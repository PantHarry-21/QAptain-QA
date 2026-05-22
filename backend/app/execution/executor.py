"""
Main Execution Orchestrator
Coordinates: login → plan execution → validation → reporting → memory update
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
    Environment, Credential, Application, Scenario, ExecutionReport,
    ExecutionStatus, StepStatus, RiskLevel,
)
from app.execution.browser_manager import BrowserManager
from app.execution.plan_runner import PlanRunner, StepExecutionResult
from app.execution.self_healing import SelfHealingEngine
from app.intelligence.semantic_extractor import SemanticUIExtractor
from app.intelligence.failure_analyzer import FailureAnalyzer
from app.core.security import decrypt_credential
from app.realtime.manager import connection_manager
from config import settings

log = structlog.get_logger()


class ExecutionOrchestrator:
    """
    Full lifecycle execution: from pending run → completed report.
    This is the single entry point for all test executions.
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self.failure_analyzer = FailureAnalyzer()

    async def execute_run(self, run_id: str) -> None:
        """Main execution entry point — called by background job."""
        log.info("Starting execution", run_id=run_id)

        # Load all required data
        run = await self._load_run(run_id)
        if not run:
            log.error("Run not found", run_id=run_id)
            return

        plan = await self._load_plan(run.plan_id)
        env = await self._load_environment(run.environment_id)
        credential = await self._load_credential(run.credential_id, run.plan.scenario.application_id if run.plan else None)

        if not plan or not env:
            await self._fail_run(run, "Missing plan or environment")
            return

        # Mark run as started
        run.status = ExecutionStatus.RUNNING
        run.started_at = datetime.utcnow()
        await self.db.commit()

        await self._emit_event("run_started", run_id, {
            "scenario_id": run.scenario_id,
            "plan_id": run.plan_id,
            "environment": env.name,
        })

        # Launch browser
        browser = None
        try:
            browser = BrowserManager.create()
            runner = PlanRunner(
                browser=browser,
                base_url=env.base_url,
                screenshots_dir=settings.SCREENSHOTS_DIR,
                run_id=run_id,
                event_callback=lambda e, d: asyncio.create_task(self._emit_event(e, run_id, d)),
            )

            # Step 1: Login
            login_success = await self._execute_login(
                runner=runner,
                browser=browser,
                app_id=plan.scenario.application_id if plan.scenario else None,
                credential=credential,
                env=env,
                run_id=run_id,
            )
            if not login_success:
                await self._fail_run(run, "Login failed — could not authenticate")
                return

            await self._log(run_id, "SUCCESS", "login", "Authentication completed successfully")

            # Step 2: Execute plan steps
            plan_data = plan.plan_data
            step_results = await runner.execute_plan(plan_data)

            # Step 3: Persist step results
            await self._persist_steps(run_id, plan_data.get("steps", []), step_results)

            # Step 4: Compute run summary
            summary = self._compute_summary(step_results)
            run.total_steps = summary["total"]
            run.passed_steps = summary["passed"]
            run.failed_steps = summary["failed"]
            run.healed_steps = summary["healed"]
            run.status = ExecutionStatus.COMPLETED if summary["failed"] == 0 else ExecutionStatus.FAILED
            run.completed_at = datetime.utcnow()
            await self.db.commit()

            # Step 5: Generate AI report
            await self._generate_report(run, plan_data, step_results, summary)

            # Step 6: Emit completion
            await self._emit_event("run_completed", run_id, {
                "status": run.status.value,
                "passed": summary["passed"],
                "failed": summary["failed"],
                "total": summary["total"],
            })

            log.info("Execution completed", run_id=run_id, status=run.status.value)

        except Exception as e:
            log.exception("Execution crashed", run_id=run_id, error=str(e))
            await self._fail_run(run, f"Execution error: {str(e)[:500]}")
        finally:
            if browser:
                browser.quit()

    async def _execute_login(
        self,
        runner: PlanRunner,
        browser: BrowserManager,
        app_id: str | None,
        credential,
        env,
        run_id: str,
    ) -> bool:
        """Execute login workflow using stored credentials and auth blueprint."""
        if not credential:
            log.warning("No credential — skipping login")
            return True

        await self._log(run_id, "INFO", "login", "Starting authentication workflow")

        try:
            username = credential.username
            password = decrypt_credential(credential.password_encrypted)
        except Exception as e:
            log.error("Credential decryption failed", error=str(e))
            return False

        # Navigate to app
        browser.navigate(env.base_url)

        # Use auth blueprint if available
        blueprint = credential.auth_blueprint or {}

        # Build login steps from blueprint or use semantic detection
        login_plan = self._build_login_plan(username, password, env.base_url, blueprint)

        # Execute login steps
        results = await runner.execute_plan({"workflow": "LOGIN", "steps": login_plan})
        success = all(r.success or login_plan[i].get("on_fail") == "skip"
                      for i, r in enumerate(results))

        if success:
            # Check for post-login dynamic UI (e.g., location selection)
            await asyncio.sleep(1.5)
            extractor = SemanticUIExtractor(browser.driver)
            state = extractor.extract_page_state()
            stage = state.get("workflow_stage", "")

            if "Context Selection" in stage or "Location" in stage:
                await self._log(run_id, "INFO", "login", "Dynamic context selection detected after login")
                # This will be handled as human-in-loop or workspace preference
                pref = await self._get_login_preference(app_id, "login.location")
                if pref:
                    await self._log(run_id, "INFO", "login", f"Applying saved preference: {pref}")
                    select_step = {
                        "action": "select",
                        "target": pref.get("field_label", "Location"),
                        "value": pref.get("value", ""),
                        "on_fail": "skip",
                    }
                    await runner.execute_plan({"workflow": "LOGIN_CONTEXT", "steps": [select_step]})

                    # Click sign in again
                    submit_step = {
                        "action": "click",
                        "target": "Sign In",
                        "on_fail": "skip",
                    }
                    await runner.execute_plan({"workflow": "LOGIN_SUBMIT", "steps": [submit_step]})

        return success

    def _build_login_plan(
        self,
        username: str,
        password: str,
        base_url: str,
        blueprint: dict,
    ) -> list[dict]:
        """Build login execution steps from blueprint or defaults."""
        login_url = blueprint.get("login_url", base_url)

        return [
            {"action": "navigate", "url": login_url, "description": "Navigate to login page", "on_fail": "fail"},
            {"action": "fill", "target": blueprint.get("username_field", "Username"), "value": username,
             "description": "Enter username", "on_fail": "fail"},
            {"action": "fill", "target": blueprint.get("password_field", "Password"), "value": password,
             "description": "Enter password", "on_fail": "fail"},
            {"action": "click", "target": blueprint.get("submit_button", "Sign In"),
             "description": "Click login button", "on_fail": "fail"},
            {"action": "wait_ms", "ms": 2000, "description": "Wait for login response", "on_fail": "skip"},
        ]

    async def _get_login_preference(self, app_id: str | None, key: str) -> dict | None:
        if not app_id:
            return None
        from app.db.models import WorkspacePreference
        result = await self.db.execute(
            select(WorkspacePreference).where(
                WorkspacePreference.application_id == app_id,
                WorkspacePreference.preference_key == key,
            )
        )
        pref = result.scalar_one_or_none()
        return pref.preference_value if pref else None

    async def _persist_steps(
        self,
        run_id: str,
        plan_steps: list[dict],
        results: list[StepExecutionResult],
    ):
        for idx, (step, result) in enumerate(zip(plan_steps, results)):
            status = StepStatus.PASSED if result.success else StepStatus.FAILED
            if result.success and result.healing_used:
                status = StepStatus.HEALED

            db_step = ExecutionStep(
                run_id=run_id,
                sequence=idx + 1,
                action_type=step.get("action", "unknown"),
                description=step.get("description", ""),
                plan_step=step,
                status=status,
                duration_ms=result.duration_ms,
                screenshot_path=result.screenshot_path,
                healing_triggered=result.healing_used,
                healing_attempts=result.healing_attempts,
                error_message=None if result.success else result.message,
            )
            self.db.add(db_step)

        await self.db.commit()

    async def _generate_report(
        self,
        run: ExecutionRun,
        plan_data: dict,
        results: list[StepExecutionResult],
        summary: dict,
    ):
        failed_steps = [
            {"action": r.healing_attempts[0]["selector_type"] if r.healing_attempts else "unknown",
             "description": r.message}
            for r in results if not r.success
        ]

        rca = await self.failure_analyzer.analyze_run(
            {
                "total_steps": summary["total"],
                "passed": summary["passed"],
                "failed": summary["failed"],
                "healed": summary["healed"],
                "scenario_title": plan_data.get("workflow", ""),
            },
            failed_steps,
        )

        quality_score = rca.get("quality_score", max(0, 100 - summary["failed"] * 20))

        report = ExecutionReport(
            run_id=run.id,
            risk_level=self._compute_risk_level(summary),
            quality_score=quality_score,
            summary={
                "total": summary["total"],
                "passed": summary["passed"],
                "failed": summary["failed"],
                "healed": summary["healed"],
                "pass_rate": round(summary["passed"] / max(summary["total"], 1) * 100, 1),
                "workflow": plan_data.get("workflow"),
                "duration_seconds": (
                    (datetime.utcnow() - run.started_at).total_seconds()
                    if run.started_at else 0
                ),
            },
            insights=[
                {"type": "quality", "message": rca.get("overall_health", "")},
            ] + [
                {"type": "root_cause", "cause": rc.get("cause"), "probability": rc.get("probability")}
                for rc in rca.get("root_causes", [])
            ],
            rca_analysis=rca,
            recommendations=rca.get("recommendations", []),
            timeline=plan_data.get("workflow_stages", []),
            evidence={
                "screenshots": [r.screenshot_path for r in results if r.screenshot_path],
            },
        )
        self.db.add(report)
        await self.db.commit()

    def _compute_summary(self, results: list[StepExecutionResult]) -> dict:
        total = len(results)
        passed = sum(1 for r in results if r.success and not r.healing_used)
        healed = sum(1 for r in results if r.success and r.healing_used)
        failed = sum(1 for r in results if not r.success)
        return {"total": total, "passed": passed, "healed": healed, "failed": failed}

    def _compute_risk_level(self, summary: dict) -> RiskLevel:
        if summary["failed"] == 0:
            return RiskLevel.LOW
        fail_rate = summary["failed"] / max(summary["total"], 1)
        if fail_rate < 0.2:
            return RiskLevel.MEDIUM
        if fail_rate < 0.5:
            return RiskLevel.HIGH
        return RiskLevel.CRITICAL

    async def _fail_run(self, run: ExecutionRun, reason: str):
        run.status = ExecutionStatus.FAILED
        run.error_message = reason
        run.completed_at = datetime.utcnow()
        await self.db.commit()
        await self._emit_event("run_failed", run.id, {"reason": reason})

    async def _log(self, run_id: str, level: str, category: str, message: str, metadata: dict | None = None):
        entry = ExecutionLog(
            run_id=run_id,
            level=level,
            category=category,
            message=message,
            extra=metadata or {},
        )
        self.db.add(entry)
        await self.db.commit()
        await self._emit_event("run_log", run_id, {
            "level": level,
            "category": category,
            "message": message,
        })

    async def _emit_event(self, event: str, run_id: str, data: dict):
        await connection_manager.broadcast_json({
            "event": event,
            "run_id": run_id,
            **data,
        })

    async def _load_run(self, run_id: str) -> ExecutionRun | None:
        result = await self.db.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))
        return result.scalar_one_or_none()

    async def _load_plan(self, plan_id: str) -> ExecutionPlan | None:
        result = await self.db.execute(select(ExecutionPlan).where(ExecutionPlan.id == plan_id))
        return result.scalar_one_or_none()

    async def _load_environment(self, env_id: str) -> Environment | None:
        result = await self.db.execute(select(Environment).where(Environment.id == env_id))
        return result.scalar_one_or_none()

    async def _load_credential(self, cred_id: str | None, app_id: str | None) -> Credential | None:
        if cred_id:
            result = await self.db.execute(select(Credential).where(Credential.id == cred_id))
            return result.scalar_one_or_none()
        if app_id:
            result = await self.db.execute(
                select(Credential).where(Credential.application_id == app_id).limit(1)
            )
            return result.scalar_one_or_none()
        return None
