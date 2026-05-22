"""
Execution Job — Enqueues and processes execution runs.
Uses asyncio directly (with optional Redis/Celery for scale).
"""
from __future__ import annotations
import asyncio
from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ExecutionRun, ExecutionPlan, ExecutionStatus

log = structlog.get_logger()

# Track active runs (in-process for single-server; replace with Celery for scale)
_active_runs: dict[str, asyncio.Task] = {}


async def enqueue_execution(
    db: AsyncSession,
    plan: ExecutionPlan,
    environment_id: str,
    credential_id: str | None,
    triggered_by: str,
) -> ExecutionRun:
    """Create an ExecutionRun and schedule it for execution."""
    run = ExecutionRun(
        scenario_id=plan.scenario_id,
        plan_id=plan.id,
        environment_id=environment_id,
        credential_id=credential_id,
        status=ExecutionStatus.QUEUED,
        triggered_by=triggered_by,
    )
    db.add(run)
    await db.commit()

    # Schedule execution (non-blocking)
    asyncio.create_task(_run_execution(run.id))
    log.info("Execution queued", run_id=run.id)
    return run


async def _run_execution(run_id: str):
    """Execute a run in the background."""
    from app.db.session import AsyncSessionFactory
    from app.execution.executor import ExecutionOrchestrator

    async with AsyncSessionFactory() as db:
        try:
            orchestrator = ExecutionOrchestrator(db)
            await orchestrator.execute_run(run_id)
        except Exception as e:
            log.exception("Background execution failed", run_id=run_id, error=str(e))
