"""
Plan Runner — Deterministic Execution Engine
AI plans ONCE. This runner executes deterministically.
No AI calls during execution unless healing fails.
"""
from __future__ import annotations
import asyncio
import os
import time
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
from app.intelligence.semantic_extractor import SemanticUIExtractor

log = structlog.get_logger()


class StepExecutionResult:
    def __init__(self, success: bool, message: str = "", healing_used: bool = False,
                 healing_attempts: list = None, screenshot_path: str | None = None,
                 duration_ms: int = 0, state_after: dict | None = None):
        self.success = success
        self.message = message
        self.healing_used = healing_used
        self.healing_attempts = healing_attempts or []
        self.screenshot_path = screenshot_path
        self.duration_ms = duration_ms
        self.state_after = state_after


class PlanRunner:
    """
    Executes a structured execution plan step by step.

    Design principles:
    - Each step is atomic
    - Healing is triggered automatically on failure
    - Screenshots captured at key stages
    - No business logic here — pure execution
    """

    def __init__(
        self,
        browser: BrowserManager,
        base_url: str,
        screenshots_dir: str,
        run_id: str,
        event_callback: Callable[[str, dict], None] | None = None,
    ):
        self.browser = browser
        self.base_url = base_url
        self.screenshots_dir = screenshots_dir
        self.run_id = run_id
        self.event_callback = event_callback or (lambda e, d: None)
        self.healer = SelfHealingEngine(browser.driver)
        self.extractor = SemanticUIExtractor(browser.driver)
        self._step_counter = 0

    async def execute_plan(
        self,
        plan_data: dict[str, Any],
    ) -> list[StepExecutionResult]:
        """Execute all steps in the plan. Returns results for each step."""
        steps = plan_data.get("steps", [])
        results = []

        self._emit("plan_started", {
            "workflow": plan_data.get("workflow"),
            "total_steps": len(steps),
        })

        for idx, step in enumerate(steps):
            self._step_counter = idx + 1
            result = await self._execute_step(step, idx + 1, len(steps))
            results.append(result)

            # Emit step result event
            self._emit("step_completed", {
                "step_index": idx,
                "action": step.get("action"),
                "description": step.get("description"),
                "success": result.success,
                "healing_used": result.healing_used,
                "duration_ms": result.duration_ms,
            })

            # Abort on failure if on_fail=fail
            if not result.success and step.get("on_fail", "fail") == "fail":
                log.warning("Aborting plan — step failed with on_fail=fail", step=idx + 1)
                self._emit("plan_aborted", {"at_step": idx + 1, "reason": result.message})
                break

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
        })

        log.info("Executing step", step_num=step_num, action=action, desc=description)

        try:
            result = await self._dispatch_action(action, step)
        except Exception as e:
            result = StepExecutionResult(
                success=False,
                message=f"Unexpected error: {str(e)[:200]}",
            )

        result.duration_ms = int((time.monotonic() - start) * 1000)
        return result

    async def _dispatch_action(self, action: str, step: dict) -> StepExecutionResult:
        handlers = {
            "navigate": self._action_navigate,
            "click": self._action_click,
            "fill": self._action_fill,
            "select": self._action_select,
            "assert_visible": self._action_assert_visible,
            "assert_text": self._action_assert_text,
            "assert_url": self._action_assert_url,
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

    async def _action_navigate(self, step: dict) -> StepExecutionResult:
        url = step.get("url", "")
        if url.startswith("/") or not url.startswith("http"):
            url = self.base_url.rstrip("/") + "/" + url.lstrip("/")

        try:
            self.browser.navigate(url)
            return StepExecutionResult(success=True, message=f"Navigated to {url}")
        except Exception as e:
            return StepExecutionResult(success=False, message=f"Navigation failed: {e}")

    async def _action_click(self, step: dict) -> StepExecutionResult:
        target = step.get("target", step.get("label", ""))
        element_type = step.get("element_type")
        timeout = step.get("timeout_ms", 10000) / 1000

        # Try stored selectors first (if available)
        stored_selectors = step.get("selectors", [])
        for sel in stored_selectors:
            try:
                by = By.CSS_SELECTOR if sel.get("type") == "css" else By.XPATH
                element = WebDriverWait(self.browser.driver, 3).until(
                    EC.element_to_be_clickable((by, sel["value"]))
                )
                success, method = self.healer.click_with_healing(element)
                if success:
                    self._wait_for_settle()
                    screenshot = self._take_step_screenshot()
                    return StepExecutionResult(
                        success=True,
                        message=f"Clicked '{target}' via stored selector",
                        screenshot_path=screenshot,
                    )
            except Exception:
                continue

        # Healing: find by semantic label
        result_tuple = self.healer.find_element(target, element_type)
        element, strategy, attempts = result_tuple

        if element is None:
            return StepExecutionResult(
                success=False,
                message=f"Element '{target}' not found after all healing strategies",
                healing_used=True,
                healing_attempts=[a.__dict__ for a in attempts],
            )

        success, method = self.healer.click_with_healing(element)
        self._wait_for_settle()
        screenshot = self._take_step_screenshot()

        return StepExecutionResult(
            success=success,
            message=f"Clicked '{target}' via {strategy} / {method}",
            healing_used=strategy != "stored_selector",
            healing_attempts=[a.__dict__ for a in attempts],
            screenshot_path=screenshot,
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
            element.clear()
            element.send_keys(str(value))
            return StepExecutionResult(
                success=True,
                message=f"Filled '{target}' with value",
                healing_used=strategy != "stored_selector",
                healing_attempts=[a.__dict__ for a in attempts],
            )
        except Exception as e:
            return StepExecutionResult(success=False, message=f"Fill failed: {e}")

    async def _action_select(self, step: dict) -> StepExecutionResult:
        target = step.get("target", "")
        value = step.get("value", "")

        result_tuple = self.healer.find_element(target, "dropdown")
        element, strategy, attempts = result_tuple

        if element is None:
            # Try custom dropdown (non-native select)
            return await self._handle_custom_dropdown(target, value, attempts)

        try:
            select = Select(element)
            try:
                select.select_by_visible_text(str(value))
            except Exception:
                select.select_by_value(str(value))
            return StepExecutionResult(success=True, message=f"Selected '{value}' in '{target}'")
        except Exception as e:
            return StepExecutionResult(success=False, message=f"Select failed: {e}")

    async def _handle_custom_dropdown(self, target: str, value: str, prior_attempts: list) -> StepExecutionResult:
        """Handle custom (non-native) dropdown menus."""
        # Click the dropdown trigger
        result_tuple = self.healer.find_element(target, "combobox")
        trigger, strategy, attempts = result_tuple
        if trigger is None:
            return StepExecutionResult(
                success=False,
                message=f"Dropdown '{target}' not found",
                healing_used=True,
                healing_attempts=prior_attempts + [a.__dict__ for a in attempts],
            )

        self.healer.click_with_healing(trigger)
        time.sleep(0.5)

        # Find and click the option
        try:
            option = WebDriverWait(self.browser.driver, 5).until(
                EC.element_to_be_clickable((
                    By.XPATH,
                    f'//*[contains(translate(normalize-space(.), "ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), "{value.lower()}") and (contains(@class, "option") or contains(@class, "item") or @role="option")]',
                ))
            )
            option.click()
            return StepExecutionResult(success=True, message=f"Selected '{value}' from custom dropdown '{target}'")
        except Exception as e:
            return StepExecutionResult(success=False, message=f"Custom dropdown selection failed: {e}")

    async def _action_assert_visible(self, step: dict) -> StepExecutionResult:
        text = step.get("text", step.get("target", ""))
        timeout = step.get("timeout_ms", 10000) / 1000

        try:
            WebDriverWait(self.browser.driver, timeout).until(
                EC.visibility_of_element_located((
                    By.XPATH,
                    f'//*[contains(normalize-space(text()), "{text}") or contains(@aria-label, "{text}")]',
                ))
            )
            return StepExecutionResult(success=True, message=f"'{text}' is visible")
        except TimeoutException:
            screenshot = self._take_step_screenshot("failure")
            return StepExecutionResult(
                success=False,
                message=f"Expected text '{text}' not visible after {timeout}s",
                screenshot_path=screenshot,
            )

    async def _action_assert_text(self, step: dict) -> StepExecutionResult:
        text = step.get("text", "")
        page_source = self.browser.driver.page_source
        if text.lower() in page_source.lower():
            return StepExecutionResult(success=True, message=f"Text '{text}' found on page")
        return StepExecutionResult(success=False, message=f"Text '{text}' not found on page")

    async def _action_assert_url(self, step: dict) -> StepExecutionResult:
        pattern = step.get("pattern", step.get("text", ""))
        current_url = self.browser.get_current_url()
        if pattern.lower() in current_url.lower():
            return StepExecutionResult(success=True, message=f"URL contains '{pattern}'")
        return StepExecutionResult(
            success=False,
            message=f"URL '{current_url}' does not contain '{pattern}'",
        )

    async def _action_wait_network(self, step: dict) -> StepExecutionResult:
        url_substring = step.get("url_substring", "")
        timeout = step.get("timeout_ms", 15000) / 1000
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            events = self.browser.get_network_events()
            for event in events:
                if url_substring.lower() in event.get("url", "").lower():
                    return StepExecutionResult(success=True, message=f"Network request matching '{url_substring}' detected")
            await asyncio.sleep(0.5)

        return StepExecutionResult(success=False, message=f"No network request matching '{url_substring}' within {timeout}s")

    async def _action_wait_element(self, step: dict) -> StepExecutionResult:
        target = step.get("target", "")
        timeout = step.get("timeout_ms", 10000) / 1000
        result_tuple = self.healer.find_element(target, timeout=timeout if hasattr(self.healer.find_element, 'timeout') else None)
        element, strategy, attempts = result_tuple
        if element:
            return StepExecutionResult(success=True, message=f"Element '{target}' appeared")
        return StepExecutionResult(success=False, message=f"Element '{target}' did not appear within {timeout}s")

    async def _action_wait_ms(self, step: dict) -> StepExecutionResult:
        ms = min(step.get("ms", 1000), 30000)  # Cap at 30 seconds
        await asyncio.sleep(ms / 1000)
        return StepExecutionResult(success=True, message=f"Waited {ms}ms")

    async def _action_scroll(self, step: dict) -> StepExecutionResult:
        target = step.get("target")
        if target:
            result_tuple = self.healer.find_element(target)
            element, _, _ = result_tuple
            if element:
                self.browser.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
                return StepExecutionResult(success=True, message=f"Scrolled to '{target}'")
        else:
            direction = step.get("direction", "down")
            amount = step.get("amount", 500)
            self.browser.execute_script(f"window.scrollBy(0, {amount if direction == 'down' else -amount});")
            return StepExecutionResult(success=True, message=f"Scrolled {direction}")
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

    async def _action_screenshot(self, step: dict) -> StepExecutionResult:
        path = self._take_step_screenshot("evidence")
        return StepExecutionResult(success=True, message="Screenshot captured", screenshot_path=path)

    def _take_step_screenshot(self, suffix: str = "") -> str | None:
        os.makedirs(self.screenshots_dir, exist_ok=True)
        timestamp = int(time.time() * 1000)
        filename = f"{self.run_id}_step{self._step_counter}_{suffix}_{timestamp}.png".replace("__", "_")
        path = os.path.join(self.screenshots_dir, filename)
        success = self.browser.take_screenshot(path)
        return path if success else None

    def _wait_for_settle(self, timeout: float = 2.0):
        """Brief wait for DOM to settle after action."""
        time.sleep(0.3)
        # Quick stability check
        try:
            before = self.browser.execute_script(
                "return document.querySelectorAll('*').length;"
            )
            time.sleep(0.3)
            after = self.browser.execute_script(
                "return document.querySelectorAll('*').length;"
            )
            if abs(after - before) > 20:
                time.sleep(0.5)  # Extra wait for active rendering
        except Exception:
            pass

    def _emit(self, event: str, data: dict):
        try:
            self.event_callback(event, data)
        except Exception:
            pass
