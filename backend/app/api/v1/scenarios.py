from __future__ import annotations
import io
import json

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import openpyxl
import csv

from app.db.session import get_db
from app.db.models import (
    User, Scenario, ScenarioPriority, ExecutionPlan, ExecutionRun,
    Environment, Credential, ApplicationModule,
)
from app.core.dependencies import get_current_user
from app.schemas.scenario import (
    ScenarioCreate, ScenarioResponse,
    ExecutionPlanRequest, ExecutionPlanResponse,
    ExecutionTrigger, ExecutionRunResponse,
)
from app.intelligence.scenario_planner import ScenarioPlanner
from app.intelligence.ai_client import get_ai_client
from app.jobs.execution_job import enqueue_execution, enqueue_batch_execution

router = APIRouter()


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _parse_priority(value) -> ScenarioPriority:
    raw = str(value or "").strip().lower()
    if raw in ("critical", "p1", "blocker", "blocking", "showstopper", "block"):
        return ScenarioPriority.CRITICAL
    if raw in ("high", "p2", "major", "important", "must", "must-have"):
        return ScenarioPriority.HIGH
    if raw in ("low", "p4", "p5", "minor", "trivial", "nice to have", "nice-to-have"):
        return ScenarioPriority.LOW
    return ScenarioPriority.MEDIUM


def _enrich_scenario(s: Scenario, modules_by_id: dict) -> dict:
    """Return a scenario dict with module_name/url fields for the frontend."""
    mod = modules_by_id.get(s.module_id) if s.module_id else None
    return {
        "id": s.id,
        "application_id": s.application_id,
        "title": s.title,
        "description": s.description,
        "priority": s.priority.value if s.priority else "MEDIUM",
        "tags": s.tags or [],
        "module_id": s.module_id,
        "module_name": mod.name if mod else None,
        "module_url": mod.url_pattern if mod else None,
        "source": s.source,
        "is_active": s.is_active,
        "created_at": s.created_at.isoformat() if s.created_at else None,
    }


async def _load_modules_by_id(db: AsyncSession, scenarios: list[Scenario]) -> dict:
    module_ids = {s.module_id for s in scenarios if s.module_id}
    if not module_ids:
        return {}
    result = await db.execute(
        select(ApplicationModule).where(ApplicationModule.id.in_(module_ids))
    )
    return {m.id: m for m in result.scalars().all()}


def _extract_docx_text(content: bytes) -> str:
    from docx import Document  # python-docx
    doc = Document(io.BytesIO(content))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _extract_pdf_text(content: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(content))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_excel_test_cases(content: bytes) -> list[dict]:
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active

    raw_headers = list(next(ws.iter_rows(min_row=1, max_row=1, values_only=True), []))
    headers = [str(h).strip().lower() if h is not None else "" for h in raw_headers]

    # ── Column detection ──────────────────────────────────────────────────────
    # Ordered preference lists: earlier match wins.
    # ID/code columns are listed last so name/title columns win when both exist.
    TITLE_PREFERENCES = [
        # Tier 1 — explicit name/title columns
        {"title", "test case name", "test case title", "tc name", "tc title",
         "case name", "scenario name", "scenario title", "test name", "name"},
        # Tier 2 — generic scenario/case without "id"
        {"scenario", "test case", "test_case", "testcase", "test scenario", "case"},
        # Tier 3 — bare "test" or any id-like column (last resort)
        {"test", "test case id", "tc id", "test id", "tc no", "test no"},
    ]
    DESC_EXACT = {
        "description", "steps", "test steps", "test description", "desc",
        "expected result", "expected output", "expected", "details",
        "test steps/actions", "steps/actions", "test steps & expected results",
        "objective", "test objective", "preconditions", "pre-conditions",
    }
    PRIORITY_EXACT = {"priority", "severity", "criticality", "importance", "level"}

    def _find_title_col() -> int | None:
        for tier in TITLE_PREFERENCES:
            for i, h in enumerate(headers):
                if h in tier:
                    return i
        # Substring fallback: prefer "title" > "name" > "scenario" > "case"
        for kw in ("title", "name", "scenario", "case"):
            for i, h in enumerate(headers):
                if h and kw in h and "id" not in h:
                    return i
        # Absolute last resort: first non-empty header
        return next((i for i, h in enumerate(headers) if h), None)

    def _find_col(exact_set: set, substr_keywords: tuple) -> int | None:
        for i, h in enumerate(headers):
            if h in exact_set:
                return i
        for i, h in enumerate(headers):
            if h and any(kw in h for kw in substr_keywords):
                return i
        return None

    title_col = _find_title_col()
    desc_col  = _find_col(DESC_EXACT,    ("description", "steps", "expected", "detail", "action", "objective"))
    prio_col  = _find_col(PRIORITY_EXACT, ("priority", "severity"))

    if title_col is None:
        return []

    # ── Row extraction ────────────────────────────────────────────────────────
    test_cases = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        cells = list(row)
        if all(v is None or str(v).strip() == "" for v in cells):
            continue

        raw_title = cells[title_col] if title_col < len(cells) else None
        title = str(raw_title).strip() if raw_title is not None else ""
        if not title or title.lower() in ("none", "nan", "-", "n/a", ""):
            continue

        description = ""
        if desc_col is not None and desc_col < len(cells):
            dv = cells[desc_col]
            description = str(dv).strip() if dv is not None else ""

        priority = "MEDIUM"
        if prio_col is not None and prio_col < len(cells):
            pv = cells[prio_col]
            if pv is not None:
                priority = str(pv).strip()

        test_cases.append({"title": title, "description": description, "priority": priority})

    return test_cases


_DOC_EXTRACT_SYSTEM = """You are a test case extraction engine.

Given document text from a test cases file, extract ALL test cases as a JSON array.

Return ONLY valid JSON — no markdown, no explanation:
{
  "test_cases": [
    {
      "title": "Short imperative title starting with a verb (Verify / Create / Test / Validate / Ensure)",
      "description": "What to test — 1–2 sentences describing the test objective and expected outcome",
      "priority": "CRITICAL|HIGH|MEDIUM|LOW"
    }
  ]
}

Rules:
- Extract EVERY distinct test case, test step, or numbered item from the document
- If the document has numbered items like "1. Test login", extract each one
- Infer priority: "critical / must / block / blocker" → CRITICAL; "should / important / must-have" → HIGH; default → MEDIUM
- Keep titles concise (under 100 chars) and actionable
- If the document is a general description with no clear test cases, infer sensible test cases from the described functionality"""


async def _ai_extract_test_cases(module_name: str, module_url: str, text: str) -> list[dict]:
    """Call AI to extract test cases from free-form document text (DOCX/PDF)."""
    ai = get_ai_client()
    response = await ai.complete(
        system=_DOC_EXTRACT_SYSTEM,
        user=f"MODULE: {module_name}\nMODULE URL: {module_url}\n\nDOCUMENT:\n{text[:8000]}",
        json_mode=True,
        max_tokens=4000,
    )
    try:
        extracted = response.json()
        return extracted.get("test_cases", [])
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"AI failed to parse test cases from the document: {exc}",
        ) from exc


# ─── List ─────────────────────────────────────────────────────────────────────

@router.get("")
async def list_scenarios(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Scenario)
        .where(Scenario.application_id == application_id, Scenario.is_active == True)
        .order_by(Scenario.created_at.desc())
    )
    scenarios = result.scalars().all()
    modules_by_id = await _load_modules_by_id(db, scenarios)
    return [_enrich_scenario(s, modules_by_id) for s in scenarios]


# ─── Create ───────────────────────────────────────────────────────────────────

@router.post("", response_model=ScenarioResponse, status_code=201)
async def create_scenario(
    payload: ScenarioCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    scenario = Scenario(
        application_id=payload.application_id,
        title=payload.title,
        description=payload.description,
        priority=payload.priority,
        tags=payload.tags,
        module_id=payload.module_id,
        source="manual",
        created_by=current_user.id,
    )
    db.add(scenario)
    await db.commit()
    return ScenarioResponse.model_validate(scenario)


# ─── Delete (soft) ────────────────────────────────────────────────────────────

@router.delete("/{scenario_id}", status_code=204)
async def delete_scenario(
    scenario_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Scenario).where(Scenario.id == scenario_id))
    scenario = result.scalar_one_or_none()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")
    scenario.is_active = False
    await db.commit()


# ─── Import: Excel ────────────────────────────────────────────────────────────

@router.post("/import/excel")
async def import_from_excel(
    application_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    wb = openpyxl.load_workbook(io.BytesIO(content))
    ws = wb.active
    headers = [str(c.value).strip().lower() if c.value else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]

    created = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        row_data = dict(zip(headers, row))
        title = row_data.get("title") or row_data.get("scenario") or row_data.get("test case")
        if not title:
            continue
        scenario = Scenario(
            application_id=application_id,
            title=str(title).strip(),
            description=str(row_data.get("description", "") or ""),
            priority=_parse_priority(row_data.get("priority")),
            tags=[t.strip() for t in str(row_data.get("tags", "")).split(",") if t.strip()],
            source="excel",
            created_by=current_user.id,
        )
        db.add(scenario)
        created.append(str(title).strip())

    await db.commit()
    return {"imported": len(created), "titles": created[:10]}


# ─── Import: CSV ──────────────────────────────────────────────────────────────

@router.post("/import/csv")
async def import_from_csv(
    application_id: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    created = []
    for row in reader:
        title = row.get("title") or row.get("scenario") or row.get("test_case")
        if not title:
            continue
        scenario = Scenario(
            application_id=application_id,
            title=str(title).strip(),
            description=row.get("description", ""),
            priority=_parse_priority(row.get("priority")),
            tags=[t.strip() for t in (row.get("tags", "") or "").split(",") if t.strip()],
            source="csv",
            created_by=current_user.id,
        )
        db.add(scenario)
        created.append(str(title).strip())

    await db.commit()
    return {"imported": len(created), "titles": created[:10]}


# ─── Import: Document (DOCX / PDF) ────────────────────────────────────────────

@router.post("/import/document")
async def import_from_document(
    application_id: str,
    module_name: str,
    module_url: str,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a DOCX or PDF test-cases file.
    AI extracts every test case. All are saved as Scenarios linked to a module
    with the given URL — so execution navigates there automatically.
    """
    content = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith((".xlsx", ".xls")):
        test_cases = _extract_excel_test_cases(content)
        if not test_cases:
            raise HTTPException(
                status_code=422,
                detail=(
                    "No test cases found in the Excel file. "
                    "Ensure the first row contains column headers and at least one column "
                    "is named: Title, Name, Scenario, Test Case, Test Case Name, or similar."
                ),
            )
    elif filename.endswith(".docx"):
        raw_text = _extract_docx_text(content)
        if not raw_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from the document")
        test_cases = await _ai_extract_test_cases(module_name, module_url, raw_text)
    elif filename.endswith(".pdf"):
        raw_text = _extract_pdf_text(content)
        if not raw_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from the document")
        test_cases = await _ai_extract_test_cases(module_name, module_url, raw_text)
    else:
        raise HTTPException(
            status_code=400,
            detail="Only .docx, .pdf, .xlsx, and .xls files are supported",
        )

    if not test_cases:
        raise HTTPException(status_code=422, detail="No test cases found in the document")

    # Find or create module
    mod_result = await db.execute(
        select(ApplicationModule).where(
            ApplicationModule.application_id == application_id,
            ApplicationModule.name == module_name,
        ).limit(1)
    )
    module = mod_result.scalar_one_or_none()
    if not module:
        module = ApplicationModule(
            application_id=application_id,
            name=module_name,
            url_pattern=module_url,
            description="Imported via document upload",
        )
        db.add(module)
        await db.flush()
    else:
        module.url_pattern = module_url

    # Create scenarios
    created = []
    for tc in test_cases:
        title = (tc.get("title") or "").strip()
        if not title:
            continue
        scenario = Scenario(
            application_id=application_id,
            module_id=module.id,
            title=title,
            description=tc.get("description", ""),
            priority=_parse_priority(tc.get("priority", "MEDIUM")),
            tags=["document-import"],
            source="document",
            created_by=current_user.id,
        )
        db.add(scenario)
        created.append(title)

    await db.commit()
    return {
        "imported": len(created),
        "module": module_name,
        "module_url": module_url,
        "module_id": module.id,
        "titles": created[:20],
    }


# ─── Run Batch ────────────────────────────────────────────────────────────────

class RunBatchPayload(BaseModel):
    scenario_ids: list[str]
    execution_mode: str = "functional"
    environment_id: str


@router.post("/run-batch")
async def run_batch(
    payload: RunBatchPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Execute multiple scenarios with a single browser session (BeforeAll pattern).
    One login, N scenarios executed sequentially — avoids N redundant logins.
    """
    if not payload.scenario_ids:
        raise HTTPException(status_code=400, detail="No scenario IDs provided")

    import traceback as _tb
    import structlog as _sl
    _log = _sl.get_logger()

    planner = ScenarioPlanner(db)
    plans: list = []
    scenario_map: dict[str, str] = {}  # plan_id → scenario title (for response)
    errors: list[dict] = []

    cap = 50  # max scenarios per batch
    for sid in payload.scenario_ids[:cap]:
        result = await db.execute(select(Scenario).where(Scenario.id == sid))
        scenario = result.scalar_one_or_none()
        if not scenario:
            errors.append({"scenario_id": sid, "error": "Scenario not found"})
            continue
        try:
            plan = await planner.generate_fallback_plan(scenario, payload.execution_mode)
            plans.append(plan)
            scenario_map[plan.id] = scenario.title
            _log.info("Plan created", scenario_id=sid, plan_id=plan.id)
        except Exception as plan_err:
            err_detail = f"Plan creation failed: {plan_err}\n{_tb.format_exc()[-300:]}"
            _log.error("Plan creation error", scenario_id=sid, error=err_detail)
            try:
                await db.rollback()
            except Exception:
                pass
            errors.append({"scenario_id": sid, "error": err_detail, "title": scenario.title})

    if not plans:
        return {"runs": errors, "total": len(errors), "batch_mode": True}

    try:
        runs = await enqueue_batch_execution(
            db=db,
            plans=plans,
            environment_id=payload.environment_id,
            credential_id=None,
            triggered_by=current_user.id,
        )
        run_summaries = [
            {
                "scenario_id": run.scenario_id,
                "run_id": run.id,
                "title": scenario_map.get(run.plan_id, ""),
            }
            for run in runs
        ]
        _log.info("Batch enqueued", count=len(runs))
        return {
            "runs": run_summaries + errors,
            "total": len(run_summaries),
            "batch_mode": True,
            "message": f"{len(runs)} scenarios queued as a single batch (one login, one browser)",
        }
    except Exception as e:
        err_detail = f"Batch enqueue failed: {e}\n{_tb.format_exc()[-300:]}"
        _log.error("Batch enqueue error", error=err_detail)
        raise HTTPException(status_code=500, detail=err_detail)


# ─── Generate plan ────────────────────────────────────────────────────────────

@router.post("/{scenario_id}/plan", response_model=ExecutionPlanResponse)
async def generate_execution_plan(
    scenario_id: str,
    payload: ExecutionPlanRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Scenario).where(Scenario.id == scenario_id))
    scenario = result.scalar_one_or_none()
    if not scenario:
        raise HTTPException(status_code=404, detail="Scenario not found")

    if not payload.force_regenerate:
        existing = await db.execute(
            select(ExecutionPlan)
            .where(ExecutionPlan.scenario_id == scenario_id)
            .order_by(ExecutionPlan.created_at.desc())
        )
        existing_plan = existing.scalar_one_or_none()
        if existing_plan:
            return ExecutionPlanResponse.model_validate(existing_plan)

    planner = ScenarioPlanner(db)
    try:
        plan = await planner.generate_plan(scenario, payload.execution_mode)
    except Exception as e:
        import structlog
        log = structlog.get_logger()
        log.error("Plan generation failed — using fallback plan", error=str(e))
        plan = await planner.generate_fallback_plan(scenario, payload.execution_mode)
    return ExecutionPlanResponse.model_validate(plan)


# ─── Trigger execution ────────────────────────────────────────────────────────

@router.post("/{scenario_id}/execute", response_model=ExecutionRunResponse, status_code=201)
async def trigger_execution(
    scenario_id: str,
    payload: ExecutionTrigger,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ExecutionPlan).where(ExecutionPlan.id == payload.plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(status_code=404, detail="Execution plan not found")

    run = await enqueue_execution(
        db=db,
        plan=plan,
        environment_id=payload.environment_id,
        credential_id=payload.credential_id,
        triggered_by=current_user.id,
    )
    return ExecutionRunResponse.model_validate(run)


# ─── List runs ────────────────────────────────────────────────────────────────

@router.get("/{scenario_id}/runs", response_model=list[ExecutionRunResponse])
async def list_runs(
    scenario_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ExecutionRun)
        .where(ExecutionRun.scenario_id == scenario_id)
        .order_by(ExecutionRun.created_at.desc())
    )
    return [ExecutionRunResponse.model_validate(r) for r in result.scalars().all()]
