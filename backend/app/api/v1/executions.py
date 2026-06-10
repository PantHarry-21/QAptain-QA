from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.db.session import get_db
from app.db.models import (
    User, ExecutionRun, ExecutionStep, ExecutionLog, ExecutionReport,
    ExecutionStatus, Scenario, ApplicationModule, Application,
)
from app.core.dependencies import get_current_user, require_app_access, require_run_access
from app.schemas.scenario import ExecutionRunResponse, ExecutionStepResponse, ReportResponse

router = APIRouter()


@router.get("/batch-history")
async def get_batch_history(
    application_id: str,
    limit: int = 30,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Return batch execution history grouped by batch_id.
    Each entry represents one 'Run All' press, with all its scenario runs.
    """
    await require_app_access(application_id, current_user, db)
    # Get all runs for the application (via Scenario join)
    result = await db.execute(
        select(ExecutionRun, Scenario.title.label("scenario_title"))
        .join(Scenario, ExecutionRun.scenario_id == Scenario.id)
        .where(Scenario.application_id == application_id)
        .order_by(ExecutionRun.created_at.desc())
        .limit(limit * 60)  # fetch enough to fill limit batches
    )
    rows = result.all()

    # Group by batch_id stored in browser_metadata
    batches: dict[str, dict] = {}
    for run, scenario_title in rows:
        meta = run.browser_metadata or {}
        batch_id = meta.get("batch_id")
        if not batch_id:
            continue
        if batch_id not in batches:
            batches[batch_id] = {
                "batch_id": batch_id,
                "started_at": run.created_at,
                "environment_id": run.environment_id,
                "runs": [],
            }
        batches[batch_id]["runs"].append({
            "run_id": run.id,
            "title": scenario_title or "",
            "status": run.status.value,
            "passed_steps": run.passed_steps or 0,
            "failed_steps": run.failed_steps or 0,
            "total_steps": run.total_steps or 0,
            "completed_at": run.completed_at,
        })

    # Sort batches newest-first, cap at limit
    sorted_batches = sorted(
        batches.values(),
        key=lambda b: b["started_at"],
        reverse=True,
    )[:limit]

    return [
        {
            "batch_id": b["batch_id"],
            "started_at": b["started_at"],
            "environment_id": b["environment_id"],
            "total": len(b["runs"]),
            "passed": sum(1 for r in b["runs"] if r["status"] == "COMPLETED"),
            "failed": sum(1 for r in b["runs"] if r["status"] == "FAILED"),
            "running": sum(1 for r in b["runs"] if r["status"] in ("RUNNING", "QUEUED")),
            "runs": b["runs"],
        }
        for b in sorted_batches
    ]


@router.get("/batch/{batch_id}")
async def get_batch_runs(
    batch_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return all runs belonging to a specific batch_id."""
    result = await db.execute(
        select(ExecutionRun, Scenario.title.label("scenario_title"), Scenario.application_id)
        .join(Scenario, ExecutionRun.scenario_id == Scenario.id)
        .order_by(ExecutionRun.created_at.asc())
    )
    rows = result.all()
    batch_rows = [
        (run, scenario_title, app_id)
        for run, scenario_title, app_id in rows
        if (run.browser_metadata or {}).get("batch_id") == batch_id
    ]
    if not batch_rows:
        raise HTTPException(status_code=404, detail="Batch not found")
    # Verify access using the first run's application
    await require_app_access(batch_rows[0][2], current_user, db)
    runs = [{"run_id": run.id, "title": scenario_title or ""} for run, scenario_title, _ in batch_rows]
    return {"batch_id": batch_id, "runs": runs}


@router.get("/{run_id}", response_model=ExecutionRunResponse)
async def get_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await require_run_access(run_id, current_user, db)
    return ExecutionRunResponse.model_validate(run)


@router.get("/{run_id}/steps", response_model=list[ExecutionStepResponse])
async def get_steps(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_run_access(run_id, current_user, db)
    result = await db.execute(
        select(ExecutionStep)
        .where(ExecutionStep.run_id == run_id)
        .order_by(ExecutionStep.sequence)
    )
    return [ExecutionStepResponse.model_validate(s) for s in result.scalars().all()]


@router.get("/{run_id}/logs")
async def get_logs(
    run_id: str,
    since_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_run_access(run_id, current_user, db)
    query = select(ExecutionLog).where(ExecutionLog.run_id == run_id)
    if since_id:
        since_ts = select(ExecutionLog.timestamp).where(ExecutionLog.id == since_id).scalar_subquery()
        query = query.where(ExecutionLog.timestamp > since_ts)
    query = query.order_by(ExecutionLog.timestamp)
    result = await db.execute(query)
    logs = result.scalars().all()
    return [
        {"id": l.id, "timestamp": l.timestamp, "level": l.level,
         "category": l.category, "message": l.message, "metadata": l.extra}
        for l in logs
    ]


@router.get("/{run_id}/report", response_model=Optional[ReportResponse])
async def get_report(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await require_run_access(run_id, current_user, db)
    result = await db.execute(select(ExecutionReport).where(ExecutionReport.run_id == run_id))
    report = result.scalar_one_or_none()
    if not report:
        return None
    return ReportResponse.model_validate(report)


@router.get("/batch/{batch_id}/summary")
async def get_batch_summary(
    batch_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregate run report for a batch — the summary a QA lead would write after
    executing a full suite: pass/fail counts, root-cause breakdown, module health,
    and the specific scenarios that need attention.
    """
    # Load all runs in this batch
    result = await db.execute(
        select(ExecutionRun, Scenario.title.label("scenario_title"), Scenario.module_id, Scenario.application_id)
        .join(Scenario, ExecutionRun.scenario_id == Scenario.id)
        .order_by(ExecutionRun.created_at.asc())
    )
    rows = result.all()
    batch_rows_full = [
        (run, title, mid, app_id)
        for run, title, mid, app_id in rows
        if (run.browser_metadata or {}).get("batch_id") == batch_id
    ]
    if not batch_rows_full:
        raise HTTPException(status_code=404, detail="Batch not found")
    await require_app_access(batch_rows_full[0][3], current_user, db)
    batch_runs = [(run, title, mid) for run, title, mid, _ in batch_rows_full]

    # Load all failed steps with error_type for root-cause breakdown
    run_ids = [r.id for r, _, _ in batch_runs]
    steps_result = await db.execute(
        select(ExecutionStep.run_id, ExecutionStep.error_type, ExecutionStep.action_type)
        .where(
            ExecutionStep.run_id.in_(run_ids),
            ExecutionStep.status.in_(["FAILED", "failed"]),
        )
    )
    failed_steps = steps_result.all()

    # Root-cause breakdown
    error_type_counts: dict[str, int] = {}
    for _, error_type, _ in failed_steps:
        key = error_type or "unknown"
        error_type_counts[key] = error_type_counts.get(key, 0) + 1

    # Load module names for module health table
    module_ids = list({mid for _, _, mid in batch_runs if mid})
    module_names: dict[str, str] = {}
    if module_ids:
        mods_result = await db.execute(
            select(ApplicationModule.id, ApplicationModule.name)
            .where(ApplicationModule.id.in_(module_ids))
        )
        module_names = {mid: name for mid, name in mods_result.all()}

    # Per-module health
    module_health: dict[str, dict] = {}
    for run, title, mid in batch_runs:
        key = mid or "__unlinked__"
        if key not in module_health:
            module_health[key] = {
                "module_id": mid,
                "module_name": module_names.get(mid, "Unlinked") if mid else "Unlinked",
                "total": 0, "passed": 0, "failed": 0, "skipped": 0,
            }
        module_health[key]["total"] += 1
        if run.status == ExecutionStatus.COMPLETED:
            module_health[key]["passed"] += 1
        elif run.status == ExecutionStatus.FAILED:
            module_health[key]["failed"] += 1
        else:
            module_health[key]["skipped"] += 1

    # Scenarios needing attention — failed ones with their error counts
    attention_runs = []
    failed_step_by_run: dict[str, list] = {}
    for run_id, error_type, action_type in failed_steps:
        failed_step_by_run.setdefault(run_id, []).append(error_type or "unknown")

    for run, title, mid in batch_runs:
        if run.status == ExecutionStatus.FAILED:
            errors = failed_step_by_run.get(run.id, [])
            top_cause = max(set(errors), key=errors.count) if errors else "unknown"
            attention_runs.append({
                "run_id": run.id,
                "scenario_title": title or "",
                "module_name": module_names.get(mid, "Unlinked") if mid else "Unlinked",
                "failed_steps": run.failed_steps or 0,
                "total_steps": run.total_steps or 0,
                "top_error_type": top_cause,
                "error_message": run.error_message or "",
            })

    total = len(batch_runs)
    passed = sum(1 for r, _, _ in batch_runs if r.status == ExecutionStatus.COMPLETED)
    failed = sum(1 for r, _, _ in batch_runs if r.status == ExecutionStatus.FAILED)
    skipped = total - passed - failed

    # Overall quality score: 0-100
    quality_score = round((passed / total) * 100) if total else 0

    return {
        "batch_id": batch_id,
        "summary": {
            "total": total,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "quality_score": quality_score,
            "pass_rate_pct": quality_score,
        },
        "root_cause_breakdown": [
            {"error_type": k, "count": v, "pct": round(v / max(len(failed_steps), 1) * 100)}
            for k, v in sorted(error_type_counts.items(), key=lambda x: -x[1])
        ],
        "module_health": sorted(module_health.values(), key=lambda m: -m["failed"]),
        "scenarios_needing_attention": sorted(
            attention_runs, key=lambda r: -r["failed_steps"]
        ),
    }


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    run = await require_run_access(run_id, current_user, db)
    if run.status not in (ExecutionStatus.PENDING, ExecutionStatus.QUEUED, ExecutionStatus.RUNNING):
        raise HTTPException(status_code=409, detail="Run is not cancellable")

    run.status = ExecutionStatus.CANCELLED
    from app.realtime.manager import connection_manager
    await connection_manager.broadcast_json({
        "event": "run_cancelled",
        "run_id": run_id,
    })
    await db.commit()
    return {"status": "cancelled"}
