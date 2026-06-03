"""
Plan Runner — Semantic Execution Engine

Design principles:
  - AI THINKS (QAReasoningEngine generated the plan)
  - This runner EXECUTES deterministically
  - Checkpoints trigger AI validation (not every step — only key transitions)
  - Self-healing for element resolution: labels → roles → text → XPath
  - Angular Material / React / SPA-aware field filling
  - No business logic here — pure execution with semantic element resolution
"""
from __future__ import annotations
import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import structlog
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.common.exceptions import TimeoutException

from app.execution.browser_manager import BrowserManager
from app.execution.self_healing import SelfHealingEngine
from app.execution.entity_tracker import EntityTracker
from app.intelligence.semantic_extractor import SemanticUIExtractor

log = structlog.get_logger()


@dataclass
class StepExecutionResult:
    success: bool
    message: str = ""
    healing_used: bool = False
    healing_attempts: list = field(default_factory=list)
    screenshot_path: str | None = None
    duration_ms: int = 0
    state_after: dict | None = None
    checkpoint_result: dict | None = None  # AI validation result if step was a checkpoint
    phase: str = ""
    business_intent: str = ""


class PlanRunner:
    """
    Executes a structured execution plan step by step.

    The plan was already generated intelligently by QAReasoningEngine.
    This runner translates plan steps into browser actions — no reasoning here.

    Key capabilities:
    - Semantic target resolution (labels, roles, text — not CSS/XPath)
    - Angular Material / React-aware field filling (JS native setter)
    - Checkpoint validation hooks (AI validates at workflow transitions)
    - Self-healing on element not found
    - CDP-enhanced state capture
    - Cancellation: checks `_cancelled` flag between steps
    """

    def __init__(
        self,
        browser: BrowserManager,
        base_url: str,
        screenshots_dir: str,
        run_id: str,
        event_callback: Callable[[str, dict], None] | None = None,
        validation_engine=None,   # Optional[ValidationEngine]
        state_machine=None,       # Optional[WorkflowStateMachine]
        ui_engine=None,           # Optional[UITransitionEngine]
        safety=None,              # Optional[SafetyGuardrails]
        test_data=None,           # Optional[TestDataEngine]
        confidence=None,          # Optional[ConfidenceEngine]
        observability=None,       # Optional[ObservabilityLayer]
    ):
        self.browser = browser
        self.base_url = base_url
        self.screenshots_dir = screenshots_dir
        self.run_id = run_id
        self.event_callback = event_callback or (lambda e, d: None)
        self.validation_engine = validation_engine
        self.state_machine = state_machine
        self.ui_engine = ui_engine
        self.safety = safety
        self.test_data = test_data
        self.confidence = confidence
        self.observability = observability
        self.healer = SelfHealingEngine(browser.driver)
        self.extractor = SemanticUIExtractor(browser.driver)
        self.entity_tracker: EntityTracker | None = None   # set by IntentOrchestrator
        self._step_counter = 0
        self._current_phase = ""
        self._recent_actions: list[str] = []
        self._cancelled = False  # set externally to abort mid-run

    async def execute_plan(
        self,
        plan_data: dict[str, Any],
    ) -> list[StepExecutionResult]:
        """Execute all steps in the plan. Returns results for each step."""
        steps = plan_data.get("steps", [])
        checkpoint_validations = plan_data.get("checkpoint_validations", [])
        results: list[StepExecutionResult] = []

        # Build a lookup: step description → checkpoint definition
        checkpoint_map: dict[str, dict] = {}
        for cv in (checkpoint_validations or []):
            after_desc = cv.get("after_description", "")
            if after_desc:
                checkpoint_map[after_desc.strip().lower()] = cv

        execution_context = {
            "workflow": plan_data.get("workflow", ""),
            "workflow_type": plan_data.get("workflow_type", ""),
            "scenario_title": plan_data.get("goal", ""),
            "phase": "",
            "recent_actions": self._recent_actions,
        }

        # Sync state machine with workflow type from the plan
        if self.state_machine:
            self.state_machine.workflow_type = plan_data.get("workflow_type", "")

        self._emit("plan_started", {
            "workflow": plan_data.get("workflow"),
            "workflow_type": plan_data.get("workflow_type", ""),
            "goal": plan_data.get("goal", ""),
            "total_steps": len(steps),
            "checkpoints": len(checkpoint_validations),
        })

        for idx, step in enumerate(steps):
            # Check cancellation flag between every step
            if self._cancelled:
                self._emit("plan_aborted", {"at_step": idx + 1, "reason": "Execution cancelled by user"})
                break

            self._step_counter = idx + 1

            # Track current phase
            phase = step.get("phase", "")
            if phase and phase != self._current_phase:
                self._current_phase = phase
                execution_context["phase"] = phase
                self._emit("phase_started", {"phase": phase, "step_index": idx})
                if self.observability:
                    self.observability.record_phase_start(phase)

            # Resolve {{template}} placeholders before execution
            if self.test_data:
                self.test_data.set_step(idx + 1)
                step = self.test_data.resolve_step(step)

            # Inject live entity references ({{live_entity}}, {{created_entity}})
            # This MUST run after test_data resolution so both systems compose
            if self.entity_tracker:
                step = self.entity_tracker.inject_into_step(step)

            # Safety guardrail check — block dangerous steps before they run
            _safety_blocked = False
            if self.safety:
                _sr = self.safety.check_step(step)
                if not _sr.allowed:
                    _safety_blocked = True
                    result = StepExecutionResult(
                        success=False,
                        message=f"[SAFETY BLOCKED] {_sr.reason}",
                    )
                    self._emit("step_blocked", {
                        "step_index": idx,
                        "reason": _sr.reason,
                        "risk_level": _sr.risk_level,
                    })

            # Lightweight DOM fingerprint before execution (for transition detection)
            _ui_before = None
            if not _safety_blocked and self.ui_engine:
                _ui_before = await asyncio.to_thread(self.ui_engine.capture)

            # Execute the step (or use the safety-blocked result above)
            if not _safety_blocked:
                result = await self._execute_step(step, idx + 1, len(steps))

            result.phase = phase
            result.business_intent = step.get("business_intent", "")
            results.append(result)

            # Observe step for entity lifecycle tracking (CRUD entity awareness)
            if self.entity_tracker:
                self.entity_tracker.observe_step(step, result, idx + 1)

            # Detect DOM transitions (modal, form, toast, row delta, navigation)
            _ui_transitions: list[str] = []
            if _ui_before is not None and self.ui_engine:
                _ui_after = await asyncio.to_thread(self.ui_engine.capture)
                _ui_transitions = self.ui_engine.detect_transitions(_ui_before, _ui_after)
                if _ui_transitions:
                    self._emit("ui_transition", {"step_index": idx, "transitions": _ui_transitions})

            # Advance workflow state machine based on step outcome + UI transitions
            if self.state_machine:
                self.state_machine.transition_from_step(step, result.success, phase, _ui_transitions)

            # Track step in observability
            if self.observability:
                self.observability.record_step(result.success, result.healing_used)

            # Track recent actions for context
            self._recent_actions.append(step.get("description", ""))
            if len(self._recent_actions) > 6:
                self._recent_actions.pop(0)

            # Emit step result event
            self._emit("step_completed", {
                "step_index": idx,
                "action": step.get("action"),
                "description": step.get("description"),
                "business_intent": step.get("business_intent", ""),
                "phase": phase,
                "success": result.success,
                "healing_used": result.healing_used,
                "duration_ms": result.duration_ms,
            })

            # ── Checkpoint validation (AI validates workflow transition) ───────
            step_desc_lower = step.get("description", "").strip().lower()
            checkpoint_def = None
            if step.get("checkpoint"):
                # Either step is flagged as checkpoint, or matches a checkpoint_validations entry
                checkpoint_def = checkpoint_map.get(step_desc_lower) or {
                    "validation_type": "workflow_complete",
                    "description": f"Verify: {step.get('description', '')}",
                    "semantic_check": step.get("business_intent", ""),
                    "critical": False,
                }
            else:
                checkpoint_def = checkpoint_map.get(step_desc_lower)

            if checkpoint_def and result.success and self.validation_engine:
                try:
                    cv_result = await self.validation_engine.validate_checkpoint(
                        checkpoint_def,
                        {**execution_context, "recent_actions": list(self._recent_actions)},
                    )
                except (Exception, asyncio.CancelledError) as _cv_err:
                    log.warning("Checkpoint validation skipped", error=str(_cv_err))
                    cv_result = None
                if cv_result is not None:
                    result.checkpoint_result = {
                        "passed": cv_result.passed,
                        "confidence": cv_result.confidence,
                        "evidence": cv_result.evidence,
                        "business_explanation": cv_result.business_explanation,
                        "failure_detail": cv_result.failure_detail,
                        "validation_type": cv_result.validation_type,
                    }
                    self._emit("checkpoint_validated", {
                        "step_index": idx,
                        "description": step.get("description"),
                        "validation_type": cv_result.validation_type,
                        "passed": cv_result.passed,
                        "confidence": cv_result.confidence,
                        "evidence": cv_result.evidence,
                        "business_explanation": cv_result.business_explanation,
                    })
                    # If checkpoint failed and it's critical — treat step as failed
                    if not cv_result.passed and checkpoint_def.get("critical") and cv_result.confidence >= 0.7:
                        result.success = False
                        result.message = f"[CHECKPOINT FAILED] {cv_result.business_explanation}"

            # Confidence tracking from checkpoint result
            if result.checkpoint_result and self.confidence:
                _cp_conf = result.checkpoint_result.get("confidence", 0.7)
                _cp_action, _cp_reason = self.confidence.assess_checkpoint(result.checkpoint_result)
                self.confidence.record(_cp_conf, _cp_reason, phase=phase)
                if _cp_action in ("pause", "abort"):
                    self._emit("low_confidence_warning", {
                        "step_index": idx,
                        "confidence": _cp_conf,
                        "action": _cp_action,
                        "reason": _cp_reason,
                    })

            # Abort on failure if on_fail=fail
            if not result.success and step.get("on_fail", "fail") == "fail":
                # Enrich failure message with recovery hints from capability engine
                try:
                    from app.capabilities.engine_registry import get_engine_registry
                    _hints = get_engine_registry().get_recovery_plan(
                        step.get("action", ""),
                        execution_context.get("workflow_type", ""),
                        result.message,
                    )
                    if _hints:
                        result.message = result.message + "\n[Recovery hints: " + "; ".join(_hints[:3]) + "]"
                except Exception:
                    pass

                log.warning("Aborting plan — step failed", step=idx + 1,
                    action=step.get("action"), desc=step.get("description"))
                self._emit("plan_aborted", {
                    "at_step": idx + 1,
                    "reason": result.message,
                    "phase": phase,
                    "business_intent": step.get("business_intent", ""),
                })
                break

        # ── Post-plan summaries ────────────────────────────────────────────────
        if self.observability and self._current_phase:
            _final_ok = all(r.success for r in results if r.phase == self._current_phase)
            self.observability.record_phase_end(self._current_phase, _final_ok)

        if self.state_machine:
            self._emit("workflow_state_summary", self.state_machine.summary())

        if self.observability:
            self._emit("execution_metrics", self.observability.get_summary())

        if self.test_data:
            self._emit("test_data_summary", self.test_data.summary())

        return results

    async def _execute_step(
        self,
        step: dict[str, Any],
        step_num: int,
        total: int,
    ) -> StepExecutionResult:
        action = step.get("action", "")
        description = step.get("description", action)
        start = time.monotonic()

        self._emit("step_started", {
            "step_num": step_num,
            "total": total,
            "action": action,
            "description": description,
            "phase": step.get("phase", ""),
            "business_intent": step.get("business_intent", ""),
        })

        log.info("Executing step",
            step_num=step_num, action=action,
            desc=description[:60], phase=step.get("phase", ""))

        try:
            result = await self._dispatch_action(action, step)
        except Exception as e:
            result = StepExecutionResult(
                success=False,
                message=f"Unexpected error in '{description}': {str(e)[:200]}",
            )

        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result

    async def _dispatch_action(self, action: str, step: dict) -> StepExecutionResult:
        handlers = {
            "navigate": self._action_navigate,
            "click": self._action_click,
            "fill": self._action_fill,
            "clear": self._action_clear,
            "select": self._action_select,
            "key_press": self._action_key_press,
            "hover": self._action_hover,
            "assert_visible": self._action_assert_visible,
            "assert_text": self._action_assert_text,
            "assert_not_text": self._action_assert_not_text,
            "assert_url": self._action_assert_url,
            "assert_count": self._action_assert_count,
            "assert_ai_semantic": self._action_assert_ai_semantic,
            "wait_network": self._action_wait_network,
            "wait_element": self._action_wait_element,
            "wait_ms": self._action_wait_ms,
            "scroll": self._action_scroll,
            "upload": self._action_upload,
            "screenshot": self._action_screenshot,
        }
        handler = handlers.get(action)
        if not handler:
            return StepExecutionResult(success=False, message=f"Unknown action: {action}")
        return await handler(step)

    # ─── Action Handlers ──────────────────────────────────────────────────────

    async def _action_navigate(self, step: dict) -> StepExecutionResult:
        raw_url = step.get("url", "")
        if not raw_url:
            target_url = self.base_url
        elif raw_url.startswith("http"):
            target_url = raw_url
        else:
            target_url = self.base_url.rstrip("/") + "/" + raw_url.lstrip("/")

        try:
            from urllib.parse import urlparse
            current_url = self.browser.get_current_url()
            t = urlparse(target_url)
            c = urlparse(current_url)
            same_origin = (
                t.scheme == c.scheme
                and t.netloc == c.netloc
                and current_url not in ("about:blank", "data:,", "")
            )

            if same_origin:
                # ── Angular SPA: avoid full page reload to preserve in-memory JWT ──

                # Strategy 1: hash-fragment navigation (HashLocationStrategy)
                # window.location.hash = '/foo' sets URL to #/foo — no page reload.
                # Angular detects the hashchange event and routes internally.
                if t.fragment:
                    self.browser.execute_script(
                        "window.location.hash = arguments[0];", t.fragment
                    )
                    await self._wait_for_angular_render()
                    return StepExecutionResult(
                        success=True,
                        message=f"Navigated via hash #{t.fragment}",
                    )

                # Strategy 2: click a sidebar/nav link whose text matches the path segment
                nav_hint = t.path.rstrip("/").split("/")[-1].replace("-", " ").replace("_", " ").strip()
                if nav_hint and nav_hint.lower() not in ("", "index", "home", "dashboard"):
                    el, _, _ = self.healer.find_element(nav_hint, "link")
                    if el:
                        ok, _ = self.healer.click_with_healing(el)
                        if ok:
                            await self._wait_for_angular_render()
                            return StepExecutionResult(
                                success=True,
                                message=f"Navigated via nav link '{nav_hint}'",
                            )

                # Strategy 3: HTML5 pushState (PathLocationStrategy)
                # Triggers Angular's router without a browser reload.
                if t.path and t.path != c.path:
                    try:
                        push_target = t.path + (("?" + t.query) if t.query else "")
                        self.browser.execute_script(
                            "window.history.pushState({}, '', arguments[0]); "
                            "window.dispatchEvent(new PopStateEvent('popstate', {state: {}}));",
                            push_target,
                        )
                        await self._wait_for_angular_render()
                        return StepExecutionResult(
                            success=True,
                            message=f"Navigated via pushState to {push_target}",
                        )
                    except Exception:
                        pass

            # Last resort: full navigation (different origin, or all SPA strategies failed)
            self.browser.navigate(target_url)
            await self._wait_for_angular_render(timeout=10.0)
            return StepExecutionResult(success=True, message=f"Navigated to {target_url}")
        except Exception as e:
            return StepExecutionResult(success=False, message=f"Navigation failed: {e}")

    async def _action_click(self, step: dict) -> StepExecutionResult:
        target = step.get("target", step.get("label", step.get("text", "")))
        element_type = step.get("element_type")

        # Try stored selectors first
        for sel in step.get("selectors", []):
            try:
                by = By.CSS_SELECTOR if sel.get("type") == "css" else By.XPATH
                element = WebDriverWait(self.browser.driver, 3).until(
                    EC.element_to_be_clickable((by, sel["value"]))
                )
                success, method = self.healer.click_with_healing(element)
                if success:
                    await self._async_settle()
                    return StepExecutionResult(
                        success=True,
                        message=f"Clicked '{target}' via stored selector",
                        screenshot_path=self._take_step_screenshot(),
                    )
            except Exception:
                continue

        # Semantic resolution via self-healer
        result_tuple = self.healer.find_element(target, element_type)
        element, strategy, attempts = result_tuple

        if element is None:
            return StepExecutionResult(
                success=False,
                message=f"Element '{target}' not found (tried all healing strategies)",
                healing_used=True,
                healing_attempts=[a.__dict__ for a in attempts],
            )

        success, method = self.healer.click_with_healing(element)
        await self._async_settle()
        return StepExecutionResult(
            success=success,
            message=f"Clicked '{target}' via {strategy}/{method}",
            healing_used=strategy != "stored_selector",
            healing_attempts=[a.__dict__ for a in attempts],
            screenshot_path=self._take_step_screenshot() if success else None,
        )

    async def _action_fill(self, step: dict) -> StepExecutionResult:
        target = step.get("target", step.get("field", ""))
        value = step.get("value", "")

        result_tuple = self.healer.find_element(target, "textbox")
        element, strategy, attempts = result_tuple

        if element is None:
            return StepExecutionResult(
                success=False,
                message=f"Input field '{target}' not found",
                healing_used=True,
                healing_attempts=[a.__dict__ for a in attempts],
            )

        try:
            # JS fill — works for <input> and <textarea> in Angular Material, React, Vue.
            # Uses the native prototype setter so Angular's ControlValueAccessor detects the change.
            # Also dispatches keydown/keyup so autocomplete/validation logic triggers.
            self.browser.execute_script("""
                const el = arguments[0];
                const value = arguments[1];
                const tag = el.tagName.toLowerCase();
                try {
                    const proto = tag === 'textarea'
                        ? window.HTMLTextAreaElement.prototype
                        : window.HTMLInputElement.prototype;
                    const setter = Object.getOwnPropertyDescriptor(proto, 'value');
                    if (setter && setter.set) {
                        setter.set.call(el, value);
                    } else {
                        el.value = value;
                    }
                } catch(e) { el.value = value; }
                ['keydown','input','keyup','change','blur'].forEach(evtName => {
                    el.dispatchEvent(new Event(evtName, { bubbles: true }));
                });
            """, element, str(value))
            return StepExecutionResult(
                success=True,
                message=f"Filled '{target}' with '{str(value)[:40]}'",
                healing_used=strategy != "stored_selector",
                healing_attempts=[a.__dict__ for a in attempts],
            )
        except Exception:
            # Fallback: standard send_keys (works when JS setter approach doesn't)
            try:
                element.clear()
                element.send_keys(str(value))
                return StepExecutionResult(
                    success=True,
                    message=f"Filled '{target}' (send_keys fallback)",
                    healing_used=strategy != "stored_selector",
                    healing_attempts=[a.__dict__ for a in attempts],
                )
            except Exception as e:
                return StepExecutionResult(success=False, message=f"Fill failed for '{target}': {e}")

    async def _action_clear(self, step: dict) -> StepExecutionResult:
        target = step.get("target", step.get("field", ""))
        result_tuple = self.healer.find_element(target, "textbox")
        element, _, _ = result_tuple
        if element is None:
            return StepExecutionResult(success=False, message=f"Field '{target}' not found for clear")
        try:
            element.clear()
            # Also dispatch events in case SPA listens to them
            self.browser.execute_script("""
                arguments[0].value = '';
                arguments[0].dispatchEvent(new Event('input', {bubbles:true}));
                arguments[0].dispatchEvent(new Event('change', {bubbles:true}));
            """, element)
            return StepExecutionResult(success=True, message=f"Cleared '{target}'")
        except Exception as e:
            return StepExecutionResult(success=False, message=f"Clear failed: {e}")

    async def _action_key_press(self, step: dict) -> StepExecutionResult:
        key_name = step.get("key", "Enter").strip()
        target = step.get("target", "")
        key_map = {
            "Enter": Keys.RETURN, "Return": Keys.RETURN,
            "Tab": Keys.TAB, "Escape": Keys.ESCAPE, "Esc": Keys.ESCAPE,
            "Space": Keys.SPACE, "Backspace": Keys.BACK_SPACE,
            "ArrowUp": Keys.ARROW_UP, "ArrowDown": Keys.ARROW_DOWN,
            "ArrowLeft": Keys.ARROW_LEFT, "ArrowRight": Keys.ARROW_RIGHT,
            "Delete": Keys.DELETE, "Home": Keys.HOME, "End": Keys.END,
        }
        key = key_map.get(key_name, key_name)

        if target:
            result_tuple = self.healer.find_element(target)
            element, _, _ = result_tuple
            if element:
                try:
                    element.send_keys(key)
                    self._wait_for_settle()
                    return StepExecutionResult(success=True, message=f"Pressed {key_name} on '{target}'")
                except Exception as e:
                    return StepExecutionResult(success=False, message=f"Key press failed: {e}")

        # No target — send to active element
        try:
            active = self.browser.driver.switch_to.active_element
            active.send_keys(key)
            self._wait_for_settle()
            return StepExecutionResult(success=True, message=f"Pressed {key_name} on active element")
        except Exception as e:
            return StepExecutionResult(success=False, message=f"Key press failed: {e}")

    async def _action_select(self, step: dict) -> StepExecutionResult:
        target = step.get("target", "")
        value = step.get("value", "")

        result_tuple = self.healer.find_element(target, "dropdown")
        element, strategy, attempts = result_tuple

        if element is None:
            return await self._handle_custom_dropdown(target, value, attempts)

        # Try native <select> first; if the element is a mat-select or custom
        # component, Select() will throw — fall through to the custom dropdown handler.
        try:
            sel = Select(element)
            try:
                sel.select_by_visible_text(str(value))
            except Exception:
                sel.select_by_value(str(value))
            return StepExecutionResult(success=True, message=f"Selected '{value}' in '{target}'")
        except Exception:
            # Not a native <select> — treat as Angular Material / custom dropdown
            return await self._handle_custom_dropdown(target, value, attempts)

    async def _handle_custom_dropdown(
        self, target: str, value: str, prior_attempts: list
    ) -> StepExecutionResult:
        from app.intelligence.field_inspector import FieldInspector
        inspector = FieldInspector(self.browser.driver)

        ok = await asyncio.to_thread(inspector.select_by_label_text, target, value)
        if ok:
            return StepExecutionResult(
                success=True,
                message=f"Selected '{value}' from custom dropdown '{target}'",
                healing_used=True,
                screenshot_path=self._take_step_screenshot(),
            )

        # Try via trigger button
        for element_type in ("combobox", "button"):
            result_tuple = self.healer.find_element(target, element_type)
            trigger, _, attempts = result_tuple
            if trigger:
                ok = await asyncio.to_thread(inspector.select_option, trigger, value)
                return StepExecutionResult(
                    success=ok,
                    message=f"{'Selected' if ok else 'Failed'} '{value}' from dropdown '{target}'",
                    healing_used=True,
                    healing_attempts=[a.__dict__ for a in attempts],
                    screenshot_path=self._take_step_screenshot(),
                )

        return StepExecutionResult(
            success=False,
            message=f"Dropdown '{target}' not found",
            healing_used=True,
            healing_attempts=[a.__dict__ for a in prior_attempts],
        )

    async def _action_assert_visible(self, step: dict) -> StepExecutionResult:
        # Use `or` so an explicit empty "text": "" falls back to "target"
        text = step.get("text") or step.get("target", "")
        timeout = step.get("timeout_ms", 10000) / 1000

        if not text:
            return StepExecutionResult(
                success=False,
                message="assert_visible step has no target — plan generation produced an incomplete step. Fix the test plan.",
            )

        # JS-based visibility check: walks only text nodes inside specific element
        # types, ignoring <script>/<style> and hidden Angular internals.
        # Works correctly with Angular Material components (mat-cell, mat-chip, etc.)
        # whose text lives in child <span> nodes rather than direct text content.
        _JS = """
        var needle = arguments[0];
        function vis(el) {
            if (!el || !el.getBoundingClientRect) return false;
            var s = window.getComputedStyle(el);
            var r = el.getBoundingClientRect();
            return s.display !== 'none' && s.visibility !== 'hidden' &&
                   parseFloat(s.opacity||'1') > 0 && r.width > 0 && r.height > 0;
        }
        // Broad selector covering standard elements + Angular Material components:
        //   - mat-snack-bar-container : success/error toasts
        //   - mat-error               : inline form validation errors
        //   - mat-hint                : field hints
        //   - [role="alert"]          : ARIA alert messages
        //   - [role="status"]         : status messages
        //   - snack-bar-container     : older Angular Material
        //   - [class*="toast"]        : generic toast classes
        //   - [class*="snack"]        : generic snackbar classes
        var els = document.querySelectorAll(
            'h1,h2,h3,h4,h5,p,span,label,td,th,li,dt,dd,div,' +
            'button,a,mat-cell,mat-header-cell,mat-label,mat-chip,mat-option,' +
            'mat-error,mat-hint,mat-snack-bar-container,snack-bar-container,' +
            'mat-list-item,mat-nav-list a,' +
            '[role="cell"],[role="columnheader"],[role="gridcell"],[role="option"],' +
            '[role="alert"],[role="status"],[role="tooltip"],' +
            '[class*="toast"],[class*="snack"],[class*="notification"],[class*="alert"],' +
            '[class*="error"],[class*="success"],[class*="message"]'
        );
        for (var i = 0; i < els.length; i++) {
            var el = els[i];
            if (!vis(el)) continue;
            // Check direct text nodes first (avoids matching hidden nested content)
            var own = '';
            for (var j = 0; j < el.childNodes.length; j++) {
                if (el.childNodes[j].nodeType === 3) own += el.childNodes[j].textContent;
            }
            if (!own.trim()) own = (el.textContent || el.innerText || '').trim();
            if (own.toLowerCase().indexOf(needle) >= 0) return true;
            var aria = (el.getAttribute('aria-label')||'').toLowerCase();
            if (aria.indexOf(needle) >= 0) return true;
        }
        return false;
        """

        text_lower = text.lower()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if self.browser.execute_script(_JS, text_lower):
                    return StepExecutionResult(success=True, message=f"'{text}' is visible")
            except Exception:
                pass
            await asyncio.sleep(0.5)

        screenshot = self._take_step_screenshot("assert_fail")
        return StepExecutionResult(
            success=False,
            message=f"Expected visible text '{text}' not found after {timeout:.0f}s",
            screenshot_path=screenshot,
        )

    async def _action_assert_text(self, step: dict) -> StepExecutionResult:
        text = step.get("text", "")
        timeout = step.get("timeout_ms", 10000) / 1000
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                if text.lower() in (self.browser.driver.page_source or "").lower():
                    return StepExecutionResult(success=True, message=f"Text '{text}' found on page")
            except Exception:
                pass
            await asyncio.sleep(0.5)
        screenshot = self._take_step_screenshot("assert_fail")
        return StepExecutionResult(
            success=False,
            message=f"Expected text '{text}' not found after {timeout:.0f}s",
            screenshot_path=screenshot,
        )

    async def _action_assert_not_text(self, step: dict) -> StepExecutionResult:
        text = step.get("text", step.get("target", ""))
        timeout = step.get("timeout_ms", 10000) / 1000
        deadline = time.monotonic() + timeout
        # Retry: element may still be transitioning away (Angular exit animations, HTTP request in flight)
        while time.monotonic() < deadline:
            try:
                if text.lower() not in (self.browser.driver.page_source or "").lower():
                    return StepExecutionResult(success=True, message=f"Confirmed '{text}' is NOT on page")
            except Exception:
                pass
            await asyncio.sleep(0.5)
        screenshot = self._take_step_screenshot("assert_fail")
        return StepExecutionResult(
            success=False,
            message=f"Text '{text}' is still on page after {timeout:.0f}s (expected to be absent)",
            screenshot_path=screenshot,
        )

    async def _action_assert_url(self, step: dict) -> StepExecutionResult:
        pattern = step.get("pattern", step.get("text", step.get("target", "")))
        current_url = self.browser.get_current_url()
        if pattern.lower() in current_url.lower():
            return StepExecutionResult(success=True, message=f"URL contains '{pattern}'")
        return StepExecutionResult(
            success=False,
            message=f"URL '{current_url}' does not contain '{pattern}'",
        )

    async def _action_assert_count(self, step: dict) -> StepExecutionResult:
        count_expr = step.get("value", step.get("count", ""))
        try:
            # Count visible data rows — Angular Material mat-row first, then standard tbody tr
            actual = self.browser.execute_script("""
                function isVis(el) {
                    var r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                }
                // Angular Material data rows (excludes header rows)
                var matRows = document.querySelectorAll(
                    'mat-row, [role="row"].mat-mdc-row, [role="row"]:not(.mat-header-row):not(.mat-mdc-header-row)'
                );
                var visible = Array.from(matRows).filter(isVis);
                if (visible.length > 0) return visible.length;
                // Standard HTML table body rows
                var tbodyRows = document.querySelectorAll('tbody tr');
                visible = Array.from(tbodyRows).filter(isVis);
                if (visible.length > 0) return visible.length;
                // Generic list items
                var listItems = document.querySelectorAll('ul li, ol li, [role="listitem"]');
                return Array.from(listItems).filter(isVis).length;
            """) or 0

            if count_expr:
                count_expr = str(count_expr).strip()
                op = ">=" if ">=" in count_expr else (">" if ">" in count_expr else
                     "<=" if "<=" in count_expr else ("<" if "<" in count_expr else "=="))
                num = int(count_expr.replace(op, "").replace("=", "").strip())
                ops = {">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
                       "<": lambda a, b: a < b, "<=": lambda a, b: a <= b,
                       "==": lambda a, b: a == b}
                passed = ops.get(op, ops[">="])(actual, num)
                if passed:
                    return StepExecutionResult(success=True, message=f"Row count: {actual} {op} {num} ✓")
                screenshot = self._take_step_screenshot("assert_fail")
                return StepExecutionResult(
                    success=False,
                    message=f"Row count check failed: found {actual} rows, expected {op} {num}",
                    screenshot_path=screenshot,
                )
            return StepExecutionResult(success=True, message=f"Found {actual} visible rows")
        except Exception as e:
            return StepExecutionResult(success=False, message=f"Count assertion failed: {e}")

    async def _action_assert_ai_semantic(self, step: dict) -> StepExecutionResult:
        """
        AI-powered semantic assertion.
        Validates a business state using the ValidationEngine.
        Only called when explicitly in the plan — not on every step.
        """
        description = step.get("description", "")
        semantic_check = step.get("text", step.get("target", description))

        if not self.validation_engine:
            return StepExecutionResult(
                success=False,
                message="assert_ai_semantic: validation engine not available — cannot perform semantic check",
            )

        checkpoint = {
            "validation_type": "workflow_complete",
            "description": description,
            "semantic_check": semantic_check,
            "critical": step.get("on_fail", "fail") == "fail",
        }
        cv = await self.validation_engine.validate_checkpoint(
            checkpoint,
            {
                "workflow": "",
                "phase": self._current_phase,
                "scenario_title": "",
                "recent_actions": list(self._recent_actions),
            },
        )
        screenshot = self._take_step_screenshot("ai_assert")
        return StepExecutionResult(
            success=cv.passed,
            message=cv.business_explanation or f"AI assertion: {'passed' if cv.passed else 'failed'}",
            screenshot_path=screenshot,
            checkpoint_result={
                "passed": cv.passed,
                "confidence": cv.confidence,
                "evidence": cv.evidence,
                "business_explanation": cv.business_explanation,
            },
        )

    async def _action_wait_network(self, step: dict) -> StepExecutionResult:
        url_substring = step.get("url_substring", "")
        timeout = step.get("timeout_ms", 15000) / 1000
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            events = self.browser.get_network_events()
            for event in events:
                if not url_substring or url_substring.lower() in event.get("url", "").lower():
                    return StepExecutionResult(
                        success=True,
                        message=f"Network activity detected" + (f" matching '{url_substring}'" if url_substring else "")
                    )
            await asyncio.sleep(0.5)

        return StepExecutionResult(
            success=False,
            message=f"No network activity{f' matching {url_substring}' if url_substring else ''} within {timeout:.0f}s",
        )

    async def _action_wait_element(self, step: dict) -> StepExecutionResult:
        target = step.get("target", "")
        timeout = step.get("timeout_ms", 10000) / 1000
        target_lower = target.lower().replace('"', '\\"')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                # Quick JS check — no Selenium wait overhead per iteration
                found = self.browser.execute_script(f"""
                    var t = "{target_lower}";
                    var els = document.querySelectorAll('*');
                    for (var i = 0; i < els.length; i++) {{
                        var el = els[i];
                        var r = el.getBoundingClientRect();
                        if (r.width === 0 && r.height === 0) continue;
                        var aria = (el.getAttribute('aria-label') || '').toLowerCase();
                        var txt  = (el.textContent || '').trim().toLowerCase().slice(0, 200);
                        if (aria.indexOf(t) >= 0 || txt.indexOf(t) >= 0) return true;
                    }}
                    return false;
                """)
                if found:
                    return StepExecutionResult(success=True, message=f"Element '{target}' appeared")
            except Exception:
                pass
            await asyncio.sleep(0.5)
        return StepExecutionResult(
            success=False, message=f"Element '{target}' did not appear within {timeout:.0f}s"
        )

    async def _action_wait_ms(self, step: dict) -> StepExecutionResult:
        ms = min(step.get("ms", 1000), 30000)
        await asyncio.sleep(ms / 1000)
        return StepExecutionResult(success=True, message=f"Waited {ms}ms")

    async def _wait_for_angular_render(self, timeout: float = 8.0):
        """
        Wait for Angular to finish rendering after a route change.
        Polls for meaningful content (nav links, buttons, or any non-empty headings).
        Falls back after timeout so execution can continue.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                count = self.browser.execute_script(
                    "return document.querySelectorAll("
                    "  'nav a, [role=\"menuitem\"], [role=\"navigation\"] a, "
                    "   button:not([disabled]), h1, h2, h3, table, mat-table'"
                    ").length;"
                )
                if (count or 0) >= 3:
                    return
            except Exception:
                pass
            await asyncio.sleep(0.4)

    async def _action_scroll(self, step: dict) -> StepExecutionResult:
        target = step.get("target")
        if target:
            result_tuple = self.healer.find_element(target)
            element, _, _ = result_tuple
            if element:
                self.browser.execute_script(
                    "arguments[0].scrollIntoView({block:'center',behavior:'smooth'});", element
                )
                return StepExecutionResult(success=True, message=f"Scrolled to '{target}'")
        else:
            direction = step.get("direction", "down")
            amount = step.get("amount", 500)
            self.browser.execute_script(
                f"window.scrollBy(0, {amount if direction == 'down' else -amount});"
            )
            return StepExecutionResult(success=True, message=f"Scrolled {direction} {amount}px")
        return StepExecutionResult(success=False, message="Scroll target not found")

    async def _action_upload(self, step: dict) -> StepExecutionResult:
        target = step.get("target", "file input")
        file_path = step.get("file_path", "")
        if not os.path.exists(file_path):
            return StepExecutionResult(success=False, message=f"File not found: {file_path}")
        result_tuple = self.healer.find_element(target, "file_upload")
        element, _, _ = result_tuple
        if element:
            element.send_keys(os.path.abspath(file_path))
            return StepExecutionResult(success=True, message=f"File uploaded: {file_path}")
        return StepExecutionResult(success=False, message="File upload input not found")

    async def _action_hover(self, step: dict) -> StepExecutionResult:
        target = step.get("target", step.get("label", step.get("text", "")))
        result_tuple = self.healer.find_element(target)
        element, strategy, attempts = result_tuple
        if element is None:
            return StepExecutionResult(
                success=False,
                message=f"Hover target '{target}' not found",
                healing_used=True,
                healing_attempts=[a.__dict__ for a in attempts],
            )
        try:
            from selenium.webdriver.common.action_chains import ActionChains
            ActionChains(self.browser.driver).move_to_element(element).perform()
            await self._async_settle(0.5)
            return StepExecutionResult(
                success=True,
                message=f"Hovered over '{target}'",
                healing_used=strategy != "stored_selector",
            )
        except Exception as e:
            return StepExecutionResult(success=False, message=f"Hover failed: {e}")

    async def _action_screenshot(self, step: dict) -> StepExecutionResult:
        path = self._take_step_screenshot("evidence")
        return StepExecutionResult(success=True, message="Screenshot captured", screenshot_path=path)

    # ─── Utilities ────────────────────────────────────────────────────────────

    def _take_step_screenshot(self, suffix: str = "") -> str | None:
        os.makedirs(self.screenshots_dir, exist_ok=True)
        ts = int(time.time() * 1000)
        fn = f"{self.run_id}_step{self._step_counter}_{suffix}_{ts}.png".replace("__", "_")
        path = os.path.join(self.screenshots_dir, fn)
        return path if self.browser.take_screenshot(path) else None

    def _wait_for_settle(self, min_wait: float = 0.3):
        """Brief synchronous DOM settle — called from sync code paths only."""
        time.sleep(min_wait)
        try:
            before = self.browser.execute_script("return document.querySelectorAll('*').length;")
            time.sleep(0.2)
            after = self.browser.execute_script("return document.querySelectorAll('*').length;")
            if abs(after - before) > 15:
                time.sleep(0.4)  # DOM still changing — wait more
        except Exception:
            pass

    async def _async_settle(self, min_wait: float = 0.3):
        """Async version of DOM settle — use inside async action handlers."""
        await asyncio.sleep(min_wait)
        try:
            before = await asyncio.to_thread(
                self.browser.execute_script, "return document.querySelectorAll('*').length;"
            )
            await asyncio.sleep(0.2)
            after = await asyncio.to_thread(
                self.browser.execute_script, "return document.querySelectorAll('*').length;"
            )
            if abs((after or 0) - (before or 0)) > 15:
                await asyncio.sleep(0.4)
        except Exception:
            pass

    def _emit(self, event: str, data: dict):
        try:
            self.event_callback(event, data)
        except Exception:
            pass
