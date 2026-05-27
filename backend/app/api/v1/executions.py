from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, ExecutionRun, ExecutionStep, ExecutionLog, ExecutionReport, ExecutionStatus, Scenario
from app.core.dependencies import get_current_user
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
        select(ExecutionRun, Scenario.title.label("scenario_title"))
        .join(Scenario, ExecutionRun.scenario_id == Scenario.id)
        .order_by(ExecutionRun.created_at.asc())
    )
    rows = result.all()
    runs = [
        {"run_id": run.id, "title": scenario_title or ""}
        for run, scenario_title in rows
        if (run.browser_metadata or {}).get("batch_id") == batch_id
    ]
    if not runs:
        raise HTTPException(status_code=404, detail="Batch not found")
    return {"batch_id": batch_id, "runs": runs}


@router.get("/{run_id}", response_model=ExecutionRunResponse)
async def get_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Execution run not found")
    return ExecutionRunResponse.model_validate(run)


@router.get("/{run_id}/steps", response_model=list[ExecutionStepResponse])
async def get_steps(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
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
    query = select(ExecutionLog).where(ExecutionLog.run_id == run_id)
    if since_id:
        since_result = await db.execute(select(ExecutionLog).where(ExecutionLog.id == since_id))
        since_log = since_result.scalar_one_or_none()
        if since_log:
            query = query.where(ExecutionLog.timestamp > since_log.timestamp)
    query = query.order_by(ExecutionLog.timestamp)
    result = await db.execute(query)
    logs = result.scalars().all()
    return [
        {"id": l.id, "timestamp": l.timestamp, "level": l.level,
         "category": l.category, "message": l.message, "metadata": l.extra}
        for l in logs
    ]


@router.get("/{run_id}/report", response_model=ReportResponse | None)
async def get_report(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ExecutionReport).where(ExecutionReport.run_id == run_id))
    report = result.scalar_one_or_none()
    if not report:
        return None
    return ReportResponse.model_validate(report)


@router.post("/{run_id}/cancel")
async def cancel_run(
    run_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Execution run not found")
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
