"""
Execution Job — Enqueues and processes execution runs.
Each run (or batch) executes in its own thread with a dedicated event loop so that
synchronous Selenium calls never block the FastAPI event loop.
"""
from __future__ import annotations
import asyncio
import concurrent.futures
import os
from datetime import datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.db.models import ExecutionRun, ExecutionPlan, ExecutionStatus

log = structlog.get_logger()

# Thread pool: each execution or batch gets its own thread
_thread_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=5, thread_name_prefix="qaptain-exec"
)

# Map run_id → Future so we can cancel/track
_active_runs: dict[str, concurrent.futures.Future] = {}

# Reference to the main FastAPI event loop — set at startup, used by worker
# threads to post WebSocket broadcasts back to the main loop.
_main_loop: asyncio.AbstractEventLoop | None = None


def set_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _main_loop
    _main_loop = loop


def _run_execution_in_thread(run_id: str) -> None:
    """Entry point for a single-run worker thread."""
    asyncio.run(_run_execution_async(run_id))


async def _run_execution_async(run_id: str) -> None:
    """Async execution inside the worker thread's own event loop."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from config import settings

    # Executor selection (env vars, highest priority first):
    #   EXECUTOR=plan_driven  → PlanDrivenPlaywrightExecutor (default — KG-backed, AI-minimal)
    #   EXECUTOR=agentic      → PlaywrightMCPExecutor (legacy AI-per-step agentic loop)
    #   USE_PLAYWRIGHT_MCP=false → Selenium ExecutionOrchestrator (legacy fallback)
    executor_mode = os.environ.get("EXECUTOR", "plan_driven").lower()
    use_playwright = os.environ.get("USE_PLAYWRIGHT_MCP", "true").lower() != "false"

    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=2,
        max_overflow=2,
        echo=False,
    )
    try:
        SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with SessionFactory() as db:
            if not use_playwright:
                from app.execution.executor import ExecutionOrchestrator
                orchestrator = ExecutionOrchestrator(db, main_loop=_main_loop)
            elif executor_mode == "agentic":
                from app.execution.playwright_mcp_executor import PlaywrightMCPExecutor
                orchestrator = PlaywrightMCPExecutor(db, main_loop=_main_loop)
            else:
                from app.execution.plan_driven_executor import PlanDrivenPlaywrightExecutor
                orchestrator = PlanDrivenPlaywrightExecutor(db, main_loop=_main_loop)
            await orchestrator.execute_run(run_id)
    except Exception as e:
        log.exception("Background execution failed", run_id=run_id, error=str(e))
    finally:
        await engine.dispose()


def _run_batch_in_thread(run_ids: list[str]) -> None:
    """Entry point for a batch worker thread (BeforeAll pattern)."""
    asyncio.run(_run_batch_async(run_ids))


async def _run_batch_async(run_ids: list[str]) -> None:
    """Async batch execution — one browser, one login, N scenarios."""
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
    from app.execution.batch_executor import BatchExecutionOrchestrator
    from config import settings

    engine = create_async_engine(
        settings.DATABASE_URL,
        pool_size=2,
        max_overflow=2,
        echo=False,
    )
    try:
        SessionFactory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
        async with SessionFactory() as db:
            orchestrator = BatchExecutionOrchestrator(db, main_loop=_main_loop)
            await orchestrator.execute_batch(run_ids)
    except Exception as e:
        log.exception("Background batch execution failed", run_ids=run_ids[:5], error=str(e))
    finally:
        await engine.dispose()


async def enqueue_execution(
    db: AsyncSession,
    plan: ExecutionPlan,
    environment_id: str,
    credential_id: str | None,
    triggered_by: str,
) -> ExecutionRun:
    """Create an ExecutionRun record and submit it to the thread pool."""
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

    future = _thread_pool.submit(_run_execution_in_thread, run.id)
    _active_runs[run.id] = future
    future.add_done_callback(lambda f: _active_runs.pop(run.id, None))

    log.info("Execution queued", run_id=run.id)
    return run


async def enqueue_batch_execution(
    db: AsyncSession,
    plans: list[ExecutionPlan],
    environment_id: str,
    credential_id: str | None,
    triggered_by: str,
    batch_id: str | None = None,
) -> list[ExecutionRun]:
    """
    Create N ExecutionRun records and submit a SINGLE batch job.
    All scenarios share one browser session (BeforeAll login).
    batch_id links runs together for history queries.
    """
    runs: list[ExecutionRun] = []
    for plan in plans:
        run = ExecutionRun(
            scenario_id=plan.scenario_id,
            plan_id=plan.id,
            environment_id=environment_id,
            credential_id=credential_id,
            status=ExecutionStatus.QUEUED,
            triggered_by=triggered_by,
            browser_metadata={"batch_id": batch_id} if batch_id else {},
        )
        db.add(run)
        runs.append(run)

    await db.commit()

    run_ids = [r.id for r in runs]
    batch_key = f"batch:{run_ids[0]}"
    future = _thread_pool.submit(_run_batch_in_thread, run_ids)
    _active_runs[batch_key] = future
    future.add_done_callback(lambda f: _active_runs.pop(batch_key, None))

    log.info("Batch execution queued", count=len(run_ids), first_run=run_ids[0])
    return runs
