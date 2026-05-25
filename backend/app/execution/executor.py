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
from app.execution.validation_engine import ValidationEngine
from app.execution.state_machine import WorkflowStateMachine
from app.execution.ui_transition_engine import UITransitionEngine
from app.execution.safety_guardrails import SafetyGuardrails
from app.execution.test_data_engine import TestDataEngine
from app.execution.confidence_engine import ConfidenceEngine
from app.execution.observability import ObservabilityLayer
from app.intelligence.semantic_extractor import SemanticUIExtractor
from app.intelligence.failure_analyzer import FailureAnalyzer
from app.intelligence.workflow_memory import WorkflowMemoryEngine
from app.intelligence.domain_strategies import DomainStrategyEngine
from app.core.security import decrypt_credential
from app.realtime.manager import connection_manager
from config import settings

log = structlog.get_logger()


class ExecutionOrchestrator:
    """
    Full lifecycle execution: from pending run → completed report.
    This is the single entry point for all test executions.
    """

    def __init__(self, db: AsyncSession, main_loop=None):
        self.db = db
        self.main_loop = main_loop
        self.failure_analyzer = FailureAnalyzer()

    async def execute_run(self, run_id: str) -> None:
        """Main execution entry point — called by background job."""
        log.info("Starting execution", run_id=run_id)

        run = await self._load_run(run_id)
        if not run:
            log.error("Run not found", run_id=run_id)
            return

        plan = await self._load_plan(run.plan_id)
        env = await self._load_environment(run.environment_id)
        scenario = await self._load_scenario(run.scenario_id)
        app_id = scenario.application_id if scenario else None
        credential = await self._load_credential(run.credential_id, app_id)

        if not plan or not env:
            await self._fail_run(run, "Missing plan or environment")
            return

        run.status = ExecutionStatus.RUNNING
        run.started_at = datetime.utcnow()
        await self.db.commit()

        await self._emit_event("run_started", run_id, {
            "scenario_id": run.scenario_id,
            "plan_id": run.plan_id,
            "environment": env.name,
        })

        browser = None
        try:
            browser = BrowserManager.create()
            validation_engine = ValidationEngine(browser)
            ui_engine        = UITransitionEngine(browser)
            state_machine    = WorkflowStateMachine()
            safety           = SafetyGuardrails(env.base_url)
            test_data        = TestDataEngine()
            confidence       = ConfidenceEngine(run_id)
            obs              = ObservabilityLayer(run_id)
            runner = PlanRunner(
                browser=browser,
                base_url=env.base_url,
                screenshots_dir=settings.SCREENSHOTS_DIR,
                run_id=run_id,
                event_callback=lambda e, d: asyncio.create_task(self._emit_event(e, run_id, d)),
                validation_engine=validation_engine,
                state_machine=state_machine,
                ui_engine=ui_engine,
                safety=safety,
                test_data=test_data,
                confidence=confidence,
                observability=obs,
            )

            login_success = await self._execute_login(
                runner=runner,
                browser=browser,
                app_id=app_id,
                credential=credential,
                env=env,
                run_id=run_id,
            )
            if not login_success:
                await self._fail_run(run, "Login failed — could not authenticate")
                return

            await self._log(run_id, "SUCCESS", "login", "Authentication completed successfully")

            plan_data = plan.plan_data
            step_results = await runner.execute_plan(plan_data)

            await self._persist_steps(run_id, plan_data.get("steps", []), step_results)

            summary = self._compute_summary(step_results)
            run.total_steps = summary["total"]
            run.passed_steps = summary["passed"]
            run.failed_steps = summary["failed"]
            run.healed_steps = summary["healed"]
            run.status = ExecutionStatus.COMPLETED if summary["failed"] == 0 else ExecutionStatus.FAILED
            run.completed_at = datetime.utcnow()
            await self.db.commit()

            # Collect checkpoint results and phase tracking from step results
            checkpoint_results, workflow_context = self._extract_execution_intelligence(
                plan_data, step_results
            )
            await self._generate_report(
                run, plan_data, step_results, summary,
                checkpoint_results=checkpoint_results,
                workflow_context=workflow_context,
            )

            # Persist successful workflow intelligence for future runs
            if summary["failed"] == 0 and app_id:
                try:
                    wm = WorkflowMemoryEngine(self.db)
                    cp_pass_rate = (
                        sum(1 for cp in checkpoint_results if cp.get("passed")) / len(checkpoint_results)
                        if checkpoint_results else 1.0
                    )
                    await wm.store_successful_run(
                        app_id=app_id,
                        workflow_name=plan_data.get("workflow", ""),
                        workflow_type=plan_data.get("workflow_type", ""),
                        phases=workflow_context.get("phases_completed", []),
                        step_count=summary["total"],
                        duration_seconds=(
                            (run.completed_at - run.started_at).total_seconds()
                            if run.started_at and run.completed_at else 0
                        ),
                        checkpoint_pass_rate=cp_pass_rate,
                    )
                except Exception as _wm_err:
                    log.warning("Workflow memory write failed", error=str(_wm_err))

            await self._emit_event("run_completed", run_id, {
                "status": run.status.value,
                "passed": summary["passed"],
                "failed": summary["failed"],
                "total": summary["total"],
                "workflow_type": plan_data.get("workflow_type", ""),
                "workflow": plan_data.get("workflow", ""),
                "phases_completed": workflow_context.get("phases_completed", []),
                "phases_failed": workflow_context.get("phases_failed", []),
                "checkpoints_total": len(checkpoint_results),
                "checkpoints_passed": sum(1 for cp in checkpoint_results if cp.get("passed")),
                "qa_reasoning": (plan_data.get("qa_reasoning") or "")[:300],
            })

            log.info("Execution completed", run_id=run_id, status=run.status.value)

        except Exception as e:
            log.exception("Execution crashed", run_id=run_id, error=str(e))
            await self._fail_run(run, f"Execution error: {str(e)[:500]}")
        finally:
            if browser:
                browser.quit()

    # ─── Login ────────────────────────────────────────────────────────────────

    async def _execute_login(
        self,
        runner: PlanRunner,
        browser: BrowserManager,
        app_id: str | None,
        credential,
        env,
        run_id: str,
    ) -> bool:
        """
        Robust login flow that mirrors explore_engine._phase_login:
        - 90-second wait for Angular SPA inputs
        - Angular Material-aware field filling (JS native setter)
        - Two-step login (username → Next → password)
        - FieldInspector portal dropdown (e.g. YLIMS location selector)
        """
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

        # Navigate
        browser.navigate(env.base_url)

        # Wait up to 90s for Angular SPA to bootstrap and render login form
        await self._log(run_id, "INFO", "login", "Waiting for login form to render (up to 90s)")
        page_ready = await asyncio.to_thread(self._wait_for_any_input, browser, timeout=90)
        if not page_ready:
            await self._log(run_id, "WARNING", "login",
                "No input fields within 90s — page may be unreachable")
            return False

        # Find username + password fields (Angular Material aware)
        username_el, password_el = await asyncio.to_thread(
            self._find_login_fields_fast, browser
        )
        await self._log(run_id, "INFO", "login",
            f"Field scan: username={'found' if username_el else 'missing'}, "
            f"password={'found' if password_el else 'missing'}")

        # Two-step login: username shows first, password appears after Next
        if username_el is not None and password_el is None:
            two_step_ok = await self._try_two_step_login(
                browser, username_el, username, password, run_id
            )
            if two_step_ok is not None:
                if two_step_ok:
                    await self._handle_post_login_context(browser, app_id, run_id)
                return bool(two_step_ok)

        if username_el is None or password_el is None:
            await self._log(run_id, "WARNING", "login",
                "Login form fields not found — cannot authenticate")
            return False

        # Fill using JS native setter (works with Angular Material's change detection)
        await asyncio.to_thread(self._fill_field, browser, username_el, username)
        await asyncio.to_thread(self._fill_field, browser, password_el, password)
        await self._log(run_id, "INFO", "login", "Credentials entered — submitting")

        # Click login button
        from selenium.webdriver.common.keys import Keys
        healer = SelfHealingEngine(browser.driver)
        login_btn_found = False
        for label in ("Sign In", "Login", "Log In", "Submit", "SIGN IN"):
            result = healer.find_element(label)
            if result[0]:
                healer.click_with_healing(result[0])
                login_btn_found = True
                break
        if not login_btn_found:
            try:
                password_el.send_keys(Keys.RETURN)
            except Exception:
                pass

        await asyncio.sleep(2.5)

        # Handle post-login context selection (portal dropdown, location, etc.)
        await self._handle_post_login_context(browser, app_id, run_id)

        # Verify we left the login page
        if await asyncio.to_thread(self._is_on_login_page, browser, env.base_url):
            await self._log(run_id, "WARNING", "login",
                "Still on login page after submission — credentials may be incorrect")
            return False

        return True

    async def _try_two_step_login(
        self,
        browser: BrowserManager,
        username_el,
        username: str,
        password: str,
        run_id: str,
    ) -> bool | None:
        """
        Handle two-step login: enter username → click Next → enter password → submit.
        Returns True (success), False (failed), None (not two-step — fall through).
        """
        from selenium.webdriver.common.keys import Keys

        await self._log(run_id, "INFO", "login", "Two-step login: entering username")
        await asyncio.to_thread(self._fill_field, browser, username_el, username)
        await asyncio.sleep(0.3)

        healer = SelfHealingEngine(browser.driver)
        clicked_next = False
        for label in ("Next", "Continue", "Proceed", "Sign In", "Login"):
            result = healer.find_element(label)
            if result[0]:
                try:
                    result[0].click()
                    clicked_next = True
                    await self._log(run_id, "INFO", "login",
                        f"Two-step: clicked '{label}'")
                    break
                except Exception:
                    pass
        if not clicked_next:
            try:
                username_el.send_keys(Keys.RETURN)
                clicked_next = True
            except Exception:
                pass

        if not clicked_next:
            return None  # can't advance — fall through

        pw_appeared = await asyncio.to_thread(
            self._wait_for_password_field, browser, timeout=8
        )
        if not pw_appeared:
            return None

        _, password_el = await asyncio.to_thread(self._find_login_fields_fast, browser)
        if not password_el:
            return None

        await self._log(run_id, "INFO", "login", "Two-step: password field appeared, filling")
        await asyncio.to_thread(self._fill_field, browser, password_el, password)
        await asyncio.sleep(0.3)

        healer2 = SelfHealingEngine(browser.driver)
        submitted = False
        for label in ("Sign In", "Login", "Log In", "Submit", "SIGN IN", "Next"):
            result = healer2.find_element(label)
            if result[0]:
                healer2.click_with_healing(result[0])
                submitted = True
                break
        if not submitted:
            try:
                password_el.send_keys(Keys.RETURN)
            except Exception:
                pass

        await asyncio.sleep(4)
        still_login = await asyncio.to_thread(self._is_on_login_page, browser, "")
        if not still_login:
            await self._log(run_id, "SUCCESS", "login", "Two-step login successful")
            return True
        await self._log(run_id, "WARNING", "login", "Two-step: still on login page after submit")
        return False

    async def _handle_post_login_context(
        self,
        browser: BrowserManager,
        app_id: str | None,
        run_id: str,
    ) -> None:
        """
        Handle post-login context selection (portal dropdown, location selector, etc.)
        Mirrors explore_engine._handle_login_context_selection.
        """
        # Wait for async overlay / redirect (up to 8s with retries)
        selector_info: dict = {"type": "unknown"}
        for attempt in range(4):
            selector_info = await asyncio.to_thread(
                self._inspect_dom_for_selectors, browser
            )
            if selector_info.get("type") not in ("unknown", None):
                break
            if attempt < 3:
                await asyncio.sleep(2)

        sel_type = selector_info.get("type", "unknown")
        if sel_type == "unknown":
            return

        label = selector_info.get("label", "")
        await self._log(run_id, "INFO", "login",
            f"Post-login selector detected: {label!r} ({sel_type})")

        # Check for saved preference
        pref = await self._get_login_preference(app_id, "login.location")
        preferred_value = pref.get("value") if pref else None

        from app.intelligence.field_inspector import FieldInspector
        inspector = FieldInspector(browser.driver)

        if sel_type == "trigger_button":
            # Use FieldInspector for portal/custom dropdowns (e.g. YLIMS)
            if preferred_value:
                ok = await asyncio.to_thread(
                    inspector.select_by_label_text, label, preferred_value
                )
                if ok:
                    await self._log(run_id, "INFO", "login",
                        f"Portal selected: {preferred_value!r}")
                    await asyncio.sleep(1.5)
                    return

            # No preference — find trigger button and pick first option
            healer = SelfHealingEngine(browser.driver)
            result = healer.find_element(label)
            if result[0]:
                options = await asyncio.to_thread(inspector.get_options, result[0])
                if options:
                    first_label = options[0].label
                    ok = await asyncio.to_thread(
                        inspector.select_option, result[0], first_label
                    )
                    if ok:
                        await self._log(run_id, "INFO", "login",
                            f"Auto-selected first portal option: {first_label!r}")
                        await asyncio.sleep(1.5)
                        return

        elif sel_type in ("select", "list", "radio", "button_group"):
            options = selector_info.get("options", [])
            if options:
                target = preferred_value
                if not target:
                    first = options[0]
                    target = first.get("label") if isinstance(first, dict) else str(first)
                if target:
                    ok = await asyncio.to_thread(
                        inspector.select_by_label_text, label, target
                    )
                    if ok:
                        await self._log(run_id, "INFO", "login",
                            f"Context selected: {target!r}")
                        await asyncio.sleep(1.5)

        # After selection, click any submit/continue button
        await asyncio.sleep(0.5)
        healer = SelfHealingEngine(browser.driver)
        for btn_label in ("Sign In", "Continue", "Submit", "OK", "Proceed", "Next"):
            result = healer.find_element(btn_label)
            if result[0]:
                try:
                    result[0].click()
                    break
                except Exception:
                    pass

        await asyncio.sleep(2)

    # ─── Login helper statics ─────────────────────────────────────────────────

    @staticmethod
    def _wait_for_any_input(browser: BrowserManager, timeout: int = 30) -> bool:
        """Wait until at least one <input> appears in the DOM or iframes."""
        from selenium.webdriver.common.by import By
        import time as _t
        deadline = _t.time() + timeout
        while _t.time() < deadline:
            try:
                if browser.driver.find_elements(By.TAG_NAME, "input"):
                    return True
            except Exception:
                pass
            if int(_t.time() * 2) % 4 == 0:
                try:
                    iframes = browser.driver.find_elements(By.TAG_NAME, "iframe")
                    for iframe in iframes[:3]:
                        try:
                            browser.driver.switch_to.frame(iframe)
                            if browser.driver.find_elements(By.TAG_NAME, "input"):
                                browser.driver.switch_to.default_content()
                                return True
                        except Exception:
                            try:
                                browser.driver.switch_to.default_content()
                            except Exception:
                                pass
                except Exception:
                    pass
            _t.sleep(0.5)
        return False

    @staticmethod
    def _find_login_fields_fast(browser: BrowserManager):
        """
        Find username + password inputs without per-strategy timeouts.
        Handles Angular Material (inputs may not be visible) and iframes.
        Returns (username_el, password_el) — either may be None.
        """
        from selenium.webdriver.common.by import By
        SKIP = {"hidden", "submit", "button", "checkbox", "radio", "file", "image"}

        def scan(ctx):
            try:
                all_inputs = ctx.find_elements(By.TAG_NAME, "input")
            except Exception:
                return None, None
            pw = user = None
            for inp in all_inputs:
                try:
                    typ = (inp.get_attribute("type") or "text").lower()
                    if typ in SKIP:
                        continue
                    if typ == "password" and pw is None:
                        pw = inp
                    elif typ != "password" and user is None:
                        user = inp
                    if pw and user:
                        break
                except Exception:
                    continue
            return user, pw

        user, pw = scan(browser.driver)
        if pw:
            return user, pw

        try:
            iframes = browser.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes[:5]:
                try:
                    browser.driver.switch_to.frame(iframe)
                    user, pw = scan(browser.driver)
                    if pw:
                        return user, pw
                except Exception:
                    pass
                finally:
                    try:
                        browser.driver.switch_to.default_content()
                    except Exception:
                        pass
        except Exception:
            pass
        return None, None

    @staticmethod
    def _fill_field(browser: BrowserManager, el, value: str) -> None:
        """
        Fill input using JS native setter + framework events.
        Works with Angular Material, React, Vue change detection.
        """
        try:
            browser.execute_script("""
                const el = arguments[0];
                const value = arguments[1];
                try {
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    );
                    if (setter && setter.set) {
                        setter.set.call(el, value);
                    } else {
                        el.value = value;
                    }
                } catch(e) { el.value = value; }
                el.dispatchEvent(new Event('input',  { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                el.dispatchEvent(new Event('blur',   { bubbles: true }));
            """, el, value)
        except Exception:
            try:
                el.clear()
                el.send_keys(value)
            except Exception:
                pass

    @staticmethod
    def _wait_for_password_field(browser: BrowserManager, timeout: int = 8) -> bool:
        from selenium.webdriver.common.by import By
        import time as _t
        deadline = _t.time() + timeout
        while _t.time() < deadline:
            try:
                if browser.driver.find_elements(By.CSS_SELECTOR, 'input[type="password"]'):
                    return True
            except Exception:
                pass
            _t.sleep(0.5)
        return False

    @staticmethod
    def _is_on_login_page(browser: BrowserManager, base_url: str) -> bool:
        """Heuristic check: password input visible or login URL keywords."""
        try:
            return bool(browser.execute_script("""
                // Rich app navigation → definitely authenticated
                const navLinks = document.querySelectorAll(
                    'nav a, [role="navigation"] a, [role="menuitem"], .sidebar a'
                );
                if (navLinks.length >= 4) return false;
                // Password input → still on login
                const pwSels = [
                    'input[type="password"]',
                    'input[name*="password" i]',
                    'input[placeholder*="password" i]',
                ];
                if (pwSels.some(s => { try { return !!document.querySelector(s); } catch(e){return false;} }))
                    return true;
                const href = window.location.href.toLowerCase();
                return ['/login','/signin','/sign-in','#/login','#login'].some(p => href.includes(p));
            """))
        except Exception:
            return False

    @staticmethod
    def _inspect_dom_for_selectors(browser: BrowserManager) -> dict:
        """Quick DOM scan for post-login selector patterns (portal, select, radio, etc.)"""
        try:
            result = browser.execute_script("""
                function isVis(el) {
                    const r = el.getBoundingClientRect();
                    const s = getComputedStyle(el);
                    return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
                }
                function txt(el) { return (el.textContent||el.innerText||el.value||'').trim().replace(/\\s+/g,' '); }
                // Already in main app?
                const hasNav = !!document.querySelector('nav,[role="navigation"],[role="menubar"],[role="tablist"]');
                const richItems = Array.from(document.querySelectorAll('a[href],button,[role="menuitem"],[role="option"],li')).filter(isVis);
                if (hasNav || richItems.length >= 8) return {type:'unknown',label:'Main app',options:[]};
                // Trigger button?
                const kw = ['choose','select','pick','change','switch','set your','open'];
                const btns = Array.from(document.querySelectorAll('button,[role="button"],a')).filter(isVis).filter(el=>{
                    const t = txt(el).toLowerCase();
                    return t.length>0 && t.length<80 && kw.some(k=>t.includes(k));
                });
                if (btns.length >= 1 && btns.length <= 5) return {type:'trigger_button',label:txt(btns[0]),options:[]};
                // Native select?
                const sels = Array.from(document.querySelectorAll('select')).filter(isVis);
                if (sels.length > 0) {
                    const sel = sels[0];
                    const opts = Array.from(sel.options).filter(o=>o.text.trim()&&o.value!==''&&o.index>0).map(o=>({label:o.text.trim(),value:o.value}));
                    return {type:'select',label:sel.getAttribute('aria-label')||'Select',options:opts};
                }
                // ARIA listbox?
                const lbs = Array.from(document.querySelectorAll('[role="listbox"],[role="menu"]')).filter(isVis);
                for (const lb of lbs) {
                    const items = Array.from(lb.querySelectorAll('[role="option"],[role="menuitem"],li')).filter(isVis).filter(el=>txt(el).length>0&&txt(el).length<120);
                    if (items.length >= 2) return {type:'list',label:lb.getAttribute('aria-label')||'Select',options:items.map(el=>({label:txt(el),value:txt(el)}))};
                }
                return {type:'unknown',options:[]};
            """)
            return result if isinstance(result, dict) else {"type": "unknown", "options": []}
        except Exception:
            return {"type": "unknown", "options": []}

    # ─── Helpers ──────────────────────────────────────────────────────────────

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
        checkpoint_results: list[dict] | None = None,
        workflow_context: dict | None = None,
    ):
        cp_results = checkpoint_results or []
        wctx = workflow_context or {}

        # Build failed steps with full phase + intent context
        failed_steps = []
        for step, result in zip(plan_data.get("steps", []), results):
            if not result.success:
                failed_steps.append({
                    "action": step.get("action", "unknown"),
                    "description": step.get("description", ""),
                    "phase": result.phase or step.get("phase", ""),
                    "business_intent": result.business_intent or step.get("business_intent", ""),
                    "error_message": result.message,
                })

        rca = await self.failure_analyzer.analyze_run(
            {
                "total_steps": summary["total"],
                "passed": summary["passed"],
                "failed": summary["failed"],
                "healed": summary["healed"],
                "scenario_title": plan_data.get("goal", plan_data.get("workflow", "")),
                "workflow_type": plan_data.get("workflow_type", ""),
                "workflow": plan_data.get("workflow", ""),
            },
            failed_steps,
            checkpoint_results=cp_results,
            workflow_context=wctx,
        )

        quality_score = rca.get("quality_score", max(0, 100 - summary["failed"] * 20))
        phases_completed = wctx.get("phases_completed", [])
        phases_failed = wctx.get("phases_failed", [])

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
                "workflow_type": plan_data.get("workflow_type", ""),
                "duration_seconds": (
                    (datetime.utcnow() - run.started_at).total_seconds()
                    if run.started_at else 0
                ),
                "phases_completed": phases_completed,
                "phases_failed": phases_failed,
                "checkpoints_total": len(cp_results),
                "checkpoints_passed": sum(1 for cp in cp_results if cp.get("passed")),
            },
            insights=[
                {"type": "quality", "message": rca.get("overall_health", "")},
                {"type": "business_impact", "message": rca.get("business_impact", "")},
                {
                    "type": "workflow_analysis",
                    "phases_completed": phases_completed,
                    "phases_failed": phases_failed,
                    "completion_percent": (
                        rca.get("workflow_analysis", {}).get("workflow_completion_percent", 0)
                    ),
                },
            ] + [
                {
                    "type": "root_cause",
                    "cause": rc.get("cause"),
                    "probability": rc.get("probability"),
                    "category": rc.get("category", ""),
                }
                for rc in rca.get("root_causes", [])
            ] + [
                {
                    "type": "checkpoint",
                    "validation_type": cp.get("validation_type", ""),
                    "passed": cp.get("passed", True),
                    "confidence": cp.get("confidence", 0),
                    "description": cp.get("checkpoint_description", ""),
                    "evidence": cp.get("evidence", ""),
                    "business_explanation": cp.get("business_explanation", ""),
                }
                for cp in cp_results
            ],
            rca_analysis=rca,
            recommendations=rca.get("recommendations", []),
            timeline=plan_data.get("workflow_stages", []),
            evidence={
                "screenshots": [r.screenshot_path for r in results if r.screenshot_path],
                "qa_reasoning": plan_data.get("qa_reasoning", ""),
                "workflow_type": plan_data.get("workflow_type", ""),
                "test_strategy": plan_data.get("test_strategy", {}),
                "checkpoint_validations": cp_results,
            },
        )
        self.db.add(report)
        await self.db.commit()

    def _extract_execution_intelligence(
        self,
        plan_data: dict,
        results: list[StepExecutionResult],
    ) -> tuple[list[dict], dict]:
        """
        Extract checkpoint validation results and phase tracking from step results.
        Returns (checkpoint_results, workflow_context).
        """
        checkpoint_results = [
            r.checkpoint_result
            for r in results
            if r.checkpoint_result is not None
        ]

        # Track which phases passed/failed (a phase fails if any step in it failed)
        phases_status: dict[str, bool] = {}
        for step, result in zip(plan_data.get("steps", []), results):
            phase = result.phase or step.get("phase", "")
            if not phase:
                continue
            if phase not in phases_status:
                phases_status[phase] = True
            if not result.success:
                phases_status[phase] = False

        phases_completed = [p for p, ok in phases_status.items() if ok]
        phases_failed = [p for p, ok in phases_status.items() if not ok]

        workflow_context = {
            "workflow_type": plan_data.get("workflow_type", ""),
            "phases_completed": phases_completed,
            "phases_failed": phases_failed,
        }
        return checkpoint_results, workflow_context

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

    async def _load_run(self, run_id: str) -> ExecutionRun | None:
        result = await self.db.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))
        return result.scalar_one_or_none()

    async def _load_plan(self, plan_id: str) -> ExecutionPlan | None:
        result = await self.db.execute(select(ExecutionPlan).where(ExecutionPlan.id == plan_id))
        return result.scalar_one_or_none()

    async def _load_scenario(self, scenario_id: str) -> Scenario | None:
        result = await self.db.execute(select(Scenario).where(Scenario.id == scenario_id))
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
