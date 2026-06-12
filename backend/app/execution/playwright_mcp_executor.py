"""
Playwright MCP Executor — AI-native browser test executor.

Replaces the Selenium PlanRunner with an agentic loop where the AI drives
the browser in real-time via tool calls — identical interface to @playwright/mcp.

Flow:
  scenario + env + credentials
      ↓
  Playwright browser (Chromium)
      ↓
  AI sees: accessibility snapshot (aria tree) + URL + page title
      ↓
  AI calls: browser_navigate / browser_click / browser_type / … / test_pass|fail
      ↓
  Each tool call → executed → result fed back → next AI turn
      ↓
  ExecutionStep recorded per tool call, ExecutionReport at the end
"""
from __future__ import annotations
import asyncio
import base64
import json
import os
import time
import uuid as _uuid_mod
from datetime import datetime
from typing import Any

import openai
import structlog
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from playwright.async_api import Error as PWError, TimeoutError as PWTimeout
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    ExecutionRun, ExecutionStep, ExecutionLog, ExecutionPlan,
    Environment, Credential, Application, Scenario, ExecutionReport,
    ExecutionStatus, StepStatus, RiskLevel,
    ApplicationModule, ApplicationPage, AIMemoryChunk, MemoryKind,
)
from app.core.security import decrypt_credential
from app.realtime.manager import connection_manager
from app.intelligence.azure_rate_limiter import get_azure_limiter
from config import settings

log = structlog.get_logger()

MAX_ITERATIONS = 60          # Max plan steps per run
MAX_AI_CALLS_PER_STEP = 6   # Max AI tool calls per individual plan step
STEP_TIMEOUT_MS = 10_000     # Per-action timeout for Playwright
NAV_WAIT_MS = 2_000          # Fallback wait after navigation for SPAs (used if stability check fails)

# ─── Tool definitions (Anthropic format; converted to OpenAI when needed) ─────

PLAYWRIGHT_TOOLS: list[dict] = [
    {
        "name": "browser_snapshot",
        "description": (
            "Get the current accessibility tree of the page as structured text. "
            "Use this to understand page structure, find elements by role/name, "
            "and get element refs for targeting. Always call this after navigation "
            "or when the page content changes."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "browser_navigate",
        "description": "Navigate the browser to a URL.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Full URL to navigate to"},
            },
            "required": ["url"],
        },
    },
    {
        "name": "browser_click",
        "description": (
            "Click an element. Prefer using 'ref' from a recent browser_snapshot. "
            "Fall back to 'selector' (CSS/text) or 'text' (visible text match)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ref":      {"type": "string", "description": "Element ref from snapshot (e.g. e3)"},
                "selector": {"type": "string", "description": "CSS selector"},
                "text":     {"type": "string", "description": "Visible text to click"},
            },
        },
    },
    {
        "name": "browser_type",
        "description": "Clear an input field and type text into it.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text":     {"type": "string", "description": "Text to type"},
                "ref":      {"type": "string", "description": "Element ref from snapshot"},
                "selector": {"type": "string", "description": "CSS selector"},
                "append":   {"type": "boolean", "description": "Append instead of replacing (default false)"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "browser_select_option",
        "description": "Select an option from a <select> dropdown or mat-select.",
        "input_schema": {
            "type": "object",
            "properties": {
                "value":    {"type": "string", "description": "Option value or visible label to select"},
                "ref":      {"type": "string", "description": "Element ref from snapshot"},
                "selector": {"type": "string", "description": "CSS selector of the select element"},
            },
            "required": ["value"],
        },
    },
    {
        "name": "browser_hover",
        "description": "Hover over an element (e.g. to reveal a tooltip or submenu).",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref":      {"type": "string"},
                "selector": {"type": "string"},
                "text":     {"type": "string"},
            },
        },
    },
    {
        "name": "browser_press_key",
        "description": "Press a keyboard key (e.g. Enter, Tab, Escape, ArrowDown).",
        "input_schema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key name e.g. Enter, Tab, Escape, ArrowDown"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "browser_wait",
        "description": (
            "Wait for a condition: a number of milliseconds, or until a selector/text appears."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ms":       {"type": "integer", "description": "Milliseconds to wait"},
                "selector": {"type": "string",  "description": "Wait until this CSS selector is visible"},
                "text":     {"type": "string",  "description": "Wait until this text appears on page"},
            },
        },
    },
    {
        "name": "browser_assert_visible",
        "description": "Assert that an element is visible on the page. Use this to verify operations like 'verify added in table' instead of just relying on your vision.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text":     {"type": "string", "description": "Visible text to assert"},
                "ref":      {"type": "string", "description": "Element ref from snapshot (optional)"},
                "selector": {"type": "string", "description": "CSS selector (optional)"},
                "timeout":  {"type": "integer", "description": "Milliseconds to wait for visibility (default 5000)"},
            },
        },
    },
    {
        "name": "browser_assert_not_visible",
        "description": "Assert that an element or text is NOT visible on the page. Use this for 'verify deleted' operations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text":     {"type": "string", "description": "Text that should not be visible"},
                "selector": {"type": "string", "description": "CSS selector that should not be visible (optional)"},
                "timeout":  {"type": "integer", "description": "Milliseconds to wait for invisibility (default 5000)"},
            },
        },
    },
    {
        "name": "browser_assert_text",
        "description": (
            "Assert that an element contains specific text content. "
            "Use this to verify ACTUAL DATA VALUES after create/update operations "
            "(e.g. verify the record name in the list, verify a field value). "
            "Stronger than assert_visible — checks content, not just presence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "text":     {"type": "string", "description": "Text that should be present in the element"},
                "selector": {"type": "string", "description": "CSS selector of element to check (optional)"},
                "ref":      {"type": "string", "description": "Element ref from snapshot (optional)"},
                "exact":    {"type": "boolean", "description": "Match exactly (default false = substring match)"},
                "timeout":  {"type": "integer", "description": "Milliseconds to wait (default 5000)"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "browser_scroll",
        "description": "Scroll the page up or down.",
        "input_schema": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "enum": ["up", "down"], "description": "Scroll direction"},
                "amount":    {"type": "integer", "description": "Pixels to scroll (default 400)"},
            },
        },
    },
    {
        "name": "browser_screenshot",
        "description": (
            "Take a screenshot of the current browser state. "
            "Returns confirmation and saves evidence. Use browser_snapshot to understand UI structure."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "browser_evaluate",
        "description": "Execute JavaScript in the browser and return the result. Use sparingly.",
        "input_schema": {
            "type": "object",
            "properties": {
                "script": {"type": "string", "description": "JavaScript expression to evaluate"},
            },
            "required": ["script"],
        },
    },
    {
        "name": "test_pass",
        "description": (
            "Call this when the test scenario has been successfully completed. "
            "Provide a summary of what was verified."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "summary":              {"type": "string",  "description": "What was verified and confirmed"},
                "assertions_verified":  {"type": "array",   "items": {"type": "string"},
                                         "description": "List of specific assertions that passed"},
            },
            "required": ["summary"],
        },
    },
    {
        "name": "test_fail",
        "description": (
            "Call this when the test scenario cannot be completed due to a failure. "
            "Provide the reason and where it failed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason":          {"type": "string", "description": "Why the test failed"},
                "step_that_failed":{"type": "string", "description": "Which step or action failed"},
                "error_details":   {"type": "string", "description": "Technical error details"},
            },
            "required": ["reason"],
        },
    },
]

# Pre-build the OpenAI function-calling format (for Azure OpenAI)
_TOOLS_OPENAI = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in PLAYWRIGHT_TOOLS
]


# ─── Executor ─────────────────────────────────────────────────────────────────

class PlaywrightMCPExecutor:
    """
    AI-driven test executor. Same interface as ExecutionOrchestrator.execute_run().
    Uses Playwright (async) + AI tool-calling loop instead of Selenium + PlanRunner.
    """

    def __init__(self, db: AsyncSession, main_loop=None):
        self.db = db
        self.main_loop = main_loop
        self._ref_map: dict[str, dict] = {}      # ref_id → {role, name, value}
        self._screenshot_counter = 0

    # ─── Entry point ──────────────────────────────────────────────────────────

    async def execute_run(self, run_id: str) -> None:
        log.info("PlaywrightMCPExecutor starting", run_id=run_id)

        run      = await self._load_run(run_id)
        plan     = await self._load_plan(run.plan_id) if run else None
        env      = await self._load_environment(run.environment_id) if run else None
        scenario = await self._load_scenario(run.scenario_id) if run else None

        if not run or not env or not scenario:
            if run:
                await self._fail_run(run, "Missing environment or scenario")
            log.error("Run setup failed", run_id=run_id)
            return

        app_id     = scenario.application_id
        credential = await self._load_credential(run.credential_id, app_id)
        cred_data  = await self._decrypt_credential(credential)

        # Load exploration-built KG context (interaction guide, module URL, form fields)
        kg_context = await self._load_kg_context(scenario)
        if kg_context.get("module_url"):
            log.info("KG context loaded", run_id=run_id,
                     module=kg_context.get("module_name"),
                     guide_chars=len(kg_context.get("interaction_guide", "")),
                     form_fields=len(kg_context.get("form_fields", [])))

        run.status     = ExecutionStatus.RUNNING
        run.started_at = datetime.utcnow()
        await self.db.commit()
        await self._emit("run_started", run_id, {"scenario": scenario.title, "env": env.name})

        pw = None
        browser: Browser | None = None
        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(
                    headless=getattr(settings, "SELENIUM_HEADLESS", True),
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                        "--ignore-certificate-errors",
                    ],
                )
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 900},
                    ignore_https_errors=True,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                )
                page = await context.new_page()

                passed, steps_taken = await self._run_agentic_loop(
                    page, run, scenario, plan, env, cred_data, kg_context
                )

                await browser.close()

            final_status = ExecutionStatus.COMPLETED if passed else ExecutionStatus.FAILED
            run.status       = final_status
            run.completed_at = datetime.utcnow()
            run.total_steps  = len(steps_taken)
            run.passed_steps = sum(1 for s in steps_taken if s.get("passed"))
            run.failed_steps = sum(1 for s in steps_taken if not s.get("passed"))
            await self.db.commit()
            await self._emit(
                "run_completed", run_id,
                {"status": final_status.value, "steps": run.total_steps},
            )

            await self._build_report(run, scenario, steps_taken, passed)

        except asyncio.CancelledError:
            run.status       = ExecutionStatus.CANCELLED
            run.completed_at = datetime.utcnow()
            await self.db.commit()
            await self._emit("run_cancelled", run_id, {})
        except Exception as exc:
            log.exception("PlaywrightMCPExecutor crashed", run_id=run_id, error=str(exc))
            await self._fail_run(run, f"Executor error: {exc!s}")

    # ─── Plan-grounded execution loop ─────────────────────────────────────────

    async def _run_agentic_loop(
        self,
        page: Page,
        run: ExecutionRun,
        scenario: Scenario,
        plan: ExecutionPlan | None,
        env: Environment,
        cred_data: dict,
        kg_context: dict | None = None,
    ) -> tuple[bool, list[dict]]:
        """
        Plan-grounded execution loop.

        For each plan step we:
          1. Take a fresh browser snapshot (so the AI sees the live DOM)
          2. Send ONE focused AI message: "execute this specific step"
          3. Execute the returned tool calls (up to MAX_AI_CALLS_PER_STEP)
          4. Record every tool call as an ExecutionStep
          5. Honour on_fail policy: 'fail' stops the run, 'skip' continues

        This is fundamentally different from the old free-form loop where all steps
        were dumped into a system-prompt and the AI did whatever it liked.
        """
        steps_taken: list[dict] = []
        step_seq = 0
        passed = False
        ai_client = self._build_ai_client()
        # Unique 8-char prefix for test data in this run — prevents collisions on re-runs
        run_tag = run.id[:8].upper()
        system_prompt = self._build_system_prompt(scenario, plan, env, cred_data, kg_context or {}, run_tag=run_tag)

        # ── Navigate to app ──────────────────────────────────────────────────
        try:
            await page.goto(env.base_url, wait_until="domcontentloaded", timeout=60_000)
            await self._wait_for_stable(page)
        except Exception as exc:
            await self._fail_run(run, f"Cannot reach {env.base_url}: {exc}")
            return False, steps_taken

        # ── Login ────────────────────────────────────────────────────────────
        if cred_data.get("username"):
            login_result = await self._do_login(page, env, cred_data)
            step_seq += 1
            login_passed = not login_result.startswith("Error")
            step_record = ExecutionStep(
                id=str(_uuid_mod.uuid4()),
                run_id=run.id,
                sequence=step_seq,
                action_type="login",
                description=f"Login as {cred_data.get('username', '')}",
                plan_step={"action": "login", "result": login_result},
                status=StepStatus.PASSED if login_passed else StepStatus.FAILED,
                started_at=datetime.utcnow(),
                completed_at=datetime.utcnow(),
                duration_ms=0,
            )
            self.db.add(step_record)
            steps_taken.append({
                "seq": step_seq, "tool": "login",
                "args": {}, "result": login_result, "passed": login_passed,
                "duration_ms": 0, "screenshot_path": None,
            })
            await self._log_db(run, "INFO" if login_passed else "ERROR", "login",
                               f"[{step_seq}] {login_result}")
            await self._emit("step_completed", run.id, {
                "seq": step_seq, "tool": "login",
                "status": (StepStatus.PASSED if login_passed else StepStatus.FAILED).value,
                "result": login_result[:200],
            })
            await self.db.commit()
            if not login_passed:
                return False, steps_taken

        # ── Get plan steps ───────────────────────────────────────────────────
        plan_steps: list[dict] = []
        if plan and plan.plan_data:
            plan_steps = plan.plan_data.get("steps", [])

        if not plan_steps:
            await self._log_db(run, "WARNING", "executor", "No plan steps found — run complete")
            passed = True
            return passed, steps_taken

        total = len(plan_steps)
        await self._log_db(run, "INFO", "executor",
                           f"Executing {total} plan steps one by one via AI browser tools")

        all_critical_passed = True

        # ── Execute plan steps one by one ────────────────────────────────────
        for idx, plan_step in enumerate(plan_steps[:MAX_ITERATIONS]):
            # Check if the run was cancelled externally between steps
            await self.db.refresh(run)
            if run.status == ExecutionStatus.CANCELLED:
                raise asyncio.CancelledError("Run cancelled by user")

            action = (plan_step.get("action") or "").strip().lower()
            on_fail = plan_step.get("on_fail", "skip")
            is_critical = on_fail == "fail"
            phase = plan_step.get("phase", "")

            # ── Simple steps — execute directly, no AI needed ───────────────
            if action == "screenshot":
                try:
                    await self._save_screenshot(page, run.id, step_seq + 1)
                except Exception:
                    pass
                continue

            if action in ("wait_ms", "wait"):
                ms = int(plan_step.get("ms") or plan_step.get("value") or 1000)
                await page.wait_for_timeout(min(ms, 8000))
                continue

            if action == "wait_network":
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass
                continue

            if action == "navigate":
                nav_url = (plan_step.get("url") or plan_step.get("target") or "").strip()
                if nav_url:
                    step_seq += 1
                    t_start = time.monotonic()
                    try:
                        await page.goto(nav_url, wait_until="domcontentloaded", timeout=30_000)
                        await self._wait_for_stable(page)
                        result_text = f"Navigated to {nav_url}"
                        nav_status = StepStatus.PASSED
                    except Exception as exc:
                        result_text = f"Error: navigate to {nav_url} — {str(exc)[:120]}"
                        nav_status = StepStatus.FAILED
                    duration_ms = int((time.monotonic() - t_start) * 1000)
                    step_record = ExecutionStep(
                        id=str(_uuid_mod.uuid4()),
                        run_id=run.id, sequence=step_seq,
                        action_type="navigate",
                        description=plan_step.get("description", f"Navigate to {nav_url}"),
                        plan_step={"action": "navigate", "url": nav_url, "result": result_text},
                        status=nav_status,
                        started_at=datetime.utcnow(), completed_at=datetime.utcnow(),
                        duration_ms=duration_ms,
                    )
                    self.db.add(step_record)
                    steps_taken.append({
                        "seq": step_seq, "tool": "navigate", "args": {"url": nav_url},
                        "result": result_text, "passed": nav_status == StepStatus.PASSED,
                        "duration_ms": duration_ms, "screenshot_path": None,
                    })
                    await self._log_db(run, "INFO", "action",
                                       f"[{step_seq}] navigate: {result_text}")
                    await self._emit("step_completed", run.id, {
                        "seq": step_seq, "tool": "navigate",
                        "status": nav_status.value, "result": result_text[:200],
                    })
                    await self.db.commit()
                    if nav_status == StepStatus.FAILED and is_critical:
                        all_critical_passed = False
                        break
                continue

            # ── AI-driven steps ──────────────────────────────────────────────
            # Take a fresh snapshot of the current page
            try:
                snapshot = await self._do_snapshot(page)
            except Exception as exc:
                snapshot = f"Snapshot unavailable: {str(exc)[:100]}"

            # Build a focused single-step message for the AI
            step_msg = self._format_step_for_ai(idx + 1, total, plan_step, snapshot, page.url)

            await self._log_db(run, "INFO", "executor",
                               f"Step {idx+1}/{total} [{phase or action.upper()}]: {plan_step.get('description', action)[:80]}")

            # Call AI with a fresh, focused context for this single step
            ai_error: str | None = None
            tool_calls: list = []
            try:
                tool_calls, _text = await self._call_ai(ai_client, system_prompt, [
                    {"role": "user", "content": step_msg}
                ])
            except Exception as exc:
                ai_error = str(exc)[:200]
                await self._log_db(run, "ERROR", "ai",
                                   f"AI call failed for step {idx+1}: {ai_error}")

            if ai_error or not tool_calls:
                # Record this plan step as SKIPPED so it is visible in the UI
                step_seq += 1
                reason = f"AI error: {ai_error}" if ai_error else "AI returned no tool calls"
                skip_record = ExecutionStep(
                    id=str(_uuid_mod.uuid4()),
                    run_id=run.id,
                    sequence=step_seq,
                    action_type="skipped",
                    description=plan_step.get("description") or f"[skipped] {action}",
                    plan_step={"action": action, "target": plan_step.get("target", ""),
                               "result": reason, "plan_step_idx": idx + 1},
                    status=StepStatus.SKIPPED,
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                    duration_ms=0,
                )
                self.db.add(skip_record)
                steps_taken.append({
                    "seq": step_seq, "tool": "skipped", "args": {},
                    "result": reason, "passed": False,
                    "duration_ms": 0, "screenshot_path": None,
                })
                await self.db.commit()
                if ai_error and is_critical:
                    all_critical_passed = False
                    break
                continue

            # Execute tool calls returned for this step
            step_overall_passed = True
            for tc in tool_calls[:MAX_AI_CALLS_PER_STEP]:
                tool_name = tc["name"]
                tool_args = tc["arguments"]
                # Substitute {{RUN_ID}} placeholder in fill values for test data uniqueness
                if tool_name == "browser_type" and isinstance(tool_args.get("text"), str):
                    tool_args = dict(tool_args)
                    tool_args["text"] = tool_args["text"].replace("{{RUN_ID}}", run_tag)
                step_seq += 1

                t_start = time.monotonic()
                screenshot_path: str | None = None

                if tool_name == "test_pass":
                    result_text = f"PASS: {tool_args.get('summary', '')}"
                    passed = True
                    status = StepStatus.PASSED
                elif tool_name == "test_fail":
                    result_text = (
                        f"FAIL: {tool_args.get('reason', '')} — "
                        f"{tool_args.get('error_details', '')}"
                    )
                    step_overall_passed = False
                    status = StepStatus.FAILED
                else:
                    result_text = await self._execute_tool(page, tool_name, tool_args)
                    status = (
                        StepStatus.PASSED
                        if not result_text.startswith("Error")
                        and not result_text.startswith("Assertion failed")
                        else StepStatus.FAILED
                    )
                    if status == StepStatus.FAILED:
                        step_overall_passed = False

                # Always capture screenshot on failure — critical for debugging
                try:
                    if status == StepStatus.FAILED:
                        screenshot_path = await self._save_screenshot(page, run.id, step_seq)
                    elif tool_name in ("browser_screenshot", "test_pass", "test_fail"):
                        screenshot_path = await self._save_screenshot(page, run.id, step_seq)
                except Exception:
                    pass

                duration_ms = int((time.monotonic() - t_start) * 1000)
                step_desc = (
                    plan_step.get("description")
                    or f"{tool_name}: {json.dumps(tool_args)[:120]}"
                )
                step_record = ExecutionStep(
                    id=str(_uuid_mod.uuid4()),
                    run_id=run.id,
                    sequence=step_seq,
                    action_type=tool_name,
                    description=step_desc,
                    plan_step={
                        "tool": tool_name,
                        "arguments": tool_args,
                        "result": result_text[:500],
                        "plan_step_idx": idx + 1,
                        "plan_action": action,
                        "plan_target": plan_step.get("target", ""),
                        "plan_phase": phase,
                    },
                    status=status,
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                    duration_ms=duration_ms,
                    screenshot_path=screenshot_path,
                )
                self.db.add(step_record)
                steps_taken.append({
                    "seq": step_seq, "tool": tool_name, "args": tool_args,
                    "result": result_text, "passed": status == StepStatus.PASSED,
                    "duration_ms": duration_ms, "screenshot_path": screenshot_path,
                })
                await self._log_db(
                    run, "INFO" if status == StepStatus.PASSED else "ERROR", "action",
                    f"[{step_seq}] {tool_name}: {result_text[:150]}",
                    {"tool": tool_name, "args": tool_args, "duration_ms": duration_ms},
                )
                await self._emit("step_completed", run.id, {
                    "seq": step_seq, "tool": tool_name,
                    "status": status.value, "result": result_text[:200],
                })

            await self.db.commit()

            if not step_overall_passed and is_critical:
                all_critical_passed = False
                await self._log_db(run, "ERROR", "executor",
                                   f"Critical step {idx+1} failed — stopping run")
                break

        else:
            # for-loop finished without break — all steps attempted
            passed = all_critical_passed

        try:
            await ai_client.close()
        except Exception:
            pass

        return passed, steps_taken

    # ── Step formatter ─────────────────────────────────────────────────────────

    def _format_step_for_ai(
        self,
        step_num: int,
        total: int,
        plan_step: dict,
        snapshot: str,
        current_url: str,
    ) -> str:
        """Format one plan step + live snapshot into a focused AI message."""
        action = (plan_step.get("action") or "").upper()
        target = plan_step.get("target", "")
        value  = plan_step.get("value", "")
        desc   = plan_step.get("description", "")
        phase  = plan_step.get("phase", "")
        intent = plan_step.get("business_intent", "")
        checkpoint = plan_step.get("checkpoint", False)

        lines = [
            f"=== Step {step_num} of {total}" + (f"  [{phase}]" if phase else "") + " ===",
            f"Action: {action}",
        ]
        if target:
            lines.append(f'Target: "{target}"')
        if value:
            lines.append(f'Value: "{value}"')
        if desc:
            lines.append(f"What: {desc}")
        if intent:
            lines.append(f"Why: {intent}")
        if checkpoint:
            lines.append("CHECKPOINT: This step verifies a critical business outcome.")

        # Map plan action to the correct browser tool
        action_upper = action.upper()
        tool_hint = ""
        if action_upper in ("ASSERT_TEXT",):
            tool_hint = "→ Use browser_assert_text to verify the actual text content exists on the page."
        elif action_upper in ("ASSERT_VISIBLE",):
            tool_hint = "→ Use browser_assert_visible to confirm the element is present/visible."
        elif action_upper in ("ASSERT_NOT_TEXT", "ASSERT_NOT_VISIBLE"):
            tool_hint = "→ Use browser_assert_not_visible to confirm the text/element is gone."
        elif action_upper in ("FILL", "TYPE"):
            tool_hint = "→ Use browser_type with the ref of the matching input field."
        elif action_upper == "CLICK":
            tool_hint = "→ Use browser_click with the ref or visible text."
        elif action_upper == "SELECT":
            tool_hint = "→ Use browser_select_option."

        lines += [
            "",
            f"Current URL: {current_url}",
            "Current page (ARIA accessibility tree with element refs):",
            snapshot,
            "",
            "Instructions:",
            "- Look at the ARIA tree above to find the element that matches the Target.",
            "- Prefer using 'ref' from the ARIA tree for precise targeting.",
            f"- {tool_hint}" if tool_hint else "- Choose the most appropriate browser tool for this action.",
            "- ASSERT_TEXT steps: use browser_assert_text (verifies data VALUE, not just presence).",
            "- ASSERT_VISIBLE steps: use browser_assert_visible.",
            "- ASSERT_NOT_TEXT steps: use browser_assert_not_visible.",
            "- Make ONE tool call to execute this step.",
        ]
        return "\n".join(lines)

    # ─── Login ────────────────────────────────────────────────────────────────

    async def _do_login(self, page: Page, env: Environment, cred_data: dict) -> str:
        """
        Navigate to base URL, detect login form, fill credentials, submit.
        Handles any SPA/MPA: detects login form by password field presence.
        Returns a success or Error string.
        """
        username = cred_data.get("username", "")
        password = cred_data.get("password", "")
        if not username:
            return "Skipped login: no credentials configured"

        try:
            await page.goto(env.base_url, wait_until="commit", timeout=60_000)
        except Exception as exc:
            return f"Error: Could not reach {env.base_url} — {str(exc)[:100]}"

        # Quick 3-second check: are we already logged in?
        # If no password field found quickly AND URL isn't a login URL → already authenticated.
        _login_url_keywords = ("login", "signin", "sign-in", "auth", "sso", "saml")
        try:
            await page.wait_for_selector(
                'input[type="password"], input[name*="password" i]',
                timeout=3_000,
            )
            # Password field appeared quickly — we're on the login page, proceed normally
        except Exception:
            # No password field in 3 seconds
            current = page.url.lower()
            if not any(kw in current for kw in _login_url_keywords):
                return f"Login skipped: already authenticated — current URL: {page.url}"
            # URL looks like a login page but field hasn't appeared yet — wait longer
            try:
                await page.wait_for_selector(
                    'input[type="password"], input[type="text"], input[name*="user" i]',
                    timeout=30_000,
                )
            except Exception:
                pass

        # Detect login form
        has_form = False
        for sel in ('input[type="password"]', 'input[name*="password" i]',
                    'input[placeholder*="password" i]'):
            try:
                if await page.locator(sel).count() > 0:
                    has_form = True
                    break
            except Exception:
                pass

        if not has_form:
            return f"Login skipped: no login form at {page.url}"

        # Fill username — try multiple locator strategies
        username_filled = False
        for loc_fn, desc in [
            (page.get_by_label("username", exact=False),       "label:username"),
            (page.get_by_label("email", exact=False),          "label:email"),
            (page.get_by_placeholder("username", exact=False), "placeholder:username"),
            (page.get_by_placeholder("email", exact=False),    "placeholder:email"),
            (page.locator('input[name*="username" i]'),        "name:username"),
            (page.locator('input[name*="email" i]'),           "name:email"),
            (page.locator('input[type="email"]'),              "type:email"),
            (page.locator('input[type="text"]:visible').first, "first_text_input"),
        ]:
            try:
                cnt = await loc_fn.count() if hasattr(loc_fn, "count") else 1
                if cnt > 0:
                    target_loc = loc_fn.first if hasattr(loc_fn, "first") else loc_fn
                    await target_loc.clear(timeout=2_000)
                    await target_loc.fill(username, timeout=5_000)
                    username_filled = True
                    log.debug("Login: username filled", strategy=desc)
                    break
            except Exception:
                continue

        if not username_filled:
            return f"Error: Could not find username/email field at {page.url}"

        # Fill password
        password_filled = False
        for loc_fn, desc in [
            (page.locator('input[type="password"]:visible').first, "type:password"),
            (page.get_by_label("password", exact=False),           "label:password"),
            (page.get_by_placeholder("password", exact=False),     "placeholder:password"),
        ]:
            try:
                cnt = await loc_fn.count() if hasattr(loc_fn, "count") else 1
                if cnt > 0:
                    target_loc = loc_fn.first if hasattr(loc_fn, "first") else loc_fn
                    await target_loc.fill(password, timeout=5_000)
                    password_filled = True
                    break
            except Exception:
                continue

        if not password_filled:
            return f"Error: Could not find password field at {page.url}"

        # Submit — combined CSS covers all button label variants at once
        url_before = page.url
        submit_clicked = False
        _submit_combined = page.locator(
            'button[type="submit"], input[type="submit"], '
            'button:has-text("Sign In"), button:has-text("Sign in"), '
            'button:has-text("Log In"), button:has-text("Log in"), '
            'button:has-text("Login"), button:has-text("login"), '
            'button:has-text("Submit"), button:has-text("Continue"), '
            'button:has-text("Next"), [role="button"]:has-text("Sign In"), '
            '[role="button"]:has-text("Log In"), [role="button"]:has-text("Login")'
        ).first
        try:
            if await _submit_combined.count() > 0:
                await _submit_combined.click(timeout=5_000)
                submit_clicked = True
        except Exception:
            pass

        if not submit_clicked:
            try:
                await page.keyboard.press("Enter")
                submit_clicked = True
            except Exception:
                return "Error: Could not find or click login submit button"

        try:
            await self._wait_for_stable(page, timeout_ms=15_000)
        except Exception:
            pass

        current_url = page.url
        if current_url != url_before:
            return f"Login successful — redirected to {current_url}"

        # Check for visible error elements (not full page HTML — avoids JS bundle false-positives)
        error_sel = (
            '[class*="error" i]:visible, [class*="alert" i]:visible, '
            '[role="alert"]:visible, [class*="invalid" i]:visible'
        )
        try:
            err_count = await page.locator(error_sel).count()
            if err_count > 0:
                err_text = await page.locator(error_sel).first.text_content() or ""
                return f"Error: Login failed — {err_text.strip()[:120] or 'error shown on page'}"
        except Exception:
            pass

        if "login" not in current_url.lower() and "signin" not in current_url.lower():
            return f"Login successful — current URL: {current_url}"

        return f"Login submitted — current URL: {current_url}"

    # ─── AI client setup ──────────────────────────────────────────────────────

    def _build_ai_client(self):
        """Return an openai.AsyncAzureOpenAI (or AsyncOpenAI) client."""
        if settings.AI_PROVIDER == "azure_openai":
            return openai.AsyncAzureOpenAI(
                api_key=settings.AZURE_OPENAI_API_KEY,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_version=getattr(settings, "AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
                max_retries=0,
            )
        return openai.AsyncOpenAI(api_key=settings.OPENAI_API_KEY, max_retries=0)

    async def _call_ai(
        self,
        client: openai.AsyncAzureOpenAI | openai.AsyncOpenAI,
        system: str,
        messages: list[dict],
    ) -> tuple[list[dict], str]:
        """
        Call the AI with tool support.
        Returns (tool_calls: [{id, name, arguments}], text: str).
        Handles 429 with exponential backoff.
        """
        deployment = (
            settings.AZURE_OPENAI_DEPLOYMENT
            if settings.AI_PROVIDER == "azure_openai"
            else getattr(settings, "PRIMARY_MODEL", "gpt-4o")
        )

        full_messages = [{"role": "system", "content": system}] + messages

        limiter = get_azure_limiter() if settings.AI_PROVIDER == "azure_openai" else None
        last_exc: Exception | None = None
        for attempt in range(5):
            if limiter:
                await limiter.wait()
            try:
                response = await client.chat.completions.create(
                    model=deployment,
                    messages=full_messages,
                    tools=_TOOLS_OPENAI,
                    tool_choice="auto",
                    max_completion_tokens=4096,
                )
                break
            except openai.RateLimitError as exc:
                last_exc = exc
                retry_after = 0
                try:
                    hdrs = getattr(getattr(exc, "response", None), "headers", {}) or {}
                    retry_after = int(hdrs.get("retry-after") or hdrs.get("Retry-After") or 0)
                except Exception:
                    pass
                wait = retry_after if retry_after > 0 else min(15 * (2 ** attempt), 90)
                if limiter:
                    limiter.record_retry_after(wait)
                log.warning("AI 429 rate limit in MCP executor", attempt=attempt + 1, wait=wait)
                await asyncio.sleep(wait)
            except Exception as exc:
                raise
        else:
            raise last_exc  # type: ignore[misc]

        choice = response.choices[0]
        text = choice.message.content or ""

        tool_calls: list[dict] = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append({"id": tc.id, "name": tc.function.name, "arguments": args})

        return tool_calls, text

    # ─── KG context loading ───────────────────────────────────────────────────

    async def _load_kg_context(self, scenario: Scenario) -> dict:
        """
        Load exploration-built knowledge for this scenario's module.
        Returns a dict with: module_name, module_url, interaction_guide, form_fields.
        All fields are optional — callers must handle empty values gracefully.
        """
        ctx: dict = {
            "module_name": "",
            "module_url": "",
            "interaction_guide": "",
            "form_fields": [],
        }
        if not scenario.module_id:
            return ctx

        try:
            # Module info
            mod_result = await self.db.execute(
                select(ApplicationModule).where(ApplicationModule.id == scenario.module_id)
            )
            module = mod_result.scalar_one_or_none()
            if module:
                ctx["module_name"] = module.name or ""
                ctx["module_url"]  = module.url_pattern or ""

            # Interaction guide (exploration-built CSS selectors + workflow patterns)
            guides_result = await self.db.execute(
                select(AIMemoryChunk).where(
                    AIMemoryChunk.application_id == scenario.application_id,
                    AIMemoryChunk.kind == MemoryKind.WORKFLOW,
                )
            )
            guide_texts = [
                chunk.content
                for chunk in guides_result.scalars().all()
                if (chunk.extra or {}).get("guide_type") == "interaction"
                and (chunk.extra or {}).get("module_id") == scenario.module_id
            ]
            if guide_texts:
                ctx["interaction_guide"] = "\n\n---\n\n".join(guide_texts)

            # Form fields from explored pages
            pages_result = await self.db.execute(
                select(ApplicationPage).where(
                    ApplicationPage.module_id == scenario.module_id
                ).limit(5)
            )
            fields: list[dict] = []
            seen_labels: set[str] = set()
            for page in pages_result.scalars().all():
                for form in (page.forms or [])[:3]:
                    for f in (form.get("fields") or [])[:20]:
                        label = (f.get("label") or "").strip()
                        if label and label not in seen_labels:
                            seen_labels.add(label)
                            fields.append({
                                "label":    label,
                                "type":     f.get("type", "text"),
                                "required": bool(f.get("required", False)),
                                "options":  (f.get("options") or [])[:5],
                            })
            ctx["form_fields"] = fields[:30]

        except Exception as exc:
            log.warning("Failed to load KG context for Playwright executor", error=str(exc)[:200])

        return ctx

    # ─── System prompt ────────────────────────────────────────────────────────

    def _build_system_prompt(
        self,
        scenario: Scenario,
        plan: ExecutionPlan | None,
        env: Environment,
        cred_data: dict,
        kg_context: dict | None = None,
        run_tag: str = "",
    ) -> str:
        """
        Concise system prompt — role + credentials + known UI context + rules.
        Plan steps are NOT included here; they are fed one at a time in each user message.
        """
        kg = kg_context or {}
        username = cred_data.get("username", "")
        password = cred_data.get("password", "")
        module_name = kg.get("module_name", "")
        module_url  = kg.get("module_url", "")

        # Form fields from exploration (exact labels)
        fields_text = ""
        form_fields = kg.get("form_fields", [])
        if form_fields:
            lines = ["Known form fields (exact labels from live exploration — use these when filling forms):"]
            for f in form_fields[:25]:
                req  = " [required]" if f.get("required") else ""
                opts = f" options=[{', '.join(str(o) for o in f['options'][:4])}]" if f.get("options") else ""
                lines.append(f'  - "{f["label"]}" ({f.get("type","text")}{req}{opts})')
            fields_text = "\n".join(lines)

        # Interaction guide from exploration (exact button labels, workflow patterns)
        guide_text = ""
        guide = kg.get("interaction_guide", "")
        if guide:
            cap = guide[:3000] + ("\n...(truncated)" if len(guide) > 3000 else "")
            guide_text = f"Exploration guide (exact UI knowledge from live browser exploration):\n{cap}"

        module_text = ""
        if module_name or module_url:
            module_text = f"Module: {module_name}  URL: {module_url}"

        run_tag_text = ""
        if run_tag:
            run_tag_text = (
                f"\nTest Data Run Tag: {run_tag}  "
                f"← Append this to any unique name you create (e.g. 'Product-{run_tag}'). "
                f"Use {{{{RUN_ID}}}} in fill values and it will be substituted with this tag automatically."
            )

        return f"""You are an AI QA engineer executing test steps in a live browser.

Scenario: {scenario.title}
App URL: {env.base_url}   Username: {username}   Password: {password}
{module_text}{run_tag_text}

{fields_text}

{guide_text}

## How you work
You will receive ONE plan step at a time, together with the current page ARIA tree.
Your job: look at the ARIA tree, find the matching element, and call the RIGHT browser tool.
You are given a FRESH snapshot with every step — you do NOT need to call browser_snapshot first.

## Rules
1. Use element refs from the ARIA tree in the user message for precise targeting.
2. For CLICK: use browser_click with ref or text matching the Target.
3. For FILL/TYPE: use browser_type. Append the Run Tag to any test record name for uniqueness.
4. For SELECT: use browser_select_option.
5. For ASSERT_VISIBLE: use browser_assert_visible (checks element is present on page).
6. For ASSERT DATA VALUES (verify a specific value exists): use browser_assert_text — this checks actual content, not just visibility.
7. For ASSERT_NOT_TEXT / assert_not_visible: use browser_assert_not_visible.
8. For mat-select/custom dropdowns: browser_click to open, browser_wait 500ms, browser_click option.
9. After form submit: browser_wait for success indicator before the next assertion step.
10. Make ONE tool call per step — the next step will handle verification.
11. Only call test_fail if the current step is completely impossible to execute.
12. VERIFY BUSINESS OUTCOMES: After create/update/delete, navigate to the list view and use browser_assert_text to confirm the record name appears/disappears — a success toast alone is not sufficient proof.
"""

    # ─── Tool implementations ─────────────────────────────────────────────────

    async def _execute_tool(self, page: Page, name: str, args: dict) -> str:
        """Dispatch tool call to the appropriate browser action."""
        try:
            if name == "browser_snapshot":
                return await self._do_snapshot(page)
            elif name == "browser_navigate":
                return await self._do_navigate(page, args.get("url", ""))
            elif name == "browser_click":
                return await self._do_click(page, args)
            elif name == "browser_type":
                return await self._do_type(page, args)
            elif name == "browser_select_option":
                return await self._do_select(page, args)
            elif name == "browser_hover":
                return await self._do_hover(page, args)
            elif name == "browser_press_key":
                return await self._do_press_key(page, args.get("key", ""))
            elif name == "browser_wait":
                return await self._do_wait(page, args)
            elif name == "browser_assert_visible":
                return await self._do_assert_visible(page, args)
            elif name == "browser_assert_not_visible":
                return await self._do_assert_not_visible(page, args)
            elif name == "browser_assert_text":
                return await self._do_assert_text(page, args)
            elif name == "browser_scroll":
                return await self._do_scroll(page, args)
            elif name == "browser_screenshot":
                return f"Screenshot taken. URL: {page.url}"
            elif name == "browser_evaluate":
                return await self._do_evaluate(page, args.get("script", ""))
            else:
                return f"Error: Unknown tool '{name}'"
        except PWTimeout as exc:
            return f"Error: Timeout — {exc!s}"
        except PWError as exc:
            return f"Error: {exc!s}"
        except Exception as exc:
            return f"Error: {exc!s}"

    async def _do_snapshot(self, page: Page) -> str:
        """
        Return an interactive-elements-only ARIA tree with element refs.

        Filters to keep only actionable nodes (buttons, inputs, links, selects, tabs, etc.)
        and context-providing nodes (headings, alerts, table cells, dialog titles).
        This produces a much denser, more useful snapshot than the raw tree —
        especially for complex enterprise UIs where the full tree can be 15,000+ chars.
        Cap at 8000 chars (≈ 2000 tokens) instead of 3000.
        """
        try:
            url   = page.url
            title = await page.title()

            snapshot = await page.accessibility.snapshot(interesting_only=True)
            self._ref_map = {}
            counter = [0]

            # Roles that are always included and get a ref (actionable/interactive)
            INTERACTIVE_ROLES = {
                "button", "link", "textbox", "combobox", "listbox", "checkbox",
                "radio", "switch", "menuitem", "tab", "spinbutton", "searchbox",
                "menuitemcheckbox", "menuitemradio", "option", "treeitem",
                "slider", "scrollbar", "gridcell",
            }
            # Roles included only when they have a name (provide context)
            CONTEXT_ROLES = {
                "heading", "alert", "alertdialog", "dialog", "status", "log",
                "columnheader", "rowheader", "cell",
            }
            # Roles always skipped (structural noise)
            SKIP_ROLES = {
                "none", "generic", "group", "region", "main", "navigation",
                "complementary", "contentinfo", "banner", "document", "application",
                "list", "listitem", "presentation", "separator", "table", "grid",
                "row", "rowgroup", "toolbar",
            }

            def _fmt(node: dict, indent: int = 0) -> list[str]:
                if not node:
                    return []
                role  = node.get("role", "")
                name  = node.get("name", "")
                value = node.get("value", "")
                desc  = node.get("description", "")

                lines: list[str] = []
                include = (
                    role in INTERACTIVE_ROLES
                    or (role in CONTEXT_ROLES and name)
                )

                if role in SKIP_ROLES:
                    for child in node.get("children") or []:
                        lines.extend(_fmt(child, indent))
                    return lines

                if include:
                    counter[0] += 1
                    ref = f"e{counter[0]}"
                    self._ref_map[ref] = {"role": role, "name": name, "value": value}
                    parts = [f"[{role}]"]
                    if name:
                        parts.append(f'"{name}"')
                    if value and value != name:
                        parts.append(f'value="{value}"')
                    if desc and desc != name:
                        parts.append(f'desc="{desc}"')
                    parts.append(f"(ref={ref})")
                    lines.append("  " * indent + " ".join(parts))
                    for child in node.get("children") or []:
                        lines.extend(_fmt(child, indent + 1))
                else:
                    for child in node.get("children") or []:
                        lines.extend(_fmt(child, indent))
                return lines

            node_lines: list[str] = []
            if snapshot:
                node_lines = _fmt(snapshot)

            output = [f"URL: {url}", f"Title: {title}", ""]
            if node_lines:
                output.extend(node_lines)
            else:
                output.append("(No interactive elements found — page may still be loading)")
            result = "\n".join(output)
            # 8000 chars ≈ 2000 tokens — adequate for complex enterprise UIs
            if len(result) > 8000:
                result = result[:8000] + "\n... (more elements below — use browser_scroll to reveal them)"
            return result
        except Exception as exc:
            return f"Snapshot error: {exc}. URL: {page.url}"

    async def _wait_for_stable(self, page: Page, timeout_ms: int = 5000) -> None:
        """
        Wait for the page to reach a stable state after navigation or interaction.
        Replaces hard sleeps with an intelligent wait:
          1. domcontentloaded — basic DOM is ready
          2. networkidle — no pending XHR/fetch for 500ms (with short timeout so we don't block)
          3. Fall back to a short fixed wait if networkidle is too slow (e.g. long-polling apps)
        """
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
        except Exception:
            pass
        try:
            await page.wait_for_load_state("networkidle", timeout=2000)
        except Exception:
            # networkidle can hang on apps with continuous polling — use short fixed wait
            await page.wait_for_timeout(800)

    async def _do_navigate(self, page: Page, url: str) -> str:
        if not url:
            return "Error: No URL provided"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await self._wait_for_stable(page)
            return f"Navigated to {page.url}"
        except PWTimeout:
            return f"Navigation timeout — page may still be loading. Current URL: {page.url}"

    async def _do_click(self, page: Page, args: dict) -> str:
        ref      = args.get("ref")
        selector = args.get("selector")
        text     = args.get("text")

        errors: list[str] = []

        # Strategy 1: ref from latest snapshot
        if ref and ref in self._ref_map:
            node = self._ref_map[ref]
            role = node.get("role", "")
            name = node.get("name", "")
            try:
                if name and role:
                    await page.get_by_role(role, name=name).first.click(timeout=STEP_TIMEOUT_MS)
                    return f"Clicked [{role}] '{name}' (via ref {ref})"
                elif name:
                    await page.get_by_text(name, exact=True).first.click(timeout=STEP_TIMEOUT_MS)
                    return f"Clicked '{name}' (via ref {ref})"
            except Exception as e:
                errors.append(f"ref strategy failed: {e}")

        # Strategy 2: CSS selector
        if selector:
            try:
                await page.click(selector, timeout=STEP_TIMEOUT_MS)
                return f"Clicked '{selector}'"
            except Exception as e:
                errors.append(f"selector failed: {e}")

        # Strategy 3: visible text
        if text:
            try:
                await page.get_by_text(text, exact=False).first.click(timeout=STEP_TIMEOUT_MS)
                return f"Clicked text '{text}'"
            except Exception as e:
                errors.append(f"text strategy failed: {e}")

        return f"Error: Could not click element. Attempts: {'; '.join(errors)}"

    async def _do_type(self, page: Page, args: dict) -> str:
        text     = args.get("text", "")
        ref      = args.get("ref")
        selector = args.get("selector")
        append   = args.get("append", False)

        errors: list[str] = []

        async def _fill(locator):
            if not append:
                await locator.clear()
            await locator.fill(text)

        # Strategy 1: ref
        if ref and ref in self._ref_map:
            node = self._ref_map[ref]
            role = node.get("role", "")
            name = node.get("name", "")
            try:
                loc = page.get_by_role(role, name=name).first if (name and role) else None
                if loc:
                    await _fill(loc)
                    return f"Typed into [{role}] '{name}' (ref={ref})"
            except Exception as e:
                errors.append(f"ref: {e}")

        # Strategy 2: label / placeholder / CSS
        if selector:
            try:
                loc = page.locator(selector).first
                await _fill(loc)
                return f"Typed into '{selector}'"
            except Exception as e:
                errors.append(f"selector: {e}")

        # Strategy 3: any visible text input
        try:
            loc = page.locator("input:visible, textarea:visible").first
            await _fill(loc)
            return f"Typed into first visible input"
        except Exception as e:
            errors.append(f"generic input: {e}")

        return f"Error: Could not type. Attempts: {'; '.join(errors)}"

    async def _do_select(self, page: Page, args: dict) -> str:
        value    = args.get("value", "")
        ref      = args.get("ref")
        selector = args.get("selector")

        async def _select_on(loc):
            # Try native select first, then mat-select / custom dropdown
            try:
                await loc.select_option(label=value, timeout=3000)
                return f"Selected '{value}'"
            except Exception:
                pass
            try:
                await loc.select_option(value=value, timeout=3000)
                return f"Selected '{value}'"
            except Exception:
                pass
            # mat-select / custom dropdown: click to open, then pick option
            await loc.click(timeout=3000)
            await page.wait_for_timeout(500)
            try:
                await page.get_by_text(value, exact=False).first.click(timeout=3000)
                return f"Selected '{value}' from custom dropdown"
            except Exception as e:
                return f"Error: Could not select '{value}': {e}"

        if ref and ref in self._ref_map:
            node = self._ref_map[ref]
            role = node.get("role", "")
            name = node.get("name", "")
            try:
                loc = page.get_by_role(role, name=name).first
                return await _select_on(loc)
            except Exception as e:
                pass  # fall through

        if selector:
            return await _select_on(page.locator(selector).first)

        return f"Error: No selector or ref provided for select_option"

    async def _do_hover(self, page: Page, args: dict) -> str:
        ref      = args.get("ref")
        selector = args.get("selector")
        text     = args.get("text")

        if ref and ref in self._ref_map:
            node = self._ref_map[ref]
            role = node.get("role", "")
            name = node.get("name", "")
            if name:
                await page.get_by_role(role, name=name).first.hover(timeout=STEP_TIMEOUT_MS)
                return f"Hovered over '{name}'"

        if selector:
            await page.hover(selector, timeout=STEP_TIMEOUT_MS)
            return f"Hovered over '{selector}'"

        if text:
            await page.get_by_text(text, exact=False).first.hover(timeout=STEP_TIMEOUT_MS)
            return f"Hovered over '{text}'"

        return "Error: No selector/ref/text for hover"

    async def _do_press_key(self, page: Page, key: str) -> str:
        if not key:
            return "Error: No key specified"
        await page.keyboard.press(key)
        return f"Pressed '{key}'"

    async def _do_wait(self, page: Page, args: dict) -> str:
        ms       = args.get("ms")
        selector = args.get("selector")
        text     = args.get("text")

        if ms:
            await page.wait_for_timeout(int(ms))
            return f"Waited {ms}ms"

        if selector:
            await page.wait_for_selector(selector, timeout=15_000)
            return f"Selector '{selector}' appeared"

        if text:
            await page.get_by_text(text, exact=False).wait_for(timeout=15_000)
            return f"Text '{text}' appeared"

        return "Error: Specify ms, selector, or text for browser_wait"

    async def _do_assert_visible(self, page: Page, args: dict) -> str:
        text     = args.get("text")
        ref      = args.get("ref")
        selector = args.get("selector")
        timeout  = args.get("timeout", 5000)

        if ref and ref in self._ref_map:
            node = self._ref_map[ref]
            role = node.get("role", "")
            name = node.get("name", "")
            try:
                await page.get_by_role(role, name=name).first.wait_for(state="visible", timeout=timeout)
                return f"Assertion passed: Element with ref '{ref}' (role='{role}', name='{name}') is visible."
            except Exception as e:
                return f"Assertion failed: Element with ref '{ref}' is not visible. Error: {e}"

        if selector:
            try:
                await page.wait_for_selector(selector, state="visible", timeout=timeout)
                return f"Assertion passed: Selector '{selector}' is visible."
            except Exception as e:
                return f"Assertion failed: Selector '{selector}' is not visible. Error: {e}"

        if text:
            try:
                await page.get_by_text(text, exact=False).first.wait_for(state="visible", timeout=timeout)
                return f"Assertion passed: Text '{text}' is visible."
            except Exception as e:
                return f"Assertion failed: Text '{text}' is not visible. Error: {e}"

        return "Error: Specify text, ref, or selector for browser_assert_visible"

    async def _do_assert_not_visible(self, page: Page, args: dict) -> str:
        text     = args.get("text")
        selector = args.get("selector")
        timeout  = args.get("timeout", 5000)

        if selector:
            try:
                await page.wait_for_selector(selector, state="hidden", timeout=timeout)
                return f"Assertion passed: Selector '{selector}' is NOT visible."
            except Exception as e:
                return f"Assertion failed: Selector '{selector}' is still visible. Error: {e}"

        if text:
            try:
                # We wait for the element to be hidden
                await page.get_by_text(text, exact=False).first.wait_for(state="hidden", timeout=timeout)
                return f"Assertion passed: Text '{text}' is NOT visible."
            except Exception as e:
                return f"Assertion failed: Text '{text}' is still visible. Error: {e}"

        return "Error: Specify text or selector for browser_assert_not_visible"
    async def _do_assert_text(self, page: Page, args: dict) -> str:
        """
        Assert that an element contains specific text content.
        Stronger than assert_visible — verifies actual data values, not just presence.
        """
        text     = args.get("text", "")
        ref      = args.get("ref")
        selector = args.get("selector")
        exact    = args.get("exact", False)
        timeout  = args.get("timeout", 5000)

        if not text:
            return "Error: No text specified for browser_assert_text"

        # Strategy 1: check specific element by selector
        if selector:
            try:
                loc = page.locator(selector).first
                await loc.wait_for(state="visible", timeout=timeout)
                content = (await loc.text_content() or "").strip()
                if (exact and text == content) or (not exact and text.lower() in content.lower()):
                    return f"Assertion passed: Element '{selector}' contains '{text}'"
                return f"Assertion failed: Element '{selector}' text is '{content[:120]}', expected to contain '{text}'"
            except Exception as e:
                return f"Assertion failed: Could not check element '{selector}' — {str(e)[:120]}"

        # Strategy 2: check element by ref
        if ref and ref in self._ref_map:
            node = self._ref_map[ref]
            role = node.get("role", "")
            name = node.get("name", "")
            try:
                loc = page.get_by_role(role, name=name).first if (role and name) else None
                if loc:
                    content = (await loc.text_content() or "").strip()
                    if (exact and text == content) or (not exact and text.lower() in content.lower()):
                        return f"Assertion passed: Element (ref={ref}) contains '{text}'"
                    return f"Assertion failed: Element (ref={ref}) text is '{content[:120]}', expected to contain '{text}'"
            except Exception:
                pass

        # Strategy 3: page-wide text search (most forgiving)
        try:
            # Use Playwright's built-in locator which handles dynamic content
            loc = page.get_by_text(text, exact=exact)
            count = await loc.count()
            if count > 0:
                return f"Assertion passed: Text '{text}' found on page ({count} occurrence(s))"
            # Final fallback — check page source text content
            body_text = await page.evaluate("document.body.innerText")
            if text.lower() in (body_text or "").lower():
                return f"Assertion passed: Text '{text}' found in page content"
            return f"Assertion failed: Text '{text}' NOT found anywhere on page"
        except Exception as e:
            return f"Assertion failed: browser_assert_text error — {str(e)[:120]}"

    async def _do_scroll(self, page: Page, args: dict) -> str:
        direction = args.get("direction", "down")
        amount    = int(args.get("amount", 400))
        dy = amount if direction == "down" else -amount
        await page.evaluate(f"window.scrollBy(0, {dy})")
        return f"Scrolled {direction} {amount}px"

    async def _do_evaluate(self, page: Page, script: str) -> str:
        result = await page.evaluate(script)
        return str(result)[:500]

    # ─── Screenshots ──────────────────────────────────────────────────────────

    async def _save_screenshot(self, page: Page, run_id: str, seq: int) -> str:
        os.makedirs(settings.SCREENSHOTS_DIR, exist_ok=True)
        path = os.path.join(settings.SCREENSHOTS_DIR, f"mcp_{run_id}_{seq:03d}.png")
        await page.screenshot(path=path, full_page=False)
        return path

    # ─── DB helpers ───────────────────────────────────────────────────────────

    async def _load_run(self, run_id: str) -> ExecutionRun | None:
        result = await self.db.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))
        return result.scalar_one_or_none()

    async def _load_plan(self, plan_id: str) -> ExecutionPlan | None:
        result = await self.db.execute(select(ExecutionPlan).where(ExecutionPlan.id == plan_id))
        return result.scalar_one_or_none()

    async def _load_environment(self, env_id: str) -> Environment | None:
        result = await self.db.execute(select(Environment).where(Environment.id == env_id))
        return result.scalar_one_or_none()

    async def _load_scenario(self, scenario_id: str) -> Scenario | None:
        result = await self.db.execute(select(Scenario).where(Scenario.id == scenario_id))
        return result.scalar_one_or_none()

    async def _load_credential(self, cred_id: str | None, app_id: str | None) -> Credential | None:
        if cred_id:
            result = await self.db.execute(
                select(Credential).where(Credential.id == cred_id)
            )
            return result.scalar_one_or_none()
        if app_id:
            result = await self.db.execute(
                select(Credential).where(Credential.application_id == app_id).limit(1)
            )
            return result.scalar_one_or_none()
        return None

    async def _decrypt_credential(self, credential: Credential | None) -> dict:
        if not credential:
            return {}
        try:
            password = decrypt_credential(credential.password_encrypted)
            return {"username": credential.username, "password": password}
        except Exception:
            return {"username": getattr(credential, "username", ""), "password": ""}

    async def _fail_run(self, run: ExecutionRun, msg: str) -> None:
        run.status        = ExecutionStatus.FAILED
        run.completed_at  = datetime.utcnow()
        run.error_message = msg
        await self.db.commit()
        await self._emit("run_failed", run.id, {"error": msg})

    async def _log_db(
        self, run: ExecutionRun, level: str, category: str, message: str, extra: dict | None = None
    ) -> None:
        entry = ExecutionLog(
            id=str(_uuid_mod.uuid4()),
            run_id=run.id,
            timestamp=datetime.utcnow(),
            level=level,
            category=category,
            message=message,
            extra=extra or {},
        )
        self.db.add(entry)

    async def _emit(self, event: str, run_id: str, data: dict) -> None:
        try:
            if self.main_loop:
                asyncio.run_coroutine_threadsafe(
                    connection_manager.broadcast(
                        {"type": event, "run_id": run_id, **data}
                    ),
                    self.main_loop,
                )
            else:
                await connection_manager.broadcast(
                    {"type": event, "run_id": run_id, **data}
                )
        except Exception:
            pass

    # ─── Report ───────────────────────────────────────────────────────────────

    async def _build_report(
        self,
        run: ExecutionRun,
        scenario: Scenario,
        steps: list[dict],
        passed: bool,
    ) -> None:
        try:
            total         = len(steps)
            passed_count  = sum(1 for s in steps if s.get("passed"))
            failed_count  = total - passed_count
            # Steps that carry business checkpoint semantics (tagged in plan)
            checkpoint_steps   = [s for s in steps if s.get("checkpoint")]
            checkpoint_passed  = sum(1 for s in checkpoint_steps if s.get("passed"))
            checkpoint_total   = len(checkpoint_steps)

            # ── Deterministic quality score (not AI-generated) ──────────────────
            # Formula: 60% step pass rate + 30% checkpoint pass rate − 10% failure penalty
            if total == 0:
                quality_score = 0.0
            else:
                step_score       = (passed_count / total) * 60.0
                checkpoint_score = (checkpoint_passed / max(checkpoint_total, 1)) * 30.0
                failure_penalty  = (failed_count / total) * 10.0
                quality_score    = round(max(0.0, min(100.0, step_score + checkpoint_score - failure_penalty)), 1)

            # ── Risk level derived from quality score ────────────────────────────
            if quality_score >= 90:
                risk = RiskLevel.LOW
            elif quality_score >= 70:
                risk = RiskLevel.MEDIUM
            elif quality_score >= 40:
                risk = RiskLevel.HIGH
            else:
                risk = RiskLevel.CRITICAL if hasattr(RiskLevel, "CRITICAL") else RiskLevel.HIGH

            # ── Run history trend (last 10 completed runs for same scenario) ────
            consecutive_failures = 0
            flakiness_score      = 0.0
            last_pass_at: str | None = None
            try:
                from sqlalchemy import desc as _sql_desc
                hist_result = await self.db.execute(
                    select(ExecutionRun)
                    .where(
                        ExecutionRun.scenario_id == run.scenario_id,
                        ExecutionRun.id != run.id,
                        ExecutionRun.status.in_([ExecutionStatus.COMPLETED, ExecutionStatus.FAILED]),
                    )
                    .order_by(_sql_desc(ExecutionRun.completed_at))
                    .limit(10)
                )
                history = hist_result.scalars().all()
                if history:
                    for h in history:
                        if h.status == ExecutionStatus.FAILED:
                            consecutive_failures += 1
                        else:
                            last_pass_at = h.completed_at.isoformat() if h.completed_at else None
                            break
                    pass_count_hist  = sum(1 for h in history if h.status == ExecutionStatus.COMPLETED)
                    flakiness_score  = round(1.0 - (pass_count_hist / len(history)), 2)
            except Exception as _trend_err:
                log.debug("Trend query failed", error=str(_trend_err)[:100])

            # ── Insights derived from execution data (factual, not AI narrative) ─
            insights: list[str] = []
            failed_steps_info = [s for s in steps if not s.get("passed")]
            if failed_count > 0:
                tools_failed = ", ".join(dict.fromkeys(s["tool"] for s in failed_steps_info[:5]))
                insights.append(f"{failed_count} step(s) failed — actions: {tools_failed}")
            if checkpoint_total > 0 and checkpoint_passed < checkpoint_total:
                insights.append(
                    f"BUSINESS OUTCOME ALERT: {checkpoint_total - checkpoint_passed} of {checkpoint_total} "
                    f"business checkpoint(s) not verified"
                )
            if consecutive_failures >= 3:
                insights.append(
                    f"STABILITY ALERT: Scenario has failed {consecutive_failures} consecutive runs"
                )
            if flakiness_score > 0.4:
                insights.append(
                    f"FLAKINESS DETECTED: Scenario passes only "
                    f"{round((1 - flakiness_score) * 100)}% of recent runs"
                )
            if any("timeout" in (s.get("result") or "").lower() for s in failed_steps_info):
                insights.append("Timeout errors detected — application may be loading slowly")
            if any("not found" in (s.get("result") or "").lower() for s in failed_steps_info):
                insights.append("Element-not-found errors — consider re-exploring to refresh selectors")

            # ── Recommendations (actionable, based on failure patterns) ──────────
            recommendations: list[str] = []
            if any("element" in (s.get("result") or "").lower() and "not found" in (s.get("result") or "").lower()
                   for s in failed_steps_info):
                recommendations.append(
                    "Re-explore the application to rebuild the knowledge graph with fresh selectors"
                )
            if any("timeout" in (s.get("result") or "").lower() for s in failed_steps_info):
                recommendations.append(
                    "Add explicit wait_ms steps after actions that trigger heavy data loading"
                )
            if any("assertion failed" in (s.get("result") or "").lower() for s in failed_steps_info):
                recommendations.append(
                    "Assertion failures indicate unexpected UI state — verify test data exists before running"
                )
            if consecutive_failures >= 3:
                recommendations.append(
                    f"Scenario has failed {consecutive_failures} times in a row — "
                    f"review if the application flow has changed since last successful run"
                    + (f" (last passed: {last_pass_at})" if last_pass_at else "")
                )
            if flakiness_score > 0.3:
                recommendations.append(
                    "Flaky scenario — add browser_wait steps after dynamic content loads "
                    "and ensure test data is unique per run using the {{RUN_ID}} placeholder"
                )

            timeline = [
                {
                    "seq":         s["seq"],
                    "tool":        s["tool"],
                    "result":      s["result"][:200],
                    "duration_ms": s["duration_ms"],
                    "passed":      s["passed"],
                    "screenshot":  s.get("screenshot_path"),
                }
                for s in steps
            ]
            summary = {
                "total_steps":           total,
                "passed_steps":          passed_count,
                "failed_steps":          failed_count,
                "checkpoint_steps":      checkpoint_total,
                "checkpoints_passed":    checkpoint_passed,
                "outcome":               "PASSED" if passed else "FAILED",
                "executor":              "playwright_mcp",
                "quality_formula":       "60%×step_pass + 30%×checkpoint_pass − 10%×failure_rate",
                "consecutive_failures":  consecutive_failures,
                "flakiness_score":       flakiness_score,
                "last_pass_at":          last_pass_at,
            }

            report = ExecutionReport(
                id=str(_uuid_mod.uuid4()),
                run_id=run.id,
                risk_level=risk,
                quality_score=quality_score,
                summary=summary,
                insights=insights,
                rca_analysis={
                    "consecutive_failures": consecutive_failures,
                    "flakiness_score":      flakiness_score,
                    "failed_steps": [
                        {"seq": s["seq"], "tool": s["tool"], "result": s["result"][:200]}
                        for s in failed_steps_info[:10]
                    ],
                    "checkpoint_coverage": {
                        "total":  checkpoint_total,
                        "passed": checkpoint_passed,
                        "rate":   round(checkpoint_passed / max(checkpoint_total, 1), 2),
                    },
                },
                recommendations=recommendations,
                timeline=timeline,
            )
            self.db.add(report)
            await self.db.commit()
            log.info(
                "Report built",
                run_id=run.id,
                quality_score=quality_score,
                risk=risk.value if hasattr(risk, "value") else str(risk),
                flakiness=flakiness_score,
                consecutive_failures=consecutive_failures,
            )
        except Exception as exc:
            log.warning("Report generation failed", run_id=run.id, error=str(exc))
