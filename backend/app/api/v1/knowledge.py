from __future__ import annotations
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.session import get_db
from app.db.models import (
    User, ApplicationModule, ApplicationPage, ApplicationWorkflow,
    SemanticElement, Scenario, ExecutionStep, ExecutionRun, ExecutionPlan,
)
from app.core.dependencies import get_current_user

router = APIRouter()


@router.get("/applications/{application_id}/modules")
async def get_modules(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApplicationModule)
        .where(ApplicationModule.application_id == application_id)
        .order_by(ApplicationModule.order_index)
    )
    modules = result.scalars().all()
    return [
        {
            "id": m.id,
            "name": m.name,
            "description": m.description,
            "url_pattern": m.url_pattern,
            "icon": m.icon,
            "semantic_tags": m.semantic_tags,
        }
        for m in modules
    ]


@router.get("/modules/{module_id}/pages")
async def get_pages(
    module_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApplicationPage).where(ApplicationPage.module_id == module_id)
    )
    pages = result.scalars().all()
    return [
        {
            "id": p.id,
            "title": p.title,
            "url": p.url,
            "page_type": p.page_type,
            "semantic_map": p.semantic_map,
            "forms": p.forms,
            "tables": p.tables,
            "dynamic_behaviors": p.dynamic_behaviors,
        }
        for p in pages
    ]


@router.get("/modules/{module_id}/workflows")
async def get_workflows(
    module_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ApplicationWorkflow).where(ApplicationWorkflow.module_id == module_id)
    )
    workflows = result.scalars().all()
    return [
        {
            "id": w.id,
            "name": w.name,
            "description": w.description,
            "workflow_type": w.workflow_type,
            "stages": w.stages,
            "entry_point": w.entry_point,
            "success_indicators": w.success_indicators,
        }
        for w in workflows
    ]


@router.get("/applications/{application_id}/coverage")
async def get_coverage(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    KG coverage matrix for an application.
    Returns per-module explored/KG status and overall summary — used by the
    coverage dashboard to answer: "which modules have been tested, which haven't?"
    """
    # Load all modules
    mods_result = await db.execute(
        select(ApplicationModule)
        .where(ApplicationModule.application_id == application_id)
        .order_by(ApplicationModule.order_index)
    )
    modules = list(mods_result.scalars().all())
    if not modules:
        return {"modules": [], "summary": {"modules_total": 0, "modules_explored": 0,
                "scenarios_total": 0, "scenarios_kg_backed": 0, "kg_coverage_pct": 0}}

    module_ids = [m.id for m in modules]

    # Batch-load: pages per module (to determine explored status + last_explored_at)
    pages_result = await db.execute(
        select(ApplicationPage.module_id, func.count(ApplicationPage.id), func.max(ApplicationPage.discovered_at))
        .where(ApplicationPage.module_id.in_(module_ids))
        .group_by(ApplicationPage.module_id)
    )
    pages_by_module: dict[str, tuple[int, str | None]] = {}
    for mid, cnt, last_at in pages_result.all():
        pages_by_module[mid] = (cnt, last_at.isoformat() if last_at else None)

    # Batch-load: KG workflow types per module
    wf_result = await db.execute(
        select(ApplicationWorkflow.module_id, ApplicationWorkflow.workflow_type)
        .where(ApplicationWorkflow.module_id.in_(module_ids))
    )
    wf_by_module: dict[str, list[str]] = {}
    for mid, wtype in wf_result.all():
        wf_by_module.setdefault(mid, []).append(wtype)

    # Batch-load: scenario counts per module
    sc_result = await db.execute(
        select(Scenario.module_id, func.count(Scenario.id))
        .where(
            Scenario.application_id == application_id,
            Scenario.module_id.in_(module_ids),
        )
        .group_by(Scenario.module_id)
    )
    sc_by_module: dict[str, int] = {mid: cnt for mid, cnt in sc_result.all()}

    # Batch-load: KG-backed scenario counts per module
    kg_sc_result = await db.execute(
        select(Scenario.module_id, func.count(Scenario.id))
        .where(
            Scenario.application_id == application_id,
            Scenario.module_id.in_(module_ids),
            Scenario.source == "kg_generated",
        )
        .group_by(Scenario.module_id)
    )
    kg_sc_by_module: dict[str, int] = {mid: cnt for mid, cnt in kg_sc_result.all()}

    # Build per-module rows
    module_rows = []
    total_scenarios = 0
    total_kg_scenarios = 0
    explored_count = 0

    for m in modules:
        pages_info = pages_by_module.get(m.id, (0, None))
        page_count, last_explored = pages_info
        explored = page_count > 0
        kg_types = wf_by_module.get(m.id, [])
        sc_total = sc_by_module.get(m.id, 0)
        sc_kg = kg_sc_by_module.get(m.id, 0)
        coverage_pct = int(sc_kg / sc_total * 100) if sc_total else 0

        if explored:
            explored_count += 1
        total_scenarios += sc_total
        total_kg_scenarios += sc_kg

        module_rows.append({
            "module_id": m.id,
            "module_name": m.name,
            "explored": explored,
            "pages_discovered": page_count,
            "last_explored_at": last_explored,
            "kg_workflow_types": kg_types,
            "kg_workflows_count": len(kg_types),
            "scenarios_total": sc_total,
            "scenarios_kg_backed": sc_kg,
            "kg_coverage_pct": coverage_pct,
            "status": (
                "kg_ready" if kg_types else
                "explored" if explored else
                "not_explored"
            ),
        })

    overall_pct = int(total_kg_scenarios / total_scenarios * 100) if total_scenarios else 0

    return {
        "modules": module_rows,
        "summary": {
            "modules_total": len(modules),
            "modules_explored": explored_count,
            "modules_kg_ready": sum(1 for r in module_rows if r["kg_workflows_count"] > 0),
            "scenarios_total": total_scenarios,
            "scenarios_kg_backed": total_kg_scenarios,
            "kg_coverage_pct": overall_pct,
        },
    }


@router.get("/applications/{application_id}/drift")
async def get_selector_drift(
    application_id: str,
    lookback_runs: int = 10,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Selector drift report — detects modules where KG CSS selectors are consistently
    failing across recent runs. A selector that keeps hitting selector_timeout or
    element_not_found likely means the app UI changed and the KG needs re-exploration.

    Returns a list of drifted modules + specific failing step targets so the user
    knows exactly which element needs re-recording.
    """
    # Load modules for this application
    mods_result = await db.execute(
        select(ApplicationModule)
        .where(ApplicationModule.application_id == application_id)
        .order_by(ApplicationModule.order_index)
    )
    modules = list(mods_result.scalars().all())
    module_ids = [m.id for m in modules]
    module_map = {m.id: m.name for m in modules}

    if not module_ids:
        return {"drifted_modules": [], "healthy_modules": [], "total_checked": 0}

    # Load recent runs for scenarios in this application, ordered newest-first
    runs_result = await db.execute(
        select(ExecutionRun, Scenario.module_id, ExecutionPlan.created_by_model)
        .join(Scenario, ExecutionRun.scenario_id == Scenario.id)
        .join(ExecutionPlan, ExecutionRun.plan_id == ExecutionPlan.id)
        .where(
            Scenario.application_id == application_id,
            Scenario.module_id.in_(module_ids),
            # Only runs using KG-recorded plans — AI plans may legitimately fail for other reasons
            ExecutionPlan.created_by_model == "kg_recorded",
        )
        .order_by(ExecutionRun.created_at.desc())
        .limit(lookback_runs * len(module_ids))
    )
    runs_rows = runs_result.all()

    if not runs_rows:
        return {"drifted_modules": [], "healthy_modules": list(module_map.values()), "total_checked": 0}

    # Group runs by module, keeping only the last N per module
    runs_by_module: dict[str, list] = {}
    for run, mid, plan_model in runs_rows:
        if mid not in runs_by_module:
            runs_by_module[mid] = []
        if len(runs_by_module[mid]) < lookback_runs:
            runs_by_module[mid].append(run)

    # For each module, load failed steps with selector-related error types
    SELECTOR_ERRORS = ("selector_timeout", "element_not_found", "element_stale")
    drift_threshold = 0.6  # >60% of recent runs failing on a selector = drift

    drifted: list[dict] = []
    healthy: list[dict] = []

    for mid, mod_runs in runs_by_module.items():
        if not mod_runs:
            continue
        run_ids = [r.id for r in mod_runs]

        # Count selector failures per step target
        steps_result = await db.execute(
            select(ExecutionStep.description, ExecutionStep.error_type, func.count(ExecutionStep.id))
            .where(
                ExecutionStep.run_id.in_(run_ids),
                ExecutionStep.error_type.in_(list(SELECTOR_ERRORS)),
            )
            .group_by(ExecutionStep.description, ExecutionStep.error_type)
        )
        failing_steps = steps_result.all()

        # Total runs for this module in our window
        total_runs = len(mod_runs)
        failed_runs = sum(1 for r in mod_runs if r.status and r.status.value == "FAILED")
        fail_rate = failed_runs / total_runs if total_runs else 0.0

        if failing_steps and fail_rate >= drift_threshold:
            # Surface the top failing selectors
            top_failures = sorted(
                [
                    {"target": desc or "", "error_type": etype, "occurrences": cnt}
                    for desc, etype, cnt in failing_steps
                ],
                key=lambda x: -x["occurrences"],
            )[:5]
            drifted.append({
                "module_id": mid,
                "module_name": module_map.get(mid, mid),
                "runs_checked": total_runs,
                "failed_runs": failed_runs,
                "fail_rate_pct": round(fail_rate * 100),
                "severity": "high" if fail_rate >= 0.8 else "medium",
                "top_failing_selectors": top_failures,
                "recommendation": (
                    f"Re-explore the '{module_map.get(mid, mid)}' module — "
                    f"{round(fail_rate*100)}% of recent KG-based runs are failing on "
                    f"selector errors, suggesting the UI has changed."
                ),
            })
        else:
            healthy.append({
                "module_id": mid,
                "module_name": module_map.get(mid, mid),
                "runs_checked": total_runs,
                "fail_rate_pct": round(fail_rate * 100),
            })

    # Sort drifted by severity
    drifted.sort(key=lambda x: -x["fail_rate_pct"])

    return {
        "drifted_modules": drifted,
        "healthy_modules": healthy,
        "total_checked": len(runs_by_module),
        "drift_detected": len(drifted) > 0,
    }
