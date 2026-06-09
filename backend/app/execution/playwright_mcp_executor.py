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

MAX_ITERATIONS = 30          # Max AI turns per run
STEP_TIMEOUT_MS = 10_000     # Per-action timeout for Playwright
NAV_WAIT_MS = 2_000          # Extra wait after navigation for SPAs

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

    # ─── Agentic loop ─────────────────────────────────────────────────────────

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
        Main agentic loop. Returns (passed: bool, steps: list[dict]).
        Each iteration: AI response → tool calls → execute → feed results back.
        """
        system_prompt = self._build_system_prompt(scenario, plan, env, cred_data, kg_context or {})
        messages: list[dict] = [
            {
                "role": "user",
                "content": (
                    f"Start executing the test scenario: '{scenario.title}'\n\n"
                    "Begin by navigating to the application and taking a snapshot to "
                    "understand the current page state."
                ),
            }
        ]

        steps_taken: list[dict] = []
        step_seq = 0
        passed = False
        finished = False

        ai_client = self._build_ai_client()

        for iteration in range(MAX_ITERATIONS):
            if finished:
                break

            # Keep context window small — drop old middle messages but always
            # retain the first user message (the task) and the last 12 turns.
            if len(messages) > 25:
                messages = [messages[0]] + messages[-24:]

            # ── Call AI ──────────────────────────────────────────────────────
            try:
                tool_calls, text = await self._call_ai(ai_client, system_prompt, messages)
            except Exception as exc:
                log.error("AI call failed", run_id=run.id, iteration=iteration, error=str(exc))
                await self._log_db(run, "ERROR", "ai", f"AI call failed: {exc}")
                break

            # Build assistant message for history
            assistant_msg: dict[str, Any] = {"role": "assistant"}
            if text:
                assistant_msg["content"] = text
            if tool_calls:
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in tool_calls
                ]
            if not tool_calls and not text:
                log.warning("AI returned empty response", run_id=run.id)
                break
            messages.append(assistant_msg)

            if not tool_calls:
                # AI sent text but no tool call → unexpected, end loop
                log.info("AI finished without tool call", run_id=run.id, text=(text or "")[:200])
                break

            # ── Execute tool calls ────────────────────────────────────────────
            tool_results: list[dict] = []
            for tc in tool_calls:
                tool_name = tc["name"]
                tool_args = tc["arguments"]
                step_seq += 1

                t_start = time.monotonic()
                screenshot_path: str | None = None

                # Take screenshot before action (evidence)
                try:
                    screenshot_path = await self._save_screenshot(page, run.id, step_seq)
                except Exception:
                    pass

                # Execute
                if tool_name == "test_pass":
                    result_text = f"PASS: {tool_args.get('summary', '')}"
                    passed = True
                    finished = True
                    status = StepStatus.PASSED
                elif tool_name == "test_fail":
                    result_text = (
                        f"FAIL: {tool_args.get('reason', '')} | "
                        f"Step: {tool_args.get('step_that_failed', '')} | "
                        f"Details: {tool_args.get('error_details', '')}"
                    )
                    passed = False
                    finished = True
                    status = StepStatus.FAILED
                else:
                    result_text = await self._execute_tool(page, tool_name, tool_args)
                    status = StepStatus.PASSED if not result_text.startswith("Error") else StepStatus.FAILED

                duration_ms = int((time.monotonic() - t_start) * 1000)

                # Record step in DB
                step_record = ExecutionStep(
                    id=str(_uuid_mod.uuid4()),
                    run_id=run.id,
                    sequence=step_seq,
                    action_type=tool_name,
                    description=f"{tool_name}: {json.dumps(tool_args)[:200]}",
                    plan_step={
                        "tool": tool_name,
                        "arguments": tool_args,
                        "result": result_text[:500],
                    },
                    status=status,
                    started_at=datetime.utcnow(),
                    completed_at=datetime.utcnow(),
                    duration_ms=duration_ms,
                    screenshot_path=screenshot_path,
                )
                self.db.add(step_record)

                steps_taken.append({
                    "seq": step_seq,
                    "tool": tool_name,
                    "args": tool_args,
                    "result": result_text,
                    "passed": status == StepStatus.PASSED,
                    "duration_ms": duration_ms,
                    "screenshot_path": screenshot_path,
                })

                await self._log_db(
                    run, "INFO", "action",
                    f"[{step_seq}] {tool_name}: {result_text[:150]}",
                    {"tool": tool_name, "args": tool_args, "duration_ms": duration_ms},
                )
                await self._emit("step_completed", run.id, {
                    "seq": step_seq,
                    "tool": tool_name,
                    "status": status.value,
                    "result": result_text[:200],
                })

                # Truncate large tool results (e.g. snapshots) to keep message history small.
                # The AI already acted on the full result; future turns only need a summary.
                stored_result = result_text if len(result_text) <= 1200 else result_text[:1200] + "\n...(truncated)"
                tool_results.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": stored_result,
                })

                if finished:
                    break

            await self.db.commit()

            # Add tool results to conversation
            messages.extend(tool_results)

        if not finished:
            log.warning("Agentic loop hit max iterations", run_id=run.id, iterations=MAX_ITERATIONS)
            await self._log_db(run, "WARN", "executor",
                               f"Test did not complete within {MAX_ITERATIONS} iterations")
            passed = False

        try:
            await ai_client.close()
        except Exception:
            pass

        return passed, steps_taken

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
                    max_completion_tokens=800,
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
    ) -> str:
        kg = kg_context or {}
        username = cred_data.get("username", "")
        password = cred_data.get("password", "")

        # ── Module section ────────────────────────────────────────────────────
        module_section = ""
        module_url = kg.get("module_url", "")
        module_name = kg.get("module_name", "")
        if module_name or module_url:
            module_section = f"\n## Module Under Test\n"
            if module_name:
                module_section += f"Name: {module_name}\n"
            if module_url:
                module_section += f"URL: {module_url}\n"
                module_section += "After login, navigate directly to this URL. Do NOT navigate to the base URL first — go straight to the module.\n"

        # ── Form fields section ───────────────────────────────────────────────
        fields_section = ""
        form_fields = kg.get("form_fields", [])
        if form_fields:
            fields_section = "\n## Form Fields (exact labels from exploration)\n"
            fields_section += "When filling forms, use EXACTLY these field labels to locate inputs:\n"
            for f in form_fields:
                req = " (required)" if f.get("required") else ""
                opts = ""
                if f.get("options"):
                    opts = f" — options: {', '.join(str(o) for o in f['options'])}"
                fields_section += f"  - \"{f['label']}\" ({f.get('type', 'text')}{req}){opts}\n"

        # ── Interaction guide (exploration-built knowledge) ───────────────────
        guide_section = ""
        interaction_guide = kg.get("interaction_guide", "")
        if interaction_guide:
            # Cap at 4000 chars to avoid bloating the context window
            truncated = interaction_guide[:4000]
            if len(interaction_guide) > 4000:
                truncated += "\n... (guide truncated)"
            guide_section = f"\n## Exploration Guide (exact UI knowledge from prior exploration)\n"
            guide_section += "This section describes the exact buttons, selectors, and workflows discovered during live exploration.\n"
            guide_section += "Use these element labels to find elements via browser_snapshot ARIA names:\n"
            guide_section += truncated + "\n"

        # ── Plan steps section ────────────────────────────────────────────────
        plan_section = ""
        if plan and plan.plan_data:
            steps = plan.plan_data.get("steps", [])
            workflow_type = plan.plan_data.get("workflow_type", "")
            goal = plan.plan_data.get("goal", "")
            if steps:
                plan_section = "\n## AI-Generated Test Plan\n"
                if goal:
                    plan_section += f"Goal: {goal}\n"
                if workflow_type:
                    plan_section += f"Workflow type: {workflow_type}\n"
                plan_section += "Execute these steps in order. Each step shows: action | target element | value (if any) | why it matters.\n\n"
                current_phase = ""
                for i, s in enumerate(steps[:40], 1):
                    phase = s.get("phase", "")
                    action = s.get("action", "")
                    desc = s.get("description", "")
                    target = s.get("target", "")
                    value = s.get("value", "")
                    intent = s.get("business_intent", "")

                    if phase and phase != current_phase:
                        plan_section += f"\n[{phase}]\n"
                        current_phase = phase

                    line = f"  {i}. {action.upper()}"
                    if target:
                        line += f" → \"{target}\""
                    if value:
                        line += f" = \"{value}\""
                    if desc and desc != target:
                        line += f"  — {desc}"
                    if intent:
                        line += f"  ({intent})"
                    plan_section += line + "\n"

        return f"""You are an AI QA engineer executing a test scenario in a real browser.
You have access to browser control tools — use them to drive the browser step by step.

## Test Scenario
Title: {scenario.title}
Description: {scenario.description or "(no description)"}
{module_section}{fields_section}{guide_section}{plan_section}
## Environment
Application URL: {env.base_url}
Username: {username}
Password: {password}

## Browser Tools at Your Disposal
- browser_snapshot  → see the current page structure (ARIA tree with element refs) — call this after every navigation or UI change
- browser_navigate  → go to a URL
- browser_click     → click a button/link/element (prefer 'ref' from snapshot; fall back to 'text')
- browser_type      → clear + type into an input field (use 'ref' from snapshot or 'selector')
- browser_select_option → pick a dropdown value
- browser_hover     → hover over an element
- browser_press_key → keyboard shortcut (Enter, Tab, Escape, etc.)
- browser_wait      → pause or wait for an element/text to appear
- browser_assert_visible → assert that text or an element is visible — USE THIS to verify outcomes
- browser_assert_not_visible → assert that text or an element is NOT visible — USE THIS for delete verification
- browser_scroll    → scroll the page
- browser_screenshot → capture evidence screenshot
- browser_evaluate  → run JavaScript (use sparingly — prefer snapshot + click/type)
- test_pass(summary) → call when the scenario succeeds ✓
- test_fail(reason)  → call when the scenario cannot be completed ✗

## Execution Rules
1. Start by navigating to the module URL (above) and taking a browser_snapshot.
2. Log in if the page shows a login form — use the credentials above.
3. After login, navigate to the module URL again if you were redirected to a dashboard.
4. Follow the AI-Generated Test Plan steps in order.
5. After EVERY navigation or form submission, call browser_snapshot to re-orient.
6. Always prefer element refs from the LATEST snapshot for targeting.
7. When filling forms: locate each field by its label name in the ARIA tree, then type into it.
8. For Angular/React mat-select dropdowns: click to open, wait 500ms, then click the option text.
9. After form submission: wait 1-2s then browser_assert_visible to confirm success toast/message.
10. After delete: use browser_assert_not_visible to confirm the item is gone from the list.
11. NEVER call test_pass() without first asserting the expected outcome is visible.
12. If an action fails, try one alternative (e.g. text search instead of ref) before calling test_fail.
13. For Angular SPAs: after any navigation, wait 1-2 seconds before interacting with elements.
14. Use browser_evaluate sparingly — only for Angular value setter issues with mat-inputs.
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
        """Return the ARIA accessibility tree as structured text with element refs."""
        try:
            url   = page.url
            title = await page.title()

            snapshot = await page.accessibility.snapshot(interesting_only=True)
            self._ref_map = {}
            counter = [0]

            def _fmt(node: dict, indent: int = 0) -> list[str]:
                if not node:
                    return []
                role  = node.get("role", "")
                name  = node.get("name", "")
                value = node.get("value", "")
                desc  = node.get("description", "")

                # Skip structural-only nodes but still recurse into children
                skip_roles = {
                    "none", "generic", "group", "region", "main",
                    "navigation", "complementary", "contentinfo", "banner",
                    "document", "application", "list",
                }
                lines: list[str] = []
                if role not in skip_roles:
                    counter[0] += 1
                    ref = f"e{counter[0]}"
                    self._ref_map[ref] = {"role": role, "name": name, "value": value}

                    parts = [f"[{role}]"]
                    if name:
                        parts.append(f'"{name}"')
                    if value:
                        parts.append(f'value="{value}"')
                    if desc and desc != name:
                        parts.append(f'desc="{desc}"')
                    parts.append(f"(ref={ref})")
                    lines.append("  " * indent + " ".join(parts))

                for child in node.get("children") or []:
                    lines.extend(_fmt(child, indent + (0 if role in skip_roles else 1)))
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
            # Cap snapshot size to control Azure input token costs.
            # 3000 chars ≈ 750 tokens. Snapshots beyond this are mostly deep nested
            # structural noise — the AI only needs the top interactive elements.
            if len(result) > 3000:
                result = result[:3000] + "\n... (snapshot truncated — use browser_scroll if needed)"
            return result
        except Exception as exc:
            return f"Snapshot error: {exc}. URL: {page.url}"

    async def _do_navigate(self, page: Page, url: str) -> str:
        if not url:
            return "Error: No URL provided"
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(NAV_WAIT_MS)
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
            quality_score = 100.0 if passed else max(
                0.0, 100.0 * sum(1 for s in steps if s.get("passed")) / max(len(steps), 1)
            )
            timeline = [
                {
                    "seq": s["seq"],
                    "tool": s["tool"],
                    "result": s["result"][:150],
                    "duration_ms": s["duration_ms"],
                    "passed": s["passed"],
                }
                for s in steps
            ]
            summary = {
                "total_steps":  len(steps),
                "passed_steps": sum(1 for s in steps if s.get("passed")),
                "failed_steps": sum(1 for s in steps if not s.get("passed")),
                "outcome":      "PASSED" if passed else "FAILED",
                "executor":     "playwright_mcp",
            }
            report = ExecutionReport(
                id=str(_uuid_mod.uuid4()),
                run_id=run.id,
                risk_level=RiskLevel.LOW if passed else RiskLevel.HIGH,
                quality_score=quality_score,
                summary=summary,
                insights=[],
                rca_analysis={},
                recommendations=[],
                timeline=timeline,
            )
            self.db.add(report)
            await self.db.commit()
        except Exception as exc:
            log.warning("Report generation failed", run_id=run.id, error=str(exc))
