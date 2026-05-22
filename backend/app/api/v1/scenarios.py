from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import openpyxl
import csv
import io

from app.db.session import get_db
from app.db.models import User, Scenario, ExecutionPlan, ExecutionRun, Environment, Credential
from app.core.dependencies import get_current_user
from app.schemas.scenario import (
    ScenarioCreate, ScenarioResponse,
    ExecutionPlanRequest, ExecutionPlanResponse,
    ExecutionTrigger, ExecutionRunResponse,
)
from app.intelligence.scenario_planner import ScenarioPlanner
from app.jobs.execution_job import enqueue_execution

router = APIRouter()


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
    return [ScenarioResponse.model_validate(s) for s in scenarios]


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

    # Check for existing plan if not forcing regeneration
    if not payload.force_regenerate:
        existing = await db.execute(
            select(ExecutionPlan)
            .where(ExecutionPlan.scenario_id == scenario_id)
            .order_by(ExecutionPlan.created_at.desc())
        )
        existing_plan = existing.scalar_one_or_none()
        if existing_plan:
            return ExecutionPlanResponse.model_validate(existing_plan)

    # Generate new plan via AI
    planner = ScenarioPlanner(db)
    plan = await planner.generate_plan(scenario, payload.execution_mode)
    return ExecutionPlanResponse.model_validate(plan)


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


def _parse_priority(value):
    from app.db.models import ScenarioPriority
    mapping = {"critical": "CRITICAL", "high": "HIGH", "medium": "MEDIUM", "low": "LOW"}
    return ScenarioPriority(mapping.get(str(value or "").lower(), "MEDIUM"))
