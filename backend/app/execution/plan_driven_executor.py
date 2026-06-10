"""
Plan-Driven Playwright Executor

Executes QA scenarios deterministically from the pre-generated plan + KG data.
AI is called at most 1-3 times per scenario — only when all element resolution
strategies (KG CSS → form label → Playwright semantic locators → ARIA fuzzy match)
have failed.  The normal execution path is 100% AI-free.

Execution flow:
  1. Load KG: SemanticElement selectors, ApplicationPage form fields, interaction guide
  2. Pre-login: navigate to base URL → detect login form → fill credentials → submit
  3. Iterate plan.steps in order (for step in plan.steps: resolve → execute)
  4. TestDataStore tracks every filled value for cross-step assertions
  5. fill_counter tracks repeating-field occurrences (line items, table rows)
  6. Step failures respect on_fail: "fail" stops run, "skip"/"continue" moves on
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
import uuid as _uuid_mod
from datetime import datetime
from typing import Any

import openai
import structlog
from playwright.async_api import (
    async_playwright,
    Browser,
    Page,
    Locator,
    Error as PWError,
    TimeoutError as PWTimeout,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    ApplicationModule,
    ApplicationPage,
    AIMemoryChunk,
    Credential,
    Environment,
    ExecutionLog,
    ExecutionPlan,
    ExecutionReport,
    ExecutionRun,
    ExecutionStatus,
    ExecutionStep,
    MemoryKind,
    RiskLevel,
    Scenario,
    SemanticElement,
    StepStatus,
    TestDataset,
)
from app.core.security import decrypt_credential
from app.intelligence.azure_rate_limiter import get_azure_limiter
from app.realtime.manager import connection_manager
from config import settings

log = structlog.get_logger()

STEP_TIMEOUT_MS = 15_000
NAV_WAIT_MS = 2_000
ELEMENT_TIMEOUT_MS = 8_000

# ─── Test Data Store ──────────────────────────────────────────────────────────

class TestDataStore:
    """
    Stores values filled during execution so later steps can assert them.
    Supports {FieldName} interpolation in step values.
    """

    def __init__(self) -> None:
        self._data: dict[str, str] = {}

    def store(self, target: str, value: str) -> None:
        self._data[target.strip().lower()] = value

    def get(self, target: str) -> str | None:
        return self._data.get(target.strip().lower())

    def resolve(self, text: str) -> str:
        """Replace {FieldName} with the stored value for that field."""
        if "{" not in text:
            return text
        def _sub(m: re.Match) -> str:
            key = m.group(1).strip().lower()
            return self._data.get(key, m.group(0))
        return re.sub(r"\{([^}]+)\}", _sub, text)

    def all_values(self) -> list[str]:
        return list(self._data.values())


# ─── Element Resolver ─────────────────────────────────────────────────────────

class ElementResolver:
    """
    Multi-tier element resolution.

    Tier 1 — SemanticElement DB  : CSS selectors with confidence scores from exploration
    Tier 2 — Form field labels   : get_by_label using ApplicationPage.forms metadata
    Tier 3 — Playwright locators : get_by_role / get_by_label / get_by_placeholder / get_by_text
    Tier 4 — ARIA snapshot       : fuzzy label match against live accessibility tree
    Tier 5 — AI fallback         : one Azure call; result cached to avoid repeat calls
    """

    def __init__(
        self,
        page: Page,
        kg_elements: list,           # SemanticElement ORM objects
        form_fields: list[dict],     # from ApplicationPage.forms[].fields
    ) -> None:
        self._page = page
        self._kg_elements = kg_elements
        self._form_fields = form_fields
        self._ai_cache: dict[str, str] = {}  # cache_key → CSS selector
        # Selectors discovered by AI that should be written back to KG for future runs
        self._writebacks: list[tuple[str, str]] = []  # (target_label, css_selector)

    # ── Scoring ───────────────────────────────────────────────────────────────

    @staticmethod
    def _score(a: str, b: str) -> float:
        a, b = a.lower().strip(), b.lower().strip()
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        if a in b or b in a:
            return 0.8
        wa = set(re.findall(r"\w+", a))
        wb = set(re.findall(r"\w+", b))
        return len(wa & wb) / max(len(wa), len(wb)) if wa and wb else 0.0

    # ── Public resolve ────────────────────────────────────────────────────────

    async def resolve(
        self, target: str, action: str = "click", nth: int = 0
    ) -> tuple[Locator | None, str]:
        """
        Returns (locator, strategy_label). locator is None when all tiers fail.
        nth: for repeating elements (line items), nth=1 targets the second occurrence.

        Supports pipe-delimited alternatives (e.g. "Add|New|Create|+").
        Each alternative is tried in order — shortest first — so simple labels
        like "Add" are matched before entity-specific variants like "Add CrmRecord".
        """
        parts = [p.strip() for p in target.split("|") if p.strip()]
        if len(parts) > 1:
            # Prefer shorter/simpler labels (more likely to be actual button text)
            for alt in sorted(parts, key=len):
                loc, strat = await self._resolve_single(alt, action, nth)
                if loc is not None:
                    return loc, strat
            return None, ""
        return await self._resolve_single(target, action, nth)

    async def _resolve_single(
        self, target: str, action: str = "click", nth: int = 0
    ) -> tuple[Locator | None, str]:
        """Run the full 5-tier resolution for a single (non-pipe) target."""
        # Tier 1: KG SemanticElement CSS selectors
        result = await self._kg_resolve(target, nth)
        if result[0] is not None:
            return result

        # Tier 2: ApplicationPage form field labels
        result = await self._form_field_resolve(target, nth)
        if result[0] is not None:
            return result

        # Tier 3: Playwright semantic locators
        result = await self._playwright_resolve(target, action, nth)
        if result[0] is not None:
            return result

        # Tier 4: ARIA snapshot fuzzy match
        result = await self._aria_resolve(target, nth)
        if result[0] is not None:
            return result

        # Tier 5: AI fallback (last resort)
        return await self._ai_resolve(target, action, nth)

    # ── Tier 1 ────────────────────────────────────────────────────────────────

    async def _kg_resolve(self, target: str, nth: int) -> tuple[Locator | None, str]:
        for elem in self._kg_elements:
            if self._score(elem.semantic_label, target) < 0.7:
                continue
            for sel_info in sorted(
                elem.selectors or [], key=lambda s: -(s.get("confidence", 0))
            ):
                if sel_info.get("type") != "css" or not sel_info.get("value"):
                    continue
                css = sel_info["value"]
                try:
                    loc = self._page.locator(css)
                    cnt = await loc.count()
                    if cnt > 0:
                        return loc.nth(min(nth, cnt - 1)), f"kg:{css[:50]}"
                except Exception:
                    continue
        return None, ""

    # ── Tier 2 ────────────────────────────────────────────────────────────────

    async def _form_field_resolve(self, target: str, nth: int) -> tuple[Locator | None, str]:
        for field in self._form_fields:
            label = (field.get("label") or "").strip()
            if not label or self._score(label, target) < 0.7:
                continue
            try:
                loc = self._page.get_by_label(label, exact=False)
                cnt = await loc.count()
                if cnt > 0:
                    return loc.nth(min(nth, cnt - 1)), f"form_label:{label}"
            except Exception:
                pass
        return None, ""

    # ── Tier 3 ────────────────────────────────────────────────────────────────

    async def _playwright_resolve(
        self, target: str, action: str, nth: int
    ) -> tuple[Locator | None, str]:
        page = self._page
        is_input = action in ("fill", "clear", "select")

        if is_input:
            candidates = [
                (page.get_by_label(target, exact=False),             "by_label"),
                (page.get_by_placeholder(target, exact=False),       "by_placeholder"),
                (page.get_by_role("textbox", name=target, exact=False), "textbox"),
                (page.get_by_role("combobox", name=target, exact=False), "combobox"),
                (page.get_by_role("spinbutton", name=target, exact=False), "spinbutton"),
            ]
        else:
            candidates = [
                (page.get_by_role("button",   name=target, exact=False), "button"),
                (page.get_by_role("link",     name=target, exact=False), "link"),
                (page.get_by_role("menuitem", name=target, exact=False), "menuitem"),
                (page.get_by_role("tab",      name=target, exact=False), "tab"),
                (page.get_by_role("checkbox", name=target, exact=False), "checkbox"),
                (page.get_by_text(target, exact=False),                   "text"),
            ]

        for loc, desc in candidates:
            try:
                cnt = await loc.count()
                if cnt > 0:
                    return loc.nth(min(nth, cnt - 1)), desc
            except Exception:
                continue
        return None, ""

    # ── Tier 4 ────────────────────────────────────────────────────────────────

    async def _aria_resolve(self, target: str, nth: int) -> tuple[Locator | None, str]:
        try:
            snapshot = await self._page.accessibility.snapshot(interesting_only=True)
            if not snapshot:
                return None, ""

            candidates: list[tuple[str, str, float]] = []

            def _walk(node: dict) -> None:
                role = node.get("role", "")
                name = (node.get("name") or "").strip()
                if name:
                    score = self._score(name, target)
                    if score >= 0.5:
                        candidates.append((role, name, score))
                for child in node.get("children") or []:
                    _walk(child)

            _walk(snapshot)
            if not candidates:
                return None, ""

            candidates.sort(key=lambda c: -c[2])
            role, name, _ = candidates[0]
            loc = self._page.get_by_role(role, name=name, exact=False)
            cnt = await loc.count()
            if cnt > 0:
                return loc.nth(min(nth, cnt - 1)), f"aria:{role}/{name}"
        except Exception:
            pass
        return None, ""

    # ── Tier 5 ────────────────────────────────────────────────────────────────

    async def _ai_resolve(
        self, target: str, action: str, nth: int
    ) -> tuple[Locator | None, str]:
        cache_key = f"{target}:{action}"

        if cache_key in self._ai_cache:
            css = self._ai_cache[cache_key]
            try:
                loc = self._page.locator(css)
                cnt = await loc.count()
                if cnt > 0:
                    return loc.nth(min(nth, cnt - 1)), "ai_cached"
            except Exception:
                pass

        try:
            snap = await self._page.accessibility.snapshot(interesting_only=True)
            snap_text = json.dumps(snap, indent=1)[:2500] if snap else f"URL: {self._page.url}"
        except Exception:
            snap_text = f"URL: {self._page.url}"

        try:
            client = openai.AsyncAzureOpenAI(
                api_key=settings.AZURE_OPENAI_API_KEY,
                azure_endpoint=settings.AZURE_OPENAI_ENDPOINT,
                api_version=getattr(settings, "AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
                max_retries=0,
            )
            limiter = get_azure_limiter()
            await limiter.wait()

            resp = await client.chat.completions.create(
                model=settings.AZURE_OPENAI_DEPLOYMENT,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a Playwright automation expert. "
                            "Given an ARIA accessibility tree, return the single best CSS selector "
                            "for the requested element. "
                            "Respond with ONLY the CSS selector — no explanation, no quotes, no markdown."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"Find: '{target}' (action: {action})\n\n"
                            f"ARIA tree:\n{snap_text}"
                        ),
                    },
                ],
                max_completion_tokens=100,
            )
            await client.close()

            css = (resp.choices[0].message.content or "").strip().strip("`\"'")
            if css:
                self._ai_cache[cache_key] = css
                loc = self._page.locator(css)
                cnt = await loc.count()
                if cnt > 0:
                    log.info("AI resolved element", target=target, css=css)
                    # Queue write-back so this selector is persisted to KG for future runs
                    self._writebacks.append((target, css))
                    return loc.nth(min(nth, cnt - 1)), "ai_fallback"
        except Exception as exc:
            log.warning(
                "AI element resolution failed",
                target=target, action=action, error=str(exc)[:100]
            )

        return None, "not_found"


# ─── Plan-Driven Executor ─────────────────────────────────────────────────────

class PlanDrivenPlaywrightExecutor:
    """
    Deterministic QA executor.  The AI-generated plan is the specification;
    the KG provides element resolution data.  The agentic loop is gone.
    """

    def __init__(self, db: AsyncSession, main_loop=None) -> None:
        self.db = db
        self.main_loop = main_loop
        self._screenshot_counter = 0

    # ── Entry point ───────────────────────────────────────────────────────────

    async def execute_run(self, run_id: str) -> None:
        log.info("PlanDrivenExecutor starting", run_id=run_id)

        run      = await self._load_run(run_id)
        plan     = await self._load_plan(run.plan_id) if run else None
        env      = await self._load_environment(run.environment_id) if run else None
        scenario = await self._load_scenario(run.scenario_id) if run else None

        if not run or not env or not scenario:
            if run:
                await self._fail_run(run, "Missing environment or scenario")
            log.error("Run setup failed", run_id=run_id)
            return

        if not plan or not plan.plan_data or not plan.plan_data.get("steps"):
            await self._fail_run(run, "No execution plan — generate a plan before running")
            log.error("No plan available", run_id=run_id)
            return

        app_id     = scenario.application_id
        credential = await self._load_credential(run.credential_id, app_id)
        cred_data  = await self._decrypt_credential(credential)

        kg_context = await self._load_kg_context(scenario)
        kg_elements = await self._load_kg_elements(scenario)
        dataset_items = await self._load_dataset_items(app_id)
        log.info(
            "KG loaded",
            run_id=run_id,
            elements=len(kg_elements),
            form_fields=len(kg_context.get("form_fields", [])),
            module=kg_context.get("module_name"),
            dataset_items=len(dataset_items),
        )

        run.status     = ExecutionStatus.RUNNING
        run.started_at = datetime.utcnow()
        await self.db.commit()
        await self._emit("run_started", run_id, {"scenario": scenario.title, "env": env.name})

        # Per-run video directory — one folder per run keeps artifacts organised
        videos_dir = os.path.join(settings.VIDEOS_DIR, run_id)
        os.makedirs(videos_dir, exist_ok=True)

        try:
            async with async_playwright() as pw:
                browser: Browser = await pw.chromium.launch(
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
                    # Playwright video recording — captures the entire run as a .webm file
                    record_video_dir=videos_dir,
                    record_video_size={"width": 1280, "height": 900},
                )
                page = await context.new_page()

                passed, steps_taken = await self._run_plan_steps(
                    page, run, scenario, plan, env, cred_data, kg_context, kg_elements,
                    dataset_items=dataset_items,
                )

                # Capture final-state screenshot before closing
                try:
                    final_ss = await self._save_screenshot(page, run_id, 9999)
                    steps_taken.append({
                        "seq": 9999, "action": "screenshot", "target": "final_state",
                        "value": "", "result": "Final state captured", "passed": True,
                        "duration_ms": 0, "screenshot_path": final_ss, "phase": "TEARDOWN",
                        "checkpoint": False, "on_fail": "skip",
                    })
                except Exception:
                    final_ss = None

                # Get video path BEFORE closing the context (Playwright requires this order)
                video_path: str | None = None
                try:
                    if page.video:
                        video_path = await page.video.path()
                except Exception as exc:
                    log.warning("Could not get video path", error=str(exc)[:100])

                await context.close()   # Finalises and flushes the video file to disk
                await browser.close()

            final_status = ExecutionStatus.COMPLETED if passed else ExecutionStatus.FAILED
            run.status       = final_status
            run.completed_at = datetime.utcnow()
            run.total_steps  = len(steps_taken)
            run.passed_steps = sum(1 for s in steps_taken if s.get("passed"))
            run.failed_steps = sum(1 for s in steps_taken if not s.get("passed"))

            # Persist evidence references on the run record
            run.screenshot_paths = [
                s["screenshot_path"] for s in steps_taken
                if s.get("screenshot_path")
            ]
            if video_path:
                run.video_path = video_path
                log.info("Video recorded", run_id=run_id, path=video_path)

            await self.db.commit()
            await self._emit(
                "run_completed", run_id,
                {"status": final_status.value, "steps": run.total_steps, "video": video_path},
            )
            await self._build_report(run, scenario, steps_taken, passed)

        except asyncio.CancelledError:
            run.status       = ExecutionStatus.CANCELLED
            run.completed_at = datetime.utcnow()
            await self.db.commit()
            await self._emit("run_cancelled", run_id, {})
        except Exception as exc:
            log.exception("PlanDrivenExecutor crashed", run_id=run_id, error=str(exc))
            await self._fail_run(run, f"Executor error: {exc!s}")

    # ── Plan step loop ────────────────────────────────────────────────────────

    async def _run_plan_steps(
        self,
        page: Page,
        run: ExecutionRun,
        scenario: Scenario,
        plan: ExecutionPlan,
        env: Environment,
        cred_data: dict,
        kg_context: dict,
        kg_elements: list,
        dataset_items: list | None = None,
    ) -> tuple[bool, list[dict]]:

        steps = plan.plan_data.get("steps", [])
        form_fields = kg_context.get("form_fields", [])

        resolver   = ElementResolver(page, kg_elements, form_fields)
        test_data  = TestDataStore()

        # Pre-seed TestDataStore from the application's dataset items so plan steps
        # can reference {{invalid_email}}, {{boundary_number}}, {{oversized_file_path}}, etc.
        if dataset_items:
            # For text-type categories pick the first item as the default value
            _text_categories: set[str] = set()
            for di in dataset_items:
                cat = di.category or ""
                if di.data_type != "file" and di.text_value and cat not in _text_categories:
                    test_data.store(cat, di.text_value)
                    _text_categories.add(cat)
            # For file categories store the absolute path so upload steps can use it
            _file_categories: set[str] = set()
            for di in dataset_items:
                cat = di.category or ""
                if di.data_type == "file" and di.file_path and cat not in _file_categories:
                    test_data.store(f"{cat}_path", di.file_path)
                    test_data.store(f"{cat}_name", di.file_name or os.path.basename(di.file_path))
                    _file_categories.add(cat)
        # Tracks how many times each target label has been filled (for repeating rows).
        # Reset when a page navigation occurs.
        fill_counter: dict[str, int] = {}

        steps_taken: list[dict] = []
        passed = True
        seq = 0

        # ── Pre-login ─────────────────────────────────────────────────────────
        await self._emit("step_started", run.id, {
            "seq": 1, "action": "login",
            "target": cred_data.get("username", ""),
            "phase": "SETUP",
        })
        login_result = await self._do_login(page, env, cred_data)
        seq += 1
        screenshot_path = None
        try:
            screenshot_path = await self._save_screenshot(page, run.id, seq)
        except Exception:
            pass

        username = cred_data.get("username", "")
        login_passed = not login_result.startswith("Error")

        login_step = {
            "seq": seq,
            "action": "login",
            "target": "credentials",
            "value": username,
            "result": login_result,
            "passed": login_passed,
            "duration_ms": 0,
            "screenshot_path": screenshot_path,
            "phase": "SETUP",
            "checkpoint": True,
            "on_fail": "fail",
        }
        steps_taken.append(login_step)
        await self._record_step(run, login_step)

        # Emit individual login sub-steps to the execution log so the UI shows
        # exactly what happened during authentication.
        if username:
            await self._log_db(run, "INFO", "login",
                f"[{seq}] login → Username '{username}' entered")
            await self._log_db(run, "INFO", "login",
                f"[{seq}] login → Password '{'•' * 8}' entered")
            await self._log_db(run, "INFO" if login_passed else "ERROR", "login",
                f"[{seq}] login → Sign In button clicked — {login_result}")
        else:
            await self._log_db(run, "INFO", "login",
                f"[{seq}] login → {login_result}")
        await self.db.commit()

        if not login_passed:
            return False, steps_taken

        # ── Execute plan steps ────────────────────────────────────────────────
        for raw_step in steps:
            action  = (raw_step.get("action") or "").strip().lower()
            target  = (raw_step.get("target") or "").strip()
            # Plans from capability engine / fallback store URL in "url" field,
            # AI-generated plans store it in "target". Accept both.
            if action == "navigate" and not target:
                target = (raw_step.get("url") or "").strip()
            value   = test_data.resolve((raw_step.get("value") or "").strip())
            on_fail = (raw_step.get("on_fail") or "fail").lower()
            timeout = int(raw_step.get("timeout_ms") or STEP_TIMEOUT_MS)
            checkpoint = bool(raw_step.get("checkpoint", False))
            phase   = raw_step.get("phase", "")
            seq    += 1

            # Reset fill counter on navigation (new page = no repeating elements carry over)
            if action == "navigate":
                fill_counter.clear()

            # Notify frontend that this step is starting — important for long-running
            # steps (AI element resolution, network waits) so the user isn't left wondering.
            await self._emit("step_started", run.id, {
                "seq": seq,
                "action": action,
                "target": target[:80] if target else "",
                "phase": phase,
            })
            await self._log_db(
                run, "INFO", "step",
                f"[{seq}] {action} → '{target[:60]}' starting…" if target else f"[{seq}] {action} starting…",
            )

            t_start = time.monotonic()
            result_text = await self._execute_action(
                page, action, target, value, timeout,
                resolver, fill_counter, test_data, env,
                dataset_items=dataset_items,
            )
            duration_ms = int((time.monotonic() - t_start) * 1000)

            step_passed = not result_text.startswith("Error") and not result_text.startswith("Assertion FAILED")

            # Screenshots: always capture on failure or checkpoint; skip routine passing steps
            # to keep artifact count manageable. Assertions, navigation, and checkpoints always
            # get a screenshot; simple waits/scrolls do not.
            _always_screenshot = action in (
                "navigate", "assert_visible", "assert_text", "assert_not_text",
                "assert_url", "assert_count", "click",
            )
            screenshot_path: str | None = None
            error_screenshot_path: str | None = None
            if not step_passed or checkpoint or _always_screenshot:
                try:
                    screenshot_path = await self._save_screenshot(page, run.id, seq)
                    if not step_passed:
                        error_screenshot_path = screenshot_path
                except Exception:
                    pass

            step_record = {
                "seq": seq,
                "action": action,
                "target": target,
                "value": value,
                "result": result_text,
                "passed": step_passed,
                "duration_ms": duration_ms,
                "screenshot_path": screenshot_path,
                "error_screenshot_path": error_screenshot_path,
                "phase": phase,
                "checkpoint": checkpoint,
                "on_fail": on_fail,
                "error_type": (
                    self._classify_failure(result_text, action, target)
                    if not step_passed else None
                ),
            }
            steps_taken.append(step_record)

            log.info(
                "Step executed",
                run_id=run.id,
                seq=seq,
                action=action,
                target=target[:50] if target else "",
                passed=step_passed,
                strategy=result_text[:60],
            )

            await self._record_step(run, step_record)
            await self._emit("step_completed", run.id, {
                "seq": seq,
                "action": action,
                "status": "passed" if step_passed else "failed",
                "result": result_text[:200],
            })

            # Build a human-readable log line for the execution log panel
            if action == "navigate":
                nav_url = target or value or ""
                _log_msg = f"[{seq}] navigate → URL: '{nav_url}' — {result_text[:120]}"
            elif action == "fill":
                _log_msg = f"[{seq}] fill → '{target}' with value '{value}' — {result_text[:100]}"
            elif action == "click":
                _log_msg = f"[{seq}] click → '{target}' — {result_text[:120]}"
            elif action in ("assert_visible", "assert_text", "assert_not_text",
                            "assert_url", "assert_count"):
                status = "PASS" if step_passed else "FAIL"
                _log_msg = f"[{seq}] {action} → '{target}' [{status}] — {result_text[:100]}"
            elif action == "screenshot":
                _log_msg = f"[{seq}] screenshot — {result_text[:120]}"
            elif action == "wait_ms":
                _log_msg = f"[{seq}] wait_ms — {result_text[:80]}"
            elif action in ("select", "clear"):
                _log_msg = f"[{seq}] {action} → '{target}' value='{value}' — {result_text[:100]}"
            else:
                _log_msg = f"[{seq}] {action} → '{target}': {result_text[:150]}"

            await self._log_db(
                run, "INFO" if step_passed else "WARN", "action",
                _log_msg,
                {"action": action, "target": target, "value": value, "duration_ms": duration_ms},
            )
            await self.db.commit()

            if not step_passed and on_fail == "fail":
                passed = False
                await self._log_db(run, "ERROR", "executor",
                                   f"Step {seq} failed with on_fail=fail — stopping run")
                break

        # Persist AI-discovered selectors back to KG so future runs skip Tier 5
        if resolver._writebacks:
            await self._persist_ai_writebacks(resolver._writebacks, kg_elements)

        return passed, steps_taken

    # ── Action dispatcher ─────────────────────────────────────────────────────

    async def _execute_action(
        self,
        page: Page,
        action: str,
        target: str,
        value: str,
        timeout: int,
        resolver: ElementResolver,
        fill_counter: dict[str, int],
        test_data: TestDataStore,
        env: Environment,
        dataset_items: list | None = None,
    ) -> str:
        try:
            if action == "navigate":
                return await self._act_navigate(page, target, value, env)

            elif action == "click":
                return await self._act_click(page, target, resolver)

            elif action in ("fill", "type"):
                nth = fill_counter.get(target.lower(), 0)
                result = await self._act_fill(page, target, value, resolver, nth)
                if not result.startswith("Error"):
                    fill_counter[target.lower()] = nth + 1
                    test_data.store(target, value)
                return result

            elif action == "select":
                nth = fill_counter.get(target.lower(), 0)
                result = await self._act_select(page, target, value, resolver, nth)
                if not result.startswith("Error"):
                    fill_counter[target.lower()] = nth + 1
                    test_data.store(target, value)
                return result

            elif action == "clear":
                nth = fill_counter.get(target.lower(), 0)
                return await self._act_clear(page, target, resolver, nth)

            elif action == "assert_visible":
                return await self._act_assert_visible(page, target, value, test_data, timeout)

            elif action == "assert_text":
                return await self._act_assert_text(page, target, value, resolver, timeout)

            elif action in ("assert_not_text", "assert_not_visible"):
                return await self._act_assert_not_visible(page, target, value, timeout)

            elif action == "assert_url":
                return self._act_assert_url(page, value or target)

            elif action == "assert_count":
                return await self._act_assert_count(page, target, value, resolver)

            elif action in ("wait_ms", "wait"):
                ms = int(value or target or "1000") if (value or target or "").isdigit() else 1000
                try:
                    ms = int(value) if value.isdigit() else int(target) if target.isdigit() else 1000
                except Exception:
                    ms = 1000
                await page.wait_for_timeout(ms)
                return f"Waited {ms}ms"

            elif action == "wait_element":
                return await self._act_wait_element(page, target, resolver, timeout)

            elif action == "wait_network":
                await page.wait_for_load_state("networkidle", timeout=20_000)
                return "Network idle"

            elif action == "scroll":
                direction = (value or target or "down").lower()
                dy = 400 if direction == "down" else -400
                await page.evaluate(f"window.scrollBy(0, {dy})")
                return f"Scrolled {direction}"

            elif action == "screenshot":
                return f"Screenshot captured — URL: {page.url}"

            elif action == "key_press":
                key = value or target
                if not key:
                    return "Error: No key specified"
                await page.keyboard.press(key)
                return f"Pressed '{key}'"

            elif action == "hover":
                return await self._act_hover(page, target, resolver)

            elif action == "upload":
                return await self._act_upload(page, target, value, resolver, test_data, dataset_items)

            else:
                return f"Skipped: unknown action '{action}'"

        except PWTimeout:
            return f"Error: Timeout ({timeout}ms) — {action} → '{target}'"
        except PWError as exc:
            return f"Error: Playwright — {str(exc)[:200]}"
        except Exception as exc:
            return f"Error: {str(exc)[:200]}"

    # ── Action implementations ────────────────────────────────────────────────

    async def _act_navigate(self, page: Page, target: str, value: str, env: Environment) -> str:
        url = value or target
        if not url:
            return "Error: No URL specified for navigate"
        if not url.startswith("http"):
            url = env.base_url.rstrip("/") + "/" + url.lstrip("/")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(NAV_WAIT_MS)
            return f"Navigated to {page.url}"
        except PWTimeout:
            return f"Navigation timeout — page may still be loading. URL: {page.url}"

    async def _act_click(self, page: Page, target: str, resolver: ElementResolver) -> str:
        loc, strategy = await resolver.resolve(target, action="click")
        if loc is None:
            return f"Error: Element not found: '{target}'"
        try:
            await loc.click(timeout=STEP_TIMEOUT_MS)
            await page.wait_for_timeout(500)
            return f"Clicked '{target}' [{strategy}]"
        except Exception as exc:
            try:
                await loc.click(force=True, timeout=5_000)
                await page.wait_for_timeout(500)
                return f"Clicked '{target}' [force, {strategy}]"
            except Exception as exc2:
                return f"Error: Click failed on '{target}' — {str(exc2)[:150]}"

    async def _act_fill(
        self, page: Page, target: str, value: str,
        resolver: ElementResolver, nth: int,
    ) -> str:
        loc, strategy = await resolver.resolve(target, action="fill", nth=nth)
        if loc is None:
            return f"Error: Field not found: '{target}'"

        # Detect date fields and use a JS-safe fill strategy
        field_type = await self._detect_field_type(loc)
        if field_type == "date":
            result = await self._fill_date(page, loc, value, target)
            return result

        try:
            await loc.clear(timeout=3_000)
            await loc.fill(value, timeout=STEP_TIMEOUT_MS)
            return f"Filled '{target}' = '{value[:60]}' [{strategy}]"
        except Exception:
            # Fallback: click to focus then keyboard type
            try:
                await loc.click(timeout=3_000)
                await page.keyboard.press("Control+a")
                await page.keyboard.press("Delete")
                await loc.type(value, delay=30)
                return f"Typed '{target}' = '{value[:60]}' [type_fallback, {strategy}]"
            except Exception as exc:
                return f"Error: Could not fill '{target}' — {str(exc)[:150]}"

    async def _act_upload(
        self,
        page: Page,
        target: str,
        value: str,
        resolver: ElementResolver,
        test_data: TestDataStore,
        dataset_items: list | None,
    ) -> str:
        """Upload a file.  Priority: (1) explicit path in step value, (2) dataset item matched
        by category keyword in target/value, (3) any file dataset item available."""
        # Resolve the file path
        file_path: str | None = None
        chosen_label: str = "unknown"

        # 1 — Explicit path in step value
        if value and os.path.isfile(value):
            file_path = value
            chosen_label = os.path.basename(value)

        # 2 — Resolve {{category_path}} placeholder from test_data
        if not file_path and value:
            resolved = test_data.resolve(value)
            if resolved != value and os.path.isfile(resolved):
                file_path = resolved
                chosen_label = os.path.basename(resolved)

        # 3 — Match a dataset file item by category keyword from target+value
        if not file_path and dataset_items:
            hint = (target + " " + value).lower()
            file_items = [
                di for di in dataset_items
                if di.data_type == "file" and di.file_path and os.path.isfile(di.file_path)
            ]
            for di in file_items:
                cat_kw = di.category.replace("_", " ")
                if any(kw in hint for kw in cat_kw.split()):
                    file_path = di.file_path
                    chosen_label = f"dataset:{di.category}:{di.file_name or di.label}"
                    break
            # 4 — Any available file as a last resort
            if not file_path and file_items:
                di = file_items[0]
                file_path = di.file_path
                chosen_label = f"dataset:{di.category}:{di.file_name or di.label}"

        if not file_path:
            return f"Skipped: no file available for upload (target: '{target}'). Add a file in the Dataset module."

        # Locate the file input element
        loc, strategy = await resolver.resolve(target, action="fill")
        if loc is None:
            # Fallback: find any visible file input on the page
            loc = page.locator("input[type='file']").first
            strategy = "file_input_fallback"

        try:
            await loc.set_input_files(file_path, timeout=STEP_TIMEOUT_MS)
            await page.wait_for_timeout(500)
            return f"Uploaded '{chosen_label}' to '{target}' [{strategy}]"
        except Exception as exc:
            return f"Error: File upload failed on '{target}' — {str(exc)[:200]}"

    async def _act_select(
        self, page: Page, target: str, value: str,
        resolver: ElementResolver, nth: int,
    ) -> str:
        loc, strategy = await resolver.resolve(target, action="select", nth=nth)
        if loc is None:
            return f"Error: Dropdown not found: '{target}'"

        # Try native <select> first
        for select_fn in (
            lambda: loc.select_option(label=value, timeout=3_000),
            lambda: loc.select_option(value=value, timeout=3_000),
        ):
            try:
                await select_fn()
                return f"Selected '{value}' in '{target}' [native, {strategy}]"
            except Exception:
                pass

        # Angular Material / custom dropdown: click to open → click option
        try:
            await loc.click(timeout=3_000)
            await page.wait_for_timeout(600)

            # Try role=option first, then visible text
            opt = page.get_by_role("option", name=value, exact=False)
            if await opt.count() == 0:
                opt = page.get_by_text(value, exact=False)
            await opt.first.click(timeout=5_000)
            return f"Selected '{value}' in '{target}' [dropdown, {strategy}]"
        except Exception as exc:
            return f"Error: Select failed '{target}' = '{value}' — {str(exc)[:150]}"

    async def _act_clear(
        self, page: Page, target: str,
        resolver: ElementResolver, nth: int,
    ) -> str:
        loc, strategy = await resolver.resolve(target, action="clear", nth=nth)
        if loc is None:
            return f"Error: Field not found for clear: '{target}'"
        try:
            await loc.clear(timeout=STEP_TIMEOUT_MS)
            return f"Cleared '{target}' [{strategy}]"
        except Exception as exc:
            return f"Error: Could not clear '{target}' — {str(exc)[:100]}"

    async def _act_assert_visible(
        self, page: Page, target: str, value: str,
        test_data: TestDataStore, timeout: int,
    ) -> str:
        # Priority: explicit value → stored test_data for this target → target text itself
        text = value or test_data.get(target) or target
        if not text:
            return "Error: No text specified for assert_visible"
        try:
            await page.get_by_text(text, exact=False).first.wait_for(
                state="visible", timeout=timeout or 5_000
            )
            return f"Assertion passed: '{text}' is visible"
        except Exception:
            # Broader check: is the text anywhere in the DOM?
            content = await page.content()
            if text.lower() in content.lower():
                return f"Assertion passed: '{text}' found in page content"
            return f"Assertion FAILED: '{text}' not visible on page"

    async def _act_assert_text(
        self, page: Page, target: str, value: str,
        resolver: ElementResolver, timeout: int,
    ) -> str:
        if not value:
            return f"Error: No expected value for assert_text on '{target}'"
        loc, strategy = await resolver.resolve(target, action="assert")
        if loc is None:
            # Page-wide text search fallback
            try:
                await page.get_by_text(value, exact=False).first.wait_for(
                    state="visible", timeout=timeout or 5_000
                )
                return f"Assertion passed: text '{value}' visible on page"
            except Exception:
                return f"Assertion FAILED: '{value}' not found for target '{target}'"
        try:
            actual = await loc.first.inner_text(timeout=timeout or 5_000)
            if value.lower() in actual.lower():
                return f"Assertion passed: '{target}' contains '{value}'"
            return f"Assertion FAILED: '{target}' expected '{value}', got '{actual[:80]}'"
        except Exception as exc:
            return f"Error: Cannot read text from '{target}' — {str(exc)[:100]}"

    async def _act_assert_not_visible(
        self, page: Page, target: str, value: str, timeout: int,
    ) -> str:
        text = value or target
        if not text:
            return "Error: No text specified for assert_not_visible"
        try:
            await page.get_by_text(text, exact=False).first.wait_for(
                state="hidden", timeout=timeout or 5_000
            )
            return f"Assertion passed: '{text}' is NOT visible"
        except Exception:
            content = await page.content()
            if text.lower() not in content.lower():
                return f"Assertion passed: '{text}' not found in page"
            return f"Assertion FAILED: '{text}' is still visible on page"

    def _act_assert_url(self, page: Page, expected: str) -> str:
        current = page.url
        if expected.lower() in current.lower():
            return f"Assertion passed: URL contains '{expected}'"
        return f"Assertion FAILED: expected URL '{expected}', got '{current}'"

    async def _act_assert_count(
        self, page: Page, target: str, value: str,
        resolver: ElementResolver,
    ) -> str:
        expected = int(value) if value and value.isdigit() else None
        try:
            # Try as CSS selector first (useful for table rows)
            cnt = await page.locator(target).count()
        except Exception:
            loc, _ = await resolver.resolve(target, action="assert")
            cnt = await loc.count() if loc else 0

        if expected is None:
            return f"Count of '{target}': {cnt}"
        if cnt == expected:
            return f"Assertion passed: {cnt} '{target}' elements found"
        return f"Assertion FAILED: expected {expected} '{target}' elements, found {cnt}"

    async def _act_wait_element(
        self, page: Page, target: str,
        resolver: ElementResolver, timeout: int,
    ) -> str:
        loc, strategy = await resolver.resolve(target, action="click")
        if loc is None:
            return f"Error: Element not found for wait: '{target}'"
        try:
            await loc.wait_for(state="visible", timeout=timeout or 15_000)
            return f"Element visible: '{target}' [{strategy}]"
        except Exception as exc:
            return f"Error: Timeout waiting for '{target}' — {str(exc)[:100]}"

    async def _act_hover(self, page: Page, target: str, resolver: ElementResolver) -> str:
        loc, strategy = await resolver.resolve(target, action="click")
        if loc is None:
            return f"Error: Element not found for hover: '{target}'"
        try:
            await loc.hover(timeout=STEP_TIMEOUT_MS)
            return f"Hovered over '{target}' [{strategy}]"
        except Exception as exc:
            return f"Error: Hover failed on '{target}' — {str(exc)[:100]}"

    # ── Date field helpers ────────────────────────────────────────────────────

    async def _detect_field_type(self, loc: Locator) -> str:
        """Return 'date' if the locator points to a date input, else 'text'."""
        try:
            input_type = await loc.get_attribute("type", timeout=1_000)
            if input_type == "date":
                return "date"
            placeholder = (await loc.get_attribute("placeholder", timeout=1_000) or "").lower()
            if "date" in placeholder or "dd/mm" in placeholder or "mm/dd" in placeholder:
                return "date"
        except Exception:
            pass
        return "text"

    async def _fill_date(self, page: Page, loc: Locator, value: str, target: str) -> str:
        """Fill a date field using direct input or JS setter for Angular Material."""
        # Normalise to YYYY-MM-DD if possible
        date_value = value
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%m-%d-%Y"):
            try:
                from datetime import datetime as dt
                date_value = dt.strptime(value, fmt).strftime("%Y-%m-%d")
                break
            except Exception:
                pass

        # Try 1: direct fill (HTML5 date input)
        try:
            await loc.fill(date_value, timeout=3_000)
            return f"Filled date '{target}' = '{value}' [direct]"
        except Exception:
            pass

        # Try 2: type the value (Angular material datefields accept typed input)
        try:
            await loc.click(timeout=3_000)
            await page.keyboard.press("Control+a")
            await loc.type(value, delay=50)
            await page.keyboard.press("Escape")
            return f"Typed date '{target}' = '{value}' [type]"
        except Exception:
            pass

        # Try 3: JavaScript setter for Angular Material date pickers
        try:
            await page.evaluate(
                """([sel, val]) => {
                    const el = document.querySelector(sel);
                    if (!el) return;
                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    ).set;
                    nativeInputValueSetter.call(el, val);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""",
                [f'input[placeholder*="date" i]', date_value],
            )
            return f"Set date '{target}' = '{value}' [js_setter]"
        except Exception as exc:
            return f"Error: Could not fill date '{target}' = '{value}' — {str(exc)[:100]}"

    # ── Login ─────────────────────────────────────────────────────────────────

    async def _do_login(self, page: Page, env: Environment, cred_data: dict) -> str:
        """
        Navigate to base URL, detect login form, fill credentials, submit.
        Returns success message or Error string.
        """
        username = cred_data.get("username", "")
        password = cred_data.get("password", "")

        if not username:
            return "Skipped login: no credentials configured"

        try:
            await page.goto(env.base_url, wait_until="domcontentloaded", timeout=30_000)
            await page.wait_for_timeout(NAV_WAIT_MS)
        except Exception as exc:
            return f"Error: Could not reach {env.base_url} — {str(exc)[:100]}"

        # Check if a login form exists — if not, we may already be logged in
        login_indicators = [
            'input[type="password"]',
            'input[name*="password" i]',
            'input[placeholder*="password" i]',
        ]
        has_login_form = False
        for sel in login_indicators:
            try:
                if await page.locator(sel).count() > 0:
                    has_login_form = True
                    break
            except Exception:
                pass

        if not has_login_form:
            return f"Login skipped: no login form detected at {page.url}"

        # Fill username
        username_filled = False
        for loc_fn, desc in [
            (page.get_by_label("username", exact=False),         "label:username"),
            (page.get_by_label("email", exact=False),            "label:email"),
            (page.get_by_placeholder("username", exact=False),   "placeholder:username"),
            (page.get_by_placeholder("email", exact=False),      "placeholder:email"),
            (page.locator('input[name*="username" i]'),           "name:username"),
            (page.locator('input[name*="email" i]'),              "name:email"),
            (page.locator('input[type="email"]'),                 "type:email"),
            (page.locator('input[type="text"]:visible').first,    "first_text_input"),
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
                    log.debug("Login: password filled", strategy=desc)
                    break
            except Exception:
                continue

        if not password_filled:
            return f"Error: Could not find password field at {page.url}"

        # Submit
        url_before = page.url
        submit_clicked = False
        for loc_fn, desc in [
            (page.get_by_role("button", name="login", exact=False),  "btn:login"),
            (page.get_by_role("button", name="sign in", exact=False), "btn:sign_in"),
            (page.get_by_role("button", name="submit", exact=False),  "btn:submit"),
            (page.get_by_role("button", name="log in", exact=False),  "btn:log_in"),
            (page.locator('button[type="submit"]:visible').first,     "type:submit"),
            (page.locator('input[type="submit"]:visible').first,      "input:submit"),
        ]:
            try:
                cnt = await loc_fn.count() if hasattr(loc_fn, "count") else 1
                if cnt > 0:
                    target_loc = loc_fn.first if hasattr(loc_fn, "first") else loc_fn
                    await target_loc.click(timeout=5_000)
                    submit_clicked = True
                    log.debug("Login: submit clicked", strategy=desc)
                    break
            except Exception:
                continue

        if not submit_clicked:
            # Try pressing Enter on the password field
            try:
                await page.keyboard.press("Enter")
                submit_clicked = True
            except Exception:
                return "Error: Could not find or click login submit button"

        # Wait for navigation (successful login should redirect)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15_000)
            await page.wait_for_timeout(NAV_WAIT_MS)
        except Exception:
            pass

        if page.url != url_before or "login" not in page.url.lower():
            return f"Login successful — redirected to {page.url}"

        # Check for error messages
        error_indicators = ["invalid", "incorrect", "wrong", "failed", "error"]
        try:
            content = (await page.content()).lower()
            for err in error_indicators:
                if err in content:
                    return f"Error: Login failed — error message detected on page"
        except Exception:
            pass

        return f"Login submitted — current URL: {page.url}"

    # ── KG write-back and failure diagnosis ──────────────────────────────────

    async def _persist_ai_writebacks(
        self, writebacks: list[tuple[str, str]], kg_elements: list
    ) -> None:
        """
        Persist AI-discovered CSS selectors back to SemanticElement so future runs
        can resolve these elements at Tier 1 (KG CSS lookup) instead of falling all
        the way to Tier 5 (AI).  Called after every run that had at least one
        AI-resolved element.
        """
        if not writebacks or not kg_elements:
            return
        updated = 0
        for target, css in writebacks:
            best_elem = None
            best_score = 0.7
            for elem in kg_elements:
                score = ElementResolver._score(elem.semantic_label, target)
                if score > best_score:
                    best_score = score
                    best_elem = elem
            if not best_elem:
                continue
            existing = list(best_elem.selectors or [])
            if any(s.get("value") == css for s in existing):
                continue  # already known
            existing.insert(0, {
                "type": "css",
                "value": css,
                "confidence": 0.75,
                "source": "ai_resolved",
            })
            best_elem.selectors = existing
            updated += 1
            log.info("KG write-back", target=target, css=css[:80], element=best_elem.id)
        if updated:
            try:
                await self.db.commit()
                log.info("KG write-back committed", count=updated)
            except Exception as exc:
                log.warning("KG write-back commit failed", error=str(exc)[:100])

    @staticmethod
    def _classify_failure(error_msg: str, action: str, target: str) -> str:
        """
        Classify a step failure into a diagnostic category so reports and dashboards
        can group failures by root cause instead of showing raw error strings.

        Categories:
          selector_timeout    — element found but didn't become interactive in time
          element_not_found   — no matching element at all
          element_stale       — element detached from DOM between detection and action
          form_validation     — app rejected the submitted value (validation error)
          navigation_error    — page failed to load (network / redirect issue)
          assertion_failed    — explicit assertion step failed (content mismatch)
          unknown             — none of the above
        """
        e = (error_msg or "").lower()
        if "timed out" in e or "timeout" in e:
            return "selector_timeout"
        if "not found" in e or "count=0" in e or "no element" in e or "unable to locate" in e:
            return "element_not_found"
        if "stale" in e or "detached" in e:
            return "element_stale"
        if action in ("fill", "type", "select") and any(
            kw in e for kw in ("required", "validation", "invalid", "not allowed", "must be")
        ):
            return "form_validation"
        if action == "navigate" and any(
            kw in e for kw in ("net::", "failed to load", "err_", "refused")
        ):
            return "navigation_error"
        if "assertion failed" in e or "assert" in e.split(":")[0]:
            return "assertion_failed"
        return "unknown"

    # ── KG loading ────────────────────────────────────────────────────────────

    async def _load_kg_context(self, scenario: Scenario) -> dict:
        ctx: dict = {
            "module_name": "",
            "module_url": "",
            "interaction_guide": "",
            "form_fields": [],
        }
        if not scenario.module_id:
            return ctx
        try:
            mod = (await self.db.execute(
                select(ApplicationModule).where(ApplicationModule.id == scenario.module_id)
            )).scalar_one_or_none()
            if mod:
                ctx["module_name"] = mod.name or ""
                ctx["module_url"]  = mod.url_pattern or ""

            guides = (await self.db.execute(
                select(AIMemoryChunk).where(
                    AIMemoryChunk.application_id == scenario.application_id,
                    AIMemoryChunk.kind == MemoryKind.WORKFLOW,
                )
            )).scalars().all()
            guide_texts = [
                c.content for c in guides
                if (c.extra or {}).get("guide_type") == "interaction"
                and (c.extra or {}).get("module_id") == scenario.module_id
            ]
            if guide_texts:
                ctx["interaction_guide"] = "\n\n---\n\n".join(guide_texts)

            pages = (await self.db.execute(
                select(ApplicationPage).where(
                    ApplicationPage.module_id == scenario.module_id
                ).limit(5)
            )).scalars().all()
            fields: list[dict] = []
            seen: set[str] = set()
            for p in pages:
                for form in (p.forms or [])[:3]:
                    for f in (form.get("fields") or [])[:20]:
                        label = (f.get("label") or "").strip()
                        if label and label not in seen:
                            seen.add(label)
                            fields.append({
                                "label":    label,
                                "type":     f.get("type", "text"),
                                "required": bool(f.get("required", False)),
                                "options":  (f.get("options") or [])[:5],
                            })
            ctx["form_fields"] = fields[:40]
        except Exception as exc:
            log.warning("KG context load failed", error=str(exc)[:150])
        return ctx

    async def _load_dataset_items(self, app_id: str) -> list:
        """Load TestDataset items for this application — used to seed TestDataStore."""
        try:
            result = await self.db.execute(
                select(TestDataset).where(TestDataset.application_id == app_id)
            )
            return list(result.scalars().all())
        except Exception as exc:
            log.warning("Dataset items load failed", error=str(exc)[:150])
            return []

    async def _load_kg_elements(self, scenario: Scenario) -> list:
        """Load SemanticElement rows for this module — ordered by confidence desc."""
        if not scenario.module_id:
            return []
        try:
            pages = (await self.db.execute(
                select(ApplicationPage).where(
                    ApplicationPage.module_id == scenario.module_id
                )
            )).scalars().all()
            page_ids = [p.id for p in pages]
            if not page_ids:
                return []
            elements = (await self.db.execute(
                select(SemanticElement)
                .where(SemanticElement.page_id.in_(page_ids))
                .order_by(SemanticElement.confidence.desc())
            )).scalars().all()
            return list(elements)
        except Exception as exc:
            log.warning("KG elements load failed", error=str(exc)[:150])
            return []

    # ── Screenshots ───────────────────────────────────────────────────────────

    async def _save_screenshot(self, page: Page, run_id: str, seq: int) -> str:
        os.makedirs(settings.SCREENSHOTS_DIR, exist_ok=True)
        path = os.path.join(settings.SCREENSHOTS_DIR, f"pd_{run_id}_{seq:03d}.png")
        await page.screenshot(path=path, full_page=False)
        return path

    # ── DB helpers ────────────────────────────────────────────────────────────

    async def _record_step(self, run: ExecutionRun, step: dict) -> None:
        step_passed = step["passed"]
        record = ExecutionStep(
            id=str(_uuid_mod.uuid4()),
            run_id=run.id,
            sequence=step["seq"],
            action_type=step["action"],
            description=f"{step['action']}: {step['target']} {step['value']}".strip()[:250],
            plan_step={
                "action": step["action"],
                "target": step["target"],
                "value":  step["value"],
                "result": step["result"][:500],
                "phase":  step.get("phase", ""),
            },
            status=StepStatus.PASSED if step_passed else StepStatus.FAILED,
            started_at=datetime.utcnow(),
            completed_at=datetime.utcnow(),
            duration_ms=step["duration_ms"],
            screenshot_path=step.get("screenshot_path"),
            error_screenshot_path=step.get("error_screenshot_path") if not step_passed else None,
            error_message=step["result"] if not step_passed else None,
        )
        self.db.add(record)

    async def _load_run(self, run_id: str) -> ExecutionRun | None:
        return (await self.db.execute(
            select(ExecutionRun).where(ExecutionRun.id == run_id)
        )).scalar_one_or_none()

    async def _load_plan(self, plan_id: str) -> ExecutionPlan | None:
        return (await self.db.execute(
            select(ExecutionPlan).where(ExecutionPlan.id == plan_id)
        )).scalar_one_or_none()

    async def _load_environment(self, env_id: str) -> Environment | None:
        return (await self.db.execute(
            select(Environment).where(Environment.id == env_id)
        )).scalar_one_or_none()

    async def _load_scenario(self, scenario_id: str) -> Scenario | None:
        return (await self.db.execute(
            select(Scenario).where(Scenario.id == scenario_id)
        )).scalar_one_or_none()

    async def _load_credential(self, cred_id: str | None, app_id: str | None) -> Credential | None:
        if cred_id:
            return (await self.db.execute(
                select(Credential).where(Credential.id == cred_id)
            )).scalar_one_or_none()
        if app_id:
            return (await self.db.execute(
                select(Credential).where(Credential.application_id == app_id).limit(1)
            )).scalar_one_or_none()
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
        self, run: ExecutionRun, level: str, category: str,
        message: str, extra: dict | None = None,
    ) -> None:
        log_id = str(_uuid_mod.uuid4())
        ts = datetime.utcnow()
        self.db.add(ExecutionLog(
            id=log_id,
            run_id=run.id,
            timestamp=ts,
            level=level,
            category=category,
            message=message,
            extra=extra or {},
        ))
        # Emit immediately via WebSocket — the frontend receives each log entry
        # in real-time without waiting for the next DB commit + poll cycle.
        await self._emit("run_log", run.id, {
            "id": log_id,
            "timestamp": ts.isoformat(),
            "level": level,
            "category": category,
            "message": message,
        })

    async def _emit(self, event: str, run_id: str, data: dict) -> None:
        try:
            payload = {"type": event, "run_id": run_id, **data}
            if self.main_loop:
                asyncio.run_coroutine_threadsafe(
                    connection_manager.broadcast(payload), self.main_loop
                )
            else:
                await connection_manager.broadcast(payload)
        except Exception:
            pass

    # ── Report ────────────────────────────────────────────────────────────────

    async def _build_report(
        self,
        run: ExecutionRun,
        scenario: Scenario,
        steps: list[dict],
        passed: bool,
    ) -> None:
        try:
            total    = len(steps)
            passed_n = sum(1 for s in steps if s.get("passed"))
            failed_n = total - passed_n
            quality_score = 100.0 if passed else round(100.0 * passed_n / max(total, 1), 1)

            timeline = [
                {
                    "seq":                  s["seq"],
                    "action":               s["action"],
                    "target":               s["target"],
                    "result":               s["result"][:150],
                    "duration_ms":          s["duration_ms"],
                    "passed":               s["passed"],
                    "phase":                s.get("phase", ""),
                    "checkpoint":           s.get("checkpoint", False),
                    "screenshot_path":      s.get("screenshot_path"),
                    "error_screenshot_path": s.get("error_screenshot_path"),
                }
                for s in steps
            ]

            # Evidence index: all screenshots grouped by type
            all_screenshots   = [s["screenshot_path"] for s in steps if s.get("screenshot_path")]
            failed_screenshots = [s["error_screenshot_path"] for s in steps
                                  if s.get("error_screenshot_path")]
            checkpoint_screenshots = [s["screenshot_path"] for s in steps
                                      if s.get("checkpoint") and s.get("screenshot_path")]

            # Root cause: first failed step
            first_failure = next((s for s in steps if not s["passed"]), None)
            rca = {}
            if first_failure:
                rca = {
                    "failed_step":    first_failure["seq"],
                    "action":         first_failure["action"],
                    "target":         first_failure["target"],
                    "error":          first_failure["result"],
                    "screenshot_path": first_failure.get("error_screenshot_path"),
                }

            report = ExecutionReport(
                id=str(_uuid_mod.uuid4()),
                run_id=run.id,
                risk_level=RiskLevel.LOW if passed else RiskLevel.HIGH,
                quality_score=quality_score,
                summary={
                    "total_steps":           total,
                    "passed_steps":          passed_n,
                    "failed_steps":          failed_n,
                    "outcome":               "PASSED" if passed else "FAILED",
                    "executor":              "plan_driven",
                    "video_path":            run.video_path,
                    "screenshot_count":      len(all_screenshots),
                    "failed_screenshot_count": len(failed_screenshots),
                },
                insights=[],
                rca_analysis=rca,
                recommendations=[],
                timeline=timeline,
            )
            self.db.add(report)
            await self.db.commit()
        except Exception as exc:
            log.warning("Report generation failed", run_id=run.id, error=str(exc))
