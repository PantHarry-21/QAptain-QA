"""
Batch Execution Orchestrator — BeforeAll Pattern
One browser. One login. N scenarios run sequentially.
This is the preferred execution path for "Run All" / batch test runs.
"""
from __future__ import annotations
import asyncio
import os
import time
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    ExecutionRun, ExecutionStep, ExecutionLog, ExecutionPlan,
    Environment, Credential, Scenario, ExecutionReport,
    ExecutionStatus, StepStatus, RiskLevel,
)
from app.execution.browser_manager import BrowserManager
from app.execution.executor import ExecutionOrchestrator
from app.execution.plan_runner import PlanRunner, StepExecutionResult
from app.execution.validation_engine import ValidationEngine
from app.execution.state_machine import WorkflowStateMachine
from app.execution.ui_transition_engine import UITransitionEngine
from app.execution.safety_guardrails import SafetyGuardrails
from app.execution.test_data_engine import TestDataEngine
from app.execution.confidence_engine import ConfidenceEngine
from app.execution.observability import ObservabilityLayer
from app.intelligence.failure_analyzer import FailureAnalyzer
from app.realtime.manager import connection_manager
from config import settings

log = structlog.get_logger()


class BatchExecutionOrchestrator:
    """
    Executes a list of scenarios sharing one browser session:
      - BeforeAll: navigate + login once
      - For each scenario: execute plan steps, record results, generate report
      - AfterAll: quit browser

    This avoids N redundant logins (critical for YLIMS with 90s Angular bootstrap).
    """

    def __init__(self, db: AsyncSession, main_loop=None):
        self.db = db
        self.main_loop = main_loop
        self._single = ExecutionOrchestrator(db, main_loop)
        self.failure_analyzer = FailureAnalyzer()

    async def execute_batch(self, run_ids: list[str]) -> None:
        """Main entry point — called by background batch job."""
        if not run_ids:
            return

        log.info("Starting batch execution", count=len(run_ids), run_ids=run_ids[:5])

        # Load all runs up front
        runs = []
        for rid in run_ids:
            run = await self._single._load_run(rid)
            if run:
                runs.append(run)
            else:
                log.warning("Batch: run not found", run_id=rid)

        if not runs:
            return

        # Load shared context from the first run
        first_run = runs[0]
        env = await self._single._load_environment(first_run.environment_id)
        scenario = await self._single._load_scenario(first_run.scenario_id)
        app_id = scenario.application_id if scenario else None
        credential = await self._single._load_credential(first_run.credential_id, app_id)

        if not env:
            for run in runs:
                await self._single._fail_run(run, "Environment not found")
            return

        # Mark all runs as RUNNING
        batch_start = datetime.utcnow()
        for run in runs:
            run.status = ExecutionStatus.RUNNING
            run.started_at = batch_start
        await self.db.commit()

        await self._emit_batch_event("batch_started", run_ids, {
            "count": len(run_ids),
            "environment": env.name,
        })

        browser = None
        try:
            # ── BeforeAll: Launch browser + Login once ────────────────────────
            browser = BrowserManager.create()
            validation_engine = ValidationEngine(browser)
            ui_engine         = UITransitionEngine(browser)
            safety            = SafetyGuardrails(env.base_url)

            runner = PlanRunner(
                browser=browser,
                base_url=env.base_url,
                screenshots_dir=settings.SCREENSHOTS_DIR,
                run_id=run_ids[0],
                event_callback=lambda e, d: asyncio.create_task(
                    self._emit_event(e, run_ids[0], d)
                ),
                validation_engine=validation_engine,
                ui_engine=ui_engine,
                safety=safety,
            )

            await self._log_batch(run_ids[0], "INFO", "batch", "BeforeAll: logging in once for all scenarios")
            login_ok = await self._single._execute_login(
                runner=runner,
                browser=browser,
                app_id=app_id,
                credential=credential,
                env=env,
                run_id=run_ids[0],
            )

            if not login_ok:
                for run in runs:
                    await self._single._fail_run(run, "BeforeAll login failed")
                return

            await self._log_batch(run_ids[0], "SUCCESS", "batch",
                f"Login successful — executing {len(runs)} scenarios")

            # ── Execute each scenario ─────────────────────────────────────────
            for idx, run in enumerate(runs):
                await self._emit_event("run_started", run.id, {
                    "scenario_id": run.scenario_id,
                    "plan_id": run.plan_id,
                    "environment": env.name,
                    "batch_index": idx + 1,
                    "batch_total": len(runs),
                })

                plan = await self._single._load_plan(run.plan_id)
                if not plan:
                    await self._single._fail_run(run, "Execution plan not found")
                    continue

                # Update runner for this specific run — fresh per-scenario state
                runner.run_id = run.id
                runner.event_callback = lambda e, d, rid=run.id: asyncio.create_task(
                    self._emit_event(e, rid, d)
                )
                runner.state_machine = WorkflowStateMachine()
                runner.test_data     = TestDataEngine()
                runner.confidence    = ConfidenceEngine(run.id)
                runner.observability = ObservabilityLayer(run.id)

                await self._log_batch(run.id, "INFO", "execution",
                    f"[{idx+1}/{len(runs)}] Executing: {plan.plan_data.get('workflow', 'Scenario')}")

                step_start = datetime.utcnow()
                try:
                    step_results = await runner.execute_plan(plan.plan_data)
                except Exception as step_err:
                    log.exception("Batch step execution crashed", run_id=run.id, error=str(step_err))
                    await self._single._fail_run(run, f"Execution crashed: {str(step_err)[:300]}")
                    # Don't abort the whole batch — continue with next scenario
                    continue

                # Persist steps
                await self._single._persist_steps(
                    run.id, plan.plan_data.get("steps", []), step_results
                )

                summary = self._single._compute_summary(step_results)
                run.total_steps = summary["total"]
                run.passed_steps = summary["passed"]
                run.failed_steps = summary["failed"]
                run.healed_steps = summary["healed"]
                run.status = (
                    ExecutionStatus.COMPLETED if summary["failed"] == 0
                    else ExecutionStatus.FAILED
                )
                run.completed_at = datetime.utcnow()
                await self.db.commit()

                # Generate report with full AI intelligence context
                checkpoint_results, workflow_context = self._single._extract_execution_intelligence(
                    plan.plan_data, step_results
                )
                await self._single._generate_report(
                    run, plan.plan_data, step_results, summary,
                    checkpoint_results=checkpoint_results,
                    workflow_context=workflow_context,
                )

                await self._emit_event("run_completed", run.id, {
                    "status": run.status.value,
                    "passed": summary["passed"],
                    "failed": summary["failed"],
                    "total": summary["total"],
                    "batch_index": idx + 1,
                    "batch_total": len(runs),
                    "workflow_type": plan.plan_data.get("workflow_type", ""),
                    "phases_completed": workflow_context.get("phases_completed", []),
                    "phases_failed": workflow_context.get("phases_failed", []),
                    "checkpoints_total": len(checkpoint_results),
                    "checkpoints_passed": sum(1 for cp in checkpoint_results if cp.get("passed")),
                })

                log.info("Batch run completed",
                    run_id=run.id,
                    status=run.status.value,
                    passed=summary["passed"],
                    failed=summary["failed"],
                )

            # ── Batch summary ─────────────────────────────────────────────────
            completed = sum(1 for r in runs if r.status == ExecutionStatus.COMPLETED)
            failed = sum(1 for r in runs if r.status == ExecutionStatus.FAILED)
            await self._emit_batch_event("batch_completed", run_ids, {
                "total": len(runs),
                "completed": completed,
                "failed": failed,
                "duration_seconds": (datetime.utcnow() - batch_start).total_seconds(),
            })
            log.info("Batch execution done",
                total=len(runs), completed=completed, failed=failed)

        except Exception as e:
            log.exception("Batch execution crashed", error=str(e))
            for run in runs:
                if run.status == ExecutionStatus.RUNNING:
                    await self._single._fail_run(run, f"Batch error: {str(e)[:300]}")
        finally:
            if browser:
                browser.quit()

    # ─── Event / log helpers ──────────────────────────────────────────────────

    async def _log_batch(self, run_id: str, level: str, category: str, message: str):
        entry = ExecutionLog(
            run_id=run_id,
            level=level,
            category=category,
            message=message,
            extra={},
        )
        self.db.add(entry)
        await self.db.commit()
        await self._emit_event("run_log", run_id, {
            "level": level,
            "category": category,
            "message": message,
        })

    async def _emit_event(self, event: str, run_id: str, data: dict):
        msg = {"event": event, "run_id": run_id, **data}
        try:
            current_loop = asyncio.get_running_loop()
            if self.main_loop and self.main_loop is not current_loop and self.main_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    connection_manager.broadcast_json(msg), self.main_loop
                )
            else:
                await connection_manager.broadcast_json(msg)
        except Exception:
            pass

    async def _emit_batch_event(self, event: str, run_ids: list[str], data: dict):
        msg = {"event": event, "run_ids": run_ids, **data}
        try:
            current_loop = asyncio.get_running_loop()
            if self.main_loop and self.main_loop is not current_loop and self.main_loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    connection_manager.broadcast_json(msg), self.main_loop
                )
            else:
                await connection_manager.broadcast_json(msg)
        except Exception:
            pass
