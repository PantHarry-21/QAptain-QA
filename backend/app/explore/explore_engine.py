"""
Agent Explore Engine — The Most Important Feature
QAptain onboards itself into an application like a senior QA engineer.

It LEARNS the application — it does NOT execute tests.

Process:
  Login → Discover Modules → Map Pages → Understand Forms & Tables →
  Identify Workflows → Build Knowledge Graph → Store Memory
"""
from __future__ import annotations
import asyncio
import json
import re
import time
import uuid
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete as sa_delete, update as sa_update

from app.db.models import (
    ExploreSession, ExploreLog, ExploreStatus, Application, Credential,
    ApplicationModule, ApplicationPage, ApplicationWorkflow, SemanticElement,
    KnowledgeGraph, HumanDecision, ExploreMode,
    Scenario, ScenarioPriority, AIMemoryChunk, MemoryKind,
    ExecutionRun,
)
from app.execution.browser_manager import BrowserManager
from app.execution.self_healing import SelfHealingEngine
from app.intelligence.semantic_extractor import SemanticUIExtractor
from app.intelligence.ai_client import get_ai_client
from app.core.security import decrypt_credential
from app.realtime.manager import connection_manager
from app.explore.token_manager import TokenBudget, RateLimitManager
from app.explore.page_analyzer_optimized import analyze_page_compact, FieldValidator, SYSTEM_PROMPT_EXPLORE_COMPACT
from config import settings

log = structlog.get_logger()

# Reduced token system prompt
SYSTEM_PROMPT_EXPLORE = SYSTEM_PROMPT_EXPLORE_COMPACT


def _is_valid_scenario_json(s: str) -> bool:
    """Return True if s is a parseable JSON object with at least a 'title' key."""
    try:
        d = json.loads(s)
        return isinstance(d, dict) and bool(d.get("title"))
    except Exception:
        return False


class ExploreEngine:
    """
    Semantic exploration engine that learns an application.
    Emits live semantic logs (not technical logs) throughout.
    """

    MAX_PAGES = 10000   # increased from 200 — explore all discovered pages

    def request_stop(self) -> None:
        """Request graceful stop of exploration. Checked during long operations."""
        self._should_stop = True
        log.info("Exploration stop requested", session_id=self._session_id)

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ai = get_ai_client()
        self._session_id: str | None = None
        self._app: Application | None = None
        self._browser: BrowserManager | None = None
        self._extractor: SemanticUIExtractor | None = None
        self._healer: SelfHealingEngine | None = None
        self._discovered_urls: set[str] = set()
        self._phase3_analyzed: set[str] = set()  # URLs analyzed in Phase 3 (dedup across click + URL paths)
        self._module_map: dict[str, str] = {}  # url_pattern -> module_id
        self._raw_nav_items: list[dict] = []  # nav items from Phase 2 {text, href}
        self._login_url: str = ""       # full URL of the login page (set in Phase 1)
        self._dashboard_url: str = ""  # full URL after successful login
        # Token and rate limit management
        self._token_budget = TokenBudget(soft_limit=500000)
        self._rate_limit = RateLimitManager(max_concurrent=2)
        self._field_validator: FieldValidator | None = None
        # Stop signal for graceful interruption
        self._should_stop = False

    async def run(self, session_id: str, application_id: str, discover_only: bool = False, module_ids: list[str] = None) -> None:
        """Main explore entry point — runs the full exploration lifecycle."""
        self._session_id = session_id

        # Load session and application
        session = await self._load_session(session_id)
        app = await self._load_application(application_id)

        if not session or not app:
            log.error("Session or application not found", session_id=session_id)
            return

        self._app = app

        # Update session status
        session.status = ExploreStatus.RUNNING
        session.started_at = datetime.utcnow()
        await self.db.commit()

        await self._log("MILESTONE", "system", "Starting application exploration")
        await self._emit_event("explore_started", {"session_id": session_id})

        try:
            # Check stop signal before starting
            if self._should_stop:
                await self._log("INFO", "system", "Stop requested before exploration started")
                session.status = ExploreStatus.STOPPED
                await self.db.commit()
                return

            # Launch browser and clean up previous data concurrently — both can proceed in parallel.
            await self._log("INFO", "system", "Launching browser…")
            try:
                browser_task = asyncio.create_task(
                    asyncio.wait_for(
                        asyncio.to_thread(BrowserManager.create, settings.SELENIUM_HEADLESS),
                        timeout=90.0,
                    )
                )
                # Full cleanup only for a brand-new full exploration (not discover_only or module re-run).
                # discover_only just rescans nav — existing explored data is preserved.
                # module re-runs clean up only the targeted modules just before exploring them.
                if not discover_only and not module_ids:
                    cleanup_task = asyncio.create_task(
                        self._cleanup_old_exploration_data(application_id)
                    )
                    self._browser, _ = await asyncio.gather(browser_task, cleanup_task)
                else:
                    self._browser = await browser_task
            except asyncio.TimeoutError:
                await self._fail_session(session,
                    "Browser failed to start within 90 seconds — "
                    "check Chrome / ChromeDriver installation and that no zombie Chrome processes are running")
                return
            await self._log("INFO", "system", "Browser ready")
            self._extractor = SemanticUIExtractor(self._browser.driver)
            self._healer = SelfHealingEngine(self._browser.driver)
            self._field_validator = FieldValidator(self._browser.driver)

            # Phase 1: Login
            login_ok = await self._phase_login(app)
            if not login_ok:
                await self._fail_session(session, "Login failed during exploration")
                return
            if self._should_stop:
                await self._log("INFO", "system", "Stop requested after login")
                session.status = ExploreStatus.STOPPED
                await self.db.commit()
                return

            if session.mode != ExploreMode.SKIP:
                if module_ids:
                    await self._explore_selected_modules(module_ids)
                else:
                    await self._hierarchical_explore(discover_only=discover_only)
                    
                if self._should_stop:
                    await self._log("INFO", "system", "Stop requested during exploration")
                    session.status = ExploreStatus.STOPPED
                    await self.db.commit()
                    return

            if discover_only:
                modules_count = await self._count_modules(application_id)
                session.status = ExploreStatus.WAITING_HUMAN
                session.modules_discovered = modules_count
                await self.db.commit()
                await self._log("MILESTONE", "system",
                    f"Discovery complete — {modules_count} module(s) found. Select which to explore deeply.")
                await self._emit_event("modules_discovered", {
                    "session_id": session_id,
                    "application_id": application_id,
                    "modules_count": modules_count,
                })

                # Keep browser alive and wait for the user to select modules.
                # The /explore/{session_id}/continue endpoint sets selected_module_ids on this session.
                selected_ids = await self._wait_for_module_selection(session_id, timeout=600)
                if not selected_ids:
                    await self._log("WARNING", "system",
                        "Module selection timed out or was cancelled — session ended")
                    return

                await self._log("MILESTONE", "system",
                    f"{len(selected_ids)} module(s) selected — starting deep exploration (already logged in)")
                session.status = ExploreStatus.RUNNING
                await self.db.commit()

                # Refresh only the selected modules' data — all other explored modules are preserved
                await self._cleanup_module_exploration_data(selected_ids, application_id)

                await self._explore_selected_modules(selected_ids)
                if self._should_stop:
                    return

                # Phase 4: Build knowledge graph
                kg = await self._phase_build_knowledge_graph(application_id, session_id)
                app.knowledge_graph_id = kg.id if kg else None
                await self.db.commit()

                # Phase 5: Generate test scenarios (KG-backed + AI)
                scenarios_count = await self._generate_test_scenarios(application_id, session_id, selected_ids)
                # Auto-link any unlinked scenarios to their module
                await self._auto_link_existing_scenarios(application_id)

                # Complete session
                modules_count = await self._count_modules(application_id)
                pages_count = await self._count_pages(application_id)
                workflows_count = await self._count_workflows(application_id)
                session.status = ExploreStatus.COMPLETED
                session.completed_at = datetime.utcnow()
                session.pages_discovered = pages_count
                session.modules_discovered = modules_count
                session.workflows_discovered = workflows_count
                session.summary = {
                    "modules": modules_count,
                    "pages": pages_count,
                    "workflows": workflows_count,
                    "scenarios_generated": scenarios_count,
                }
                await self.db.commit()
                await self._log("MILESTONE", "system",
                    f"Exploration complete — {modules_count} modules, {pages_count} pages, "
                    f"{workflows_count} workflows, {scenarios_count} scenarios generated")
                await self._emit_event("explore_completed", {
                    "session_id": session_id,
                    "modules": modules_count,
                    "pages": pages_count,
                    "workflows": workflows_count,
                    "scenarios_generated": scenarios_count,
                    "redirect_to": "scenarios",
                })
                return

            # Phase 4: Build knowledge graph
            kg = await self._phase_build_knowledge_graph(application_id, session_id)

            # Phase 5: Update application knowledge reference
            app.knowledge_graph_id = kg.id if kg else None
            await self.db.commit()

            # Phase 6: Generate test scenarios (KG-backed + AI)
            scenarios_count = await self._generate_test_scenarios(application_id, session_id, module_ids)
            # Auto-link any unlinked scenarios to their module
            await self._auto_link_existing_scenarios(application_id)

            # Complete session
            modules_count = await self._count_modules(application_id)
            pages_count = await self._count_pages(application_id)
            workflows_count = await self._count_workflows(application_id)

            session.status = ExploreStatus.COMPLETED
            session.completed_at = datetime.utcnow()
            session.pages_discovered = pages_count
            session.modules_discovered = modules_count
            session.workflows_discovered = workflows_count
            session.summary = {
                "modules": modules_count,
                "pages": pages_count,
                "workflows": workflows_count,
                "urls_visited": len(self._discovered_urls),
                "scenarios_generated": scenarios_count,
            }
            await self.db.commit()

            # Log final token usage
            final_budget = await self._token_budget.summary()
            await self._log("MILESTONE", "system",
                f"Exploration complete — {modules_count} modules, {pages_count} pages, "
                f"{workflows_count} workflows, {scenarios_count} scenarios generated")
            await self._log("INFO", "system",
                f"Token usage: {final_budget['spent']}/{final_budget['limit']} "
                f"({int(final_budget['spent']/final_budget['limit']*100)}%) | "
                f"API calls: {final_budget['api_calls']}")
            await self._emit_event("explore_completed", {
                "session_id": session_id,
                "modules": modules_count,
                "pages": pages_count,
                "workflows": workflows_count,
                "scenarios_generated": scenarios_count,
                "redirect_to": "scenarios",
                "tokens_spent": final_budget["spent"],
                "tokens_limit": final_budget["limit"],
            })

        except Exception as e:
            log.exception("Explore engine crashed", session_id=session_id, error=str(e))
            await self._fail_session(session, f"Exploration error: {str(e)[:300]}")
        finally:
            if self._browser:
                self._browser.quit()

    async def _phase_login(self, app: Application) -> bool:
        """Phase 1: Login to the application."""
        await self._log("INFO", "login", "Detecting login workflow")

        # Load credential
        cred_result = await self.db.execute(
            select(Credential).where(Credential.application_id == app.id).limit(1)
        )
        credential = cred_result.scalar_one_or_none()

        if not credential:
            await self._log("WARNING", "login", "No credentials configured — exploring public pages only")
            try:
                await asyncio.to_thread(self._browser.navigate, app.base_url)
            except Exception as nav_err:
                await self._log("WARNING", "login",
                    f"Navigation to {app.base_url} failed: {nav_err!s:.150}. Check the URL is reachable.")
                return False
            return True

        try:
            username = credential.username
            password = decrypt_credential(credential.password_encrypted)
        except Exception as e:
            await self._log("WARNING", "login", f"Could not decrypt credentials: {e}")
            return False

        # Navigate to app
        try:
            await asyncio.to_thread(self._browser.navigate, app.base_url)
        except Exception as nav_err:
            await self._log("WARNING", "login",
                f"Navigation to {app.base_url} timed out or failed: {nav_err!s:.150}. "
                "Check the URL is reachable and the server is running.")
            return False

        # Wait up to 90s for the page to render at least one input field.
        # Angular SPAs with heavy scripts can take time to bootstrap.
        # First wait for Angular to stabilise (up to 30s), then poll for inputs.
        # Poll in 15s chunks so the timeline shows live progress.
        await self._log("INFO", "login", "Waiting for login form to render…")
        page_ready = False
        for _chunk in range(6):
            page_ready = await asyncio.to_thread(self._wait_for_any_input, timeout=15)
            if page_ready:
                break
            elapsed = (_chunk + 1) * 15
            await self._log("INFO", "login", f"Still loading… {elapsed}s elapsed — waiting for login form")
        if not page_ready:
            await self._log("WARNING", "login",
                "No input fields appeared within 90 seconds — page may not be reachable or is still loading")
            # Recovery: the homepage may be a splash/landing page.
            # Try clicking a Login/Sign-In link, or navigate to common Angular login routes.
            recovered = await asyncio.to_thread(self._try_navigate_to_login_page, app.base_url)
            if recovered:
                await self._log("INFO", "login", "Found login form via navigation recovery — waiting 15s")
                page_ready = await asyncio.to_thread(self._wait_for_any_input, timeout=15)

        # Capture the actual login page URL (may differ from base_url due to redirects)
        self._login_url = await asyncio.to_thread(self._get_full_url)

        # Extract semantic state
        state = self._extractor.extract_page_state()
        current_url = await asyncio.to_thread(self._get_full_url)
        input_count = await asyncio.to_thread(self._count_page_inputs)
        await self._log("INFO", "login",
            f"Login page: {state.get('page', 'Unknown')} | URL: {current_url} | inputs found: {input_count}")

        # Fast login field detection: direct find_elements (instant, no per-strategy waits)
        # Handles: standard HTML, Angular Material, iframes, hidden-but-enabled inputs
        username_el, password_el = await asyncio.to_thread(self._find_login_fields_fast)

        await self._log("INFO", "login",
            f"Field scan: username={'found' if username_el else 'missing'}, "
            f"password={'found' if password_el else 'missing'}")

        # Two-step login: some apps show username first, then password after clicking Next
        if username_el is not None and password_el is None:
            await self._log("INFO", "login",
                "Only username field found — trying two-step login (enter username → Next → password)")
            two_step_ok = await self._try_two_step_login(username_el, username, password, state)
            if two_step_ok is not None:
                # two_step_ok is True (success), False (fail), or None (not two-step — fall through)
                return two_step_ok

        if username_el is None or password_el is None:
            await self._log("WARNING", "login",
                f"Login form fields missing ({input_count} total inputs on page) — attempting JS/keyboard login")
            return await self._ai_assisted_login(app.base_url, username, password, state)

        # Fill form
        try:
            await asyncio.to_thread(self._fill_login_field, username_el, username)
            await asyncio.to_thread(self._fill_login_field, password_el, password)
        except Exception as fill_err:
            await self._log("WARNING", "login",
                f"Field fill failed ({fill_err!s:.80}) — attempting JS/keyboard login")
            return await self._ai_assisted_login(app.base_url, username, password, state)

        await self._log("INFO", "login", "Credentials entered — submitting login form")

        # Click login button — try all common variants in one combined query
        LOGIN_BTN_LABELS = ["Sign In", "Sign in", "signin", "Log In", "Log in",
                            "Login", "login", "LOG IN", "SIGN IN", "Submit", "Continue", "Next"]
        login_button = self._healer.find_element_any(LOGIN_BTN_LABELS)

        if login_button[0]:
            self._healer.click_with_healing(login_button[0])
        else:
            await self._log("WARNING", "login", "Login button not found — pressing Enter")
            if password_el:
                try:
                    from selenium.webdriver.common.keys import Keys
                    password_el.send_keys(Keys.RETURN)
                except Exception:
                    await asyncio.to_thread(self._js_submit_login)

        await asyncio.sleep(2.5)

        # Detect post-login selector with retries — overlays often load asynchronously
        selector_info: dict = {"type": "unknown"}
        for attempt in range(4):
            selector_info = await asyncio.to_thread(self._inspect_dom_for_selectors)
            if selector_info.get("type") != "unknown":
                break
            if attempt < 3:
                await asyncio.sleep(2)  # wait for async overlay / redirect

        post_state = self._extractor.extract_page_state()
        current_url = post_state.get("url", "")
        has_selector = selector_info.get("type") not in ("unknown", None)

        if has_selector:
            await self._log("INFO", "login",
                f"Post-login step detected — {selector_info.get('label')!r} ({selector_info.get('type')})")
            await self._handle_login_context_selection(post_state)
            await asyncio.sleep(1.5)
        elif current_url != app.base_url:
            await self._log("SUCCESS", "login", "Login successful — navigated away from login page")
        else:
            await self._log("INFO", "login", "Login submitted — monitoring for redirect")
            await asyncio.sleep(2)

        # Record authenticated dashboard URL so Phase 2b/3 can detect login page redirects
        self._dashboard_url = await asyncio.to_thread(self._get_full_url)

        # Final sanity check: if still on login page, credentials were wrong or the form failed
        if await asyncio.to_thread(self._is_login_page):
            await self._log("WARNING", "login",
                "Still on login page after submission — credentials may be incorrect or MFA is required")
            return False

        await self._log("INFO", "login", f"Dashboard URL recorded: {self._dashboard_url}")
        return True

    async def _handle_login_context_selection(self, state: dict):
        """
        Robust post-login context selection handler.
        Priority order:
          1. Auto-select using app description (no user input needed)
          2. Show extracted options as buttons so user clicks the right one
          3. Show text input + screenshot as fallback
        """
        max_steps = 4

        for step in range(max_steps):
            # --- Step A: standard structure detection with retries ---
            selector_info: dict = {"type": "unknown"}
            for _ in range(3):
                selector_info = await asyncio.to_thread(self._inspect_dom_for_selectors)
                if selector_info.get("type") != "unknown":
                    break
                await asyncio.sleep(1.5)

            sel_type = selector_info.get("type", "unknown")
            label = selector_info.get("label", "Selection required")
            options = selector_info.get("options", [])

            await self._log("INFO", "login",
                f"Post-login step {step+1}: {sel_type!r} — {label!r} ({len(options)} option(s))")

            # --- Trigger button / dynamic dropdown ---
            if sel_type == "trigger_button":
                # Step 1: Use FieldInspector to enumerate all real options
                # (opens the dropdown, collects options, closes — no selection yet)
                fi_options = await self._get_options_via_field_inspector(label)
                if fi_options:
                    await self._log("INFO", "login",
                        f"FieldInspector found {len(fi_options)} option(s) for {label!r}")
                    await self._handle_smart_field_decision(label, fi_options)
                    return

                # FieldInspector found nothing — fall back to broad DOM extraction
                await self._log("INFO", "login",
                    f"FieldInspector found no options — clicking trigger for DOM extraction")
                before_items = await asyncio.to_thread(self._extract_all_visible_items)
                await asyncio.to_thread(self._click_trigger_button, label)
                await asyncio.sleep(8)
                await self._resolve_selection_from_page(label, before_items=before_items)
                return

            # --- Known selector with options (native select, radio, button_group, etc.) ---
            if sel_type not in ("unknown",) and options:
                # Try auto-select only when description clearly matches one option
                option_labels = [o["label"] if isinstance(o, dict) else str(o) for o in options]
                auto = self._match_description_to_items(option_labels)
                if auto:
                    await self._log("INFO", "login",
                        f"Auto-selecting '{auto}' based on application description")
                    clicked = await asyncio.to_thread(
                        self._click_dom_option, sel_type, auto, auto, selector_info
                    )
                    await asyncio.sleep(2)
                    if clicked:
                        await self._log("SUCCESS", "login", f"Auto-selected: {auto!r}")
                        await asyncio.to_thread(self._try_submit_after_selection)
                        return

                screenshot_url = await asyncio.to_thread(
                    self._take_screenshot, f"decision_{self._session_id}.png"
                )
                await self._handle_choice_decision(
                    label, options, sel_type, selector_info, screenshot_url=screenshot_url
                )
                await asyncio.sleep(2.5)
                continue  # check for next step

            # --- Unknown: broad extraction of everything visible on the page ---
            await self._resolve_selection_from_page(label)
            return

    async def _resolve_selection_from_page(
        self, label: str, before_items: list[str] | None = None
    ):
        """
        Broad DOM extraction + description auto-match + screenshot fallback.
        If before_items is provided, only items that are NEW (appeared after trigger click)
        are used — this prevents confusing page chrome with actual selectable options.
        """
        all_items = await asyncio.to_thread(self._extract_all_visible_items)
        await self._log("INFO", "login",
            f"Broad extraction found {len(all_items)} item(s): {all_items[:10]}")

        # Diff: only keep items that appeared after the trigger click
        if before_items:
            before_lower = {i.lower() for i in before_items}
            new_items = [i for i in all_items if i.lower() not in before_lower]
            await self._log("INFO", "login",
                f"New items after trigger click: {new_items}")
            if new_items:
                all_items = new_items
            else:
                # Nothing new in regular DOM — try Shadow DOM (Web Components)
                shadow_texts = await asyncio.to_thread(self._extract_shadow_dom_items)
                if shadow_texts:
                    await self._log("INFO", "login",
                        f"Found {len(shadow_texts)} item(s) in Shadow DOM: {shadow_texts[:5]}")
                    new_shadow = [t for t in shadow_texts if t.lower() not in before_lower]
                    all_items = new_shadow if new_shadow else shadow_texts
                else:
                    # Try iframes
                    iframe_texts = await asyncio.to_thread(self._extract_iframe_items)
                    if iframe_texts:
                        await self._log("INFO", "login",
                            f"Found {len(iframe_texts)} item(s) in iframe: {iframe_texts[:5]}")
                        all_items = iframe_texts
                    else:
                        # Nothing found anywhere — force text input so user can type the name
                        await self._log("WARNING", "login",
                            "Location list not found in DOM/Shadow/iframe — asking user to type")
                        all_items = []

        # Try to auto-select from app description
        if all_items:
            auto = self._match_description_to_items(all_items)
            if auto:
                await self._log("INFO", "login",
                    f"Auto-selecting '{auto}' based on application description")
                clicked = await asyncio.to_thread(
                    self._click_dom_option, "list", auto, auto, {}
                )
                await asyncio.sleep(2)
                if clicked:
                    await self._log("SUCCESS", "login", f"Location auto-selected: {auto!r}")
                    await asyncio.to_thread(self._try_submit_after_selection)
                    return

        # Take screenshot so user can see the current browser state
        screenshot_url = await asyncio.to_thread(
            self._take_screenshot, f"decision_{self._session_id}.png"
        )

        # Pass label in selector_info so _handle_choice_decision can re-open the trigger if needed
        trigger_meta = {"label": label}

        if all_items and len(all_items) <= 25:
            # Show only the NEW items as clickable buttons
            options = [{"label": t, "value": t} for t in all_items]
            await self._handle_choice_decision(
                label, options, "button_group", trigger_meta, screenshot_url=screenshot_url
            )
        else:
            # Nothing useful detected — ask user to type the location name
            await self._handle_text_input_decision(
                label, trigger_meta, screenshot_url=screenshot_url
            )

    # Common UI chrome that should never be treated as a selectable option
    _UI_NOISE: frozenset[str] = frozenset({
        "username", "password", "email", "login", "sign in", "signin", "log in",
        "remember me", "forgot password", "forgot your password", "reset password",
        "submit", "cancel", "close", "ok", "yes", "no", "back", "next", "previous",
        "save", "reset", "clear", "search", "filter", "sort", "loading", "loading...",
        "please wait", "home", "about", "contact", "help", "settings", "logout",
        "sign out", "register", "create account", "sign up", "continue", "proceed",
        "select", "choose", "pick", "enter", "type", "input",
    })

    # Prefixes that mark placeholder/instruction text — never a real option
    _PLACEHOLDER_PREFIXES: tuple[str, ...] = (
        "select ", "choose ", "pick ", "please select", "please choose",
        "-- select", "-- choose", "--- select", "search for", "type to search",
        "start typing", "enter ", "type ",
    )

    def _match_description_to_items(self, items: list[str]) -> str | None:
        """
        Match app description against visible items to auto-select.
        Skips common UI chrome words and placeholder-prefixed items.
        Prefers longer/more specific matches.
        """
        desc = (self._app.description or "").strip()
        if not desc or not items:
            return None
        desc_lower = desc.lower()

        def is_noise(text: str) -> bool:
            t = text.strip().lower()
            if t in self._UI_NOISE:
                return True
            # Filter placeholder-like options ("Select Location", "Choose Branch", etc.)
            return any(t.startswith(p) for p in self._PLACEHOLDER_PREFIXES)

        # Remove UI-noise and placeholder items before matching
        candidates = [
            i.strip() for i in items
            if i.strip() and not is_noise(i.strip())
        ]
        if not candidates:
            return None

        # Pass 1: longest exact substring match (item text fully contained in description)
        # Prefer longer matches so "Head Office" beats "Office"
        exact_matches = [c for c in candidates if c.lower() in desc_lower]
        if exact_matches:
            return max(exact_matches, key=len)

        # Pass 2: word overlap — each meaningful word in the item that appears in description
        # Require score proportional to item length to avoid single-word false positives
        desc_words = {w for w in desc_lower.split() if len(w) > 3}
        best: str | None = None
        best_score = 0.0
        for item in candidates:
            item_words = [w for w in item.lower().split() if len(w) > 3]
            if not item_words:
                continue
            overlap = sum(1 for w in item_words if w in desc_words)
            # ratio: what fraction of the item's words appear in description
            ratio = overlap / len(item_words)
            # weight by overlap count so multi-word matches score higher
            score = overlap * ratio
            if score > best_score:
                best_score = score
                best = item
        # Require both a ratio > 0.5 (most item words match) and at least 1 overlap word
        if best and best_score >= 0.5:
            return best
        return None

    def _extract_all_visible_items(self) -> list[str]:
        """
        Broad extraction of distinct visible text items — works regardless of DOM structure.
        Prefers modal/dialog containers so background elements don't pollute results.
        Does NOT require elements to be inside the viewport (handles off-screen lists too).
        """
        items = self._browser.execute_script("""
            const NOISE = new Set([
                'username','password','email','login','sign in','signin','log in',
                'remember me','forgot password','submit','cancel','close','ok',
                'yes','no','back','next','previous','save','reset','clear',
                'search','filter','sort','loading','loading...','please wait',
                'home','about','contact','help','settings','logout','sign out',
                'register','create account','sign up','continue','proceed',
                'select','choose','pick','enter','type','input'
            ]);

            // isRendered: element has non-zero dimensions AND is not hidden by CSS.
            // We deliberately do NOT check viewport bounds — location items in a
            // scrollable modal may sit below the fold.
            function isRendered(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && s.opacity !== '0';
            }
            const seen = new Set();
            const results = [];
            function addText(el) {
                const t = (el.textContent || '').trim().replace(/\\s+/g, ' ');
                if (t.length > 1 && t.length < 120 && !seen.has(t) && !NOISE.has(t.toLowerCase())) {
                    seen.add(t);
                    results.push(t);
                }
            }

            // ── Priority 0: look inside any rendered modal / dialog / dropdown ──
            const overlaySelectors = [
                '[role="dialog"]','[role="alertdialog"]','[role="listbox"]','[role="menu"]',
                '.modal','.Modal','.dialog','.Dialog','.popup','.Popup',
                '.overlay','.Overlay','.dropdown','.Dropdown',
                '[class*="modal" i]','[class*="dialog" i]','[class*="popup" i]',
                '[class*="dropdown" i]','[class*="select" i]','[class*="picker" i]',
                '[class*="menu" i]','[class*="list" i]','[class*="location" i]',
                '[class*="branch" i]','[class*="office" i]','[class*="facility" i]'
            ];
            let container = null;
            for (const sel of overlaySelectors) {
                try {
                    for (const el of document.querySelectorAll(sel)) {
                        if (isRendered(el) && el.querySelectorAll('*').length > 2) {
                            container = el; break;
                        }
                    }
                } catch(e) {}
                if (container) break;
            }

            const root = container || document;

            // Priority 1: semantic interactive / list elements
            for (const el of root.querySelectorAll(
                'button,[role="button"],[role="option"],[role="menuitem"],[role="listitem"],li,td,a'
            )) { if (isRendered(el)) addText(el); }

            // Priority 2: elements with click handlers or tabindex (leaf-ish)
            for (const el of root.querySelectorAll('[onclick],[tabindex]')) {
                if (isRendered(el) && el.children.length < 4) addText(el);
            }

            // Priority 3: leaf text elements
            if (results.length < 5) {
                for (const el of root.querySelectorAll('span,div,p,label')) {
                    if (!isRendered(el) || el.children.length > 0) continue;
                    addText(el);
                    if (results.length >= 40) break;
                }
            }

            // Priority 4 (nuclear): TreeWalker — every text node in the subtree,
            // regardless of CSS. Used when all other strategies find < 3 items.
            if (results.length < 3) {
                const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
                let node;
                while ((node = walker.nextNode()) && results.length < 50) {
                    const parent = node.parentElement;
                    if (!parent) continue;
                    const tag = parent.tagName;
                    if (['SCRIPT','STYLE','HEAD','META','NOSCRIPT'].includes(tag)) continue;
                    const t = (node.textContent || '').trim().replace(/\\s+/g, ' ');
                    if (t.length > 1 && t.length < 120 && !seen.has(t) && !NOISE.has(t.toLowerCase())) {
                        seen.add(t);
                        results.push(t);
                    }
                }
            }

            // Priority 5: Shadow DOM — recurse into any open shadow roots
            if (results.length < 5) {
                function extractShadow(el) {
                    if (el.shadowRoot) {
                        const sw = document.createTreeWalker(el.shadowRoot, NodeFilter.SHOW_TEXT, null);
                        let sn;
                        while ((sn = sw.nextNode()) && results.length < 60) {
                            const sp = sn.parentElement;
                            if (!sp || ['SCRIPT','STYLE'].includes(sp.tagName)) continue;
                            const t = (sn.textContent || '').trim().replace(/\\s+/g, ' ');
                            if (t.length > 1 && t.length < 120 && !seen.has(t) && !NOISE.has(t.toLowerCase())) {
                                seen.add(t); results.push(t);
                            }
                        }
                        for (const c of el.shadowRoot.querySelectorAll('*')) extractShadow(c);
                    }
                }
                for (const el of document.querySelectorAll('*')) extractShadow(el);
            }

            return results.slice(0, 40);
        """)
        return [s for s in (items or []) if s and s.strip()]

    def _extract_shadow_dom_items(self) -> list[str]:
        """Recursively traverse all Shadow DOM roots to find text items."""
        items = self._browser.execute_script("""
            const NOISE = new Set([
                'username','password','email','login','sign in','signin','log in',
                'remember me','forgot password','submit','cancel','close','ok',
                'yes','no','back','next','previous','save','reset','clear',
                'search','filter','sort','loading','loading...','please wait',
                'home','about','contact','help','settings','logout','sign out',
                'register','create account','sign up','continue','proceed',
                'select','choose','pick','enter','type','input'
            ]);
            const seen = new Set();
            const results = [];

            function extractFromRoot(root) {
                if (!root) return;
                // Walk all text nodes inside this shadow root
                const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
                let node;
                while ((node = walker.nextNode()) && results.length < 60) {
                    const parent = node.parentElement;
                    if (!parent || ['SCRIPT','STYLE','HEAD'].includes(parent.tagName)) continue;
                    const t = (node.textContent || '').trim().replace(/\\s+/g, ' ');
                    if (t.length > 1 && t.length < 120 && !seen.has(t) && !NOISE.has(t.toLowerCase())) {
                        seen.add(t); results.push(t);
                    }
                }
                // Recurse into nested shadow roots
                for (const el of root.querySelectorAll('*')) {
                    if (el.shadowRoot) extractFromRoot(el.shadowRoot);
                }
            }

            // Find all elements with a shadow root (open or accessible)
            for (const el of document.querySelectorAll('*')) {
                if (el.shadowRoot) extractFromRoot(el.shadowRoot);
            }
            return results.slice(0, 40);
        """)
        return [s for s in (items or []) if s and s.strip()]

    def _extract_iframe_items(self) -> list[str]:
        """Try to extract text from iframes on the page (for apps that render lists in iframes)."""
        from selenium.webdriver.common.by import By
        results: list[str] = []
        try:
            iframes = self._browser.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes[:3]:
                try:
                    self._browser.driver.switch_to.frame(iframe)
                    texts = self._browser.execute_script("""
                        const results = [], seen = new Set();
                        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
                        let node;
                        while ((node = walker.nextNode()) && results.length < 40) {
                            const parent = node.parentElement;
                            if (!parent || ['SCRIPT','STYLE'].includes(parent.tagName)) continue;
                            const t = (node.textContent || '').trim().replace(/\\s+/g, ' ');
                            if (t.length > 1 && t.length < 100 && !seen.has(t)) {
                                seen.add(t); results.push(t);
                            }
                        }
                        return results;
                    """)
                    results.extend(texts or [])
                except Exception:
                    pass
                finally:
                    self._browser.driver.switch_to.default_content()
        except Exception as e:
            log.debug("iframe extraction failed", error=str(e))
        return results[:30]

    def _take_screenshot(self, filename: str) -> str | None:
        """Take a browser screenshot and return its URL path."""
        import os
        from config import settings
        try:
            path = os.path.join(settings.SCREENSHOTS_DIR, filename)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if self._browser.driver.save_screenshot(path):
                return f"/artifacts/screenshots/{filename}"
        except Exception as e:
            log.warning("Screenshot failed", error=str(e))
        return None

    def _inspect_dom_for_selectors(self) -> dict:
        """
        Synchronous DOM scan for post-login selector patterns.
        Returns: {type, label, options: [{label, value}], ...}
        Only fires on interstitial pages — returns 'unknown' if we're already in the main app.
        """
        result = self._browser.execute_script("""
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0
                    && s.display !== 'none'
                    && s.visibility !== 'hidden'
                    && s.opacity !== '0';
            }
            function getText(el) {
                return (el.textContent || el.innerText || el.value || '').trim().replace(/\\s+/g, ' ');
            }

            // ── Main-app guard: if the page already has rich interactive content,
            //    we are inside the application — no post-login selector needed. ──
            const hasNav = !!document.querySelector(
                'nav,[role="navigation"],[role="menubar"],[role="tablist"],[role="toolbar"]'
            );
            const richItems = Array.from(document.querySelectorAll(
                'a[href],button,[role="menuitem"],[role="option"],li'
            )).filter(isVisible);
            if (hasNav || richItems.length >= 8) {
                return {type: 'unknown', label: 'Main app detected', options: []};
            }

            function getLabel(el) {
                if (el.id) {
                    const lbl = document.querySelector('label[for="' + el.id + '"]');
                    if (lbl) return getText(lbl);
                }
                const aria = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby');
                if (aria) return aria;
                if (el.placeholder) return el.placeholder;
                const fieldset = el.closest('fieldset');
                if (fieldset) {
                    const legend = fieldset.querySelector('legend');
                    if (legend) return getText(legend);
                }
                const parent = el.parentElement;
                if (parent) {
                    const prev = el.previousElementSibling;
                    if (prev && ['LABEL','H1','H2','H3','H4','SPAN','P'].includes(prev.tagName))
                        return getText(prev);
                }
                return '';
            }

            // 0. Trigger button — a single action button that reveals a deeper selector.
            //    Present on interstitial pages: no main nav yet, button text matches reveal keywords.
            const triggerKeywords = ['choose','select','pick','change','switch','set your','open'];
            const hasMainNav = !!document.querySelector('nav, [role="navigation"], [role="menubar"]');
            if (!hasMainNav) {
                const triggerBtns = Array.from(document.querySelectorAll(
                    'button, [role="button"], a'
                )).filter(isVisible).filter(el => {
                    const t = getText(el).toLowerCase();
                    return t.length > 0 && t.length < 80
                        && triggerKeywords.some(k => t.includes(k));
                });
                if (triggerBtns.length >= 1 && triggerBtns.length <= 5) {
                    return {
                        type: 'trigger_button',
                        label: getText(triggerBtns[0]),
                        options: [],
                    };
                }
            }

            // 1. Native <select>
            const selects = Array.from(document.querySelectorAll('select')).filter(isVisible);
            if (selects.length > 0) {
                const sel = selects[0];
                const opts = Array.from(sel.options)
                    .filter(o => o.text.trim() && o.value !== '' && o.index > 0)
                    .map(o => ({label: o.text.trim(), value: o.value}));
                return {
                    type: 'select',
                    label: getLabel(sel) || sel.getAttribute('name') || 'Select',
                    options: opts,
                    cssSelector: 'select' + (sel.id ? '#' + sel.id : sel.name ? '[name="' + sel.name + '"]' : ''),
                };
            }

            // 2. ARIA listbox / combobox / menu
            const ariaContainers = Array.from(document.querySelectorAll(
                '[role="listbox"],[role="menu"],[role="combobox"],[role="tree"]'
            )).filter(isVisible);
            for (const lb of ariaContainers) {
                const items = Array.from(lb.querySelectorAll(
                    '[role="option"],[role="menuitem"],[role="treeitem"],li'
                )).filter(isVisible).filter(el => getText(el).length > 0 && getText(el).length < 120);
                if (items.length >= 2) {
                    return {
                        type: 'list',
                        label: lb.getAttribute('aria-label') || getLabel(lb) || 'Select',
                        options: items.map(el => ({label: getText(el), value: getText(el)})),
                        containerRole: lb.getAttribute('role'),
                    };
                }
            }

            // 3. Radio button group
            const radios = Array.from(document.querySelectorAll('input[type="radio"]')).filter(isVisible);
            if (radios.length >= 2) {
                const opts = radios.map(r => {
                    const lbl = document.querySelector('label[for="' + r.id + '"]');
                    const text = lbl ? getText(lbl) : (r.value || r.id || '');
                    return {label: text, value: r.value || text};
                }).filter(o => o.label.length > 0);
                const fieldset = radios[0].closest('fieldset');
                return {
                    type: 'radio',
                    label: fieldset ? getText(fieldset.querySelector('legend')) || 'Select' : 'Select',
                    options: opts,
                };
            }

            // 4. Visible button group / list of clickable items (broad detection)
            const listSelectors = [
                'ul', 'ol', '[role="group"]', 'table tbody',
                '[class*="list"]', '[class*="grid"]', '[class*="options"]',
                '[class*="modal"] ul', '[class*="modal"] ol',
                '[class*="dialog"] ul', '[class*="dropdown"] ul',
                '[class*="popup"] ul', '[class*="panel"] ul',
            ];
            for (const sel of listSelectors) {
                const containers = Array.from(document.querySelectorAll(sel)).filter(isVisible);
                for (const c of containers) {
                    const items = Array.from(c.querySelectorAll(
                        'li, tr, button, [role="button"], [role="option"], [role="menuitem"], a, .item, .option'
                    )).filter(isVisible).filter(el => {
                        const t = getText(el);
                        return t.length > 0 && t.length < 150;
                    });
                    if (items.length >= 2 && items.length <= 50) {
                        return {
                            type: 'button_group',
                            label: c.getAttribute('aria-label') || getLabel(c) || 'Select',
                            options: items.map(el => ({label: getText(el), value: getText(el)})).slice(0, 20),
                        };
                    }
                }
            }

            // 4b. Any group of similarly-styled clickable elements (custom components)
            const allClickable = Array.from(document.querySelectorAll(
                'button:not([disabled]), [role="button"], [onclick], [tabindex="0"]'
            )).filter(isVisible).filter(el => {
                const t = getText(el);
                return t.length > 0 && t.length < 100;
            });
            // If there are 2-20 visible clickable elements and no nav, treat as a choice group
            if (allClickable.length >= 2 && allClickable.length <= 20 && !hasMainNav) {
                return {
                    type: 'button_group',
                    label: 'Select option',
                    options: allClickable.map(el => ({label: getText(el), value: getText(el)})),
                };
            }

            // 5. Visible text input (type-to-filter / search)
            const inputs = Array.from(document.querySelectorAll(
                'input[type="text"],input[type="search"],input:not([type])'
            )).filter(isVisible).filter(el => !el.readOnly && el.name !== 'username' && el.name !== 'email');
            if (inputs.length > 0) {
                const inp = inputs[0];
                return {
                    type: 'text_input',
                    label: getLabel(inp) || inp.placeholder || 'Enter value',
                    options: [],
                    cssSelector: inp.id ? '#' + inp.id : 'input',
                };
            }

            return {type: 'unknown', label: 'Selection required', options: []};
        """)
        return result or {"type": "unknown", "label": "Selection required", "options": []}

    async def _handle_smart_field_decision(
        self,
        field_label: str,
        fi_options: list[dict],
    ):
        """
        AI-native dynamic field selection flow — works for every application:

          1. Show the user the available options and a text input to type their choice
          2. Wait for user input (up to 300s)
          3. Fuzzy-match what the user typed/clicked against the known options
          4. Use FieldInspector.smart_select to re-open the dropdown and select the match
          5. Click any post-selection submit/continue button

        Supports both button-click (user picks from list) and
        text-input (user types freeform → we match semantically).
        Works for: Angular Material, React Select, MUI, ShadCN, portal dropdowns,
        virtualized lists, and any custom dropdown framework.
        """
        option_labels = [o["label"] for o in fi_options if isinstance(o, dict) and o.get("label")]
        screenshot_url = await asyncio.to_thread(
            self._take_screenshot, f"decision_{self._session_id}.png"
        )

        # Build the question with visible option hints
        options_preview = ", ".join(f'"{l}"' for l in option_labels[:10])
        if len(option_labels) > 10:
            options_preview += f" … (+{len(option_labels) - 10} more)"

        question = (
            f"The application requires you to select a '{field_label}' before continuing.\n"
            f"Available options ({len(option_labels)}): {options_preview}\n\n"
            f"Type the option you want to select, or click one of the buttons below."
        )

        # Build decision options:
        # • Button for each real option (up to 12 shown as buttons for quick click)
        # • Always include a text-input option so user can type if the list is long
        decision_options: list[dict] = []

        if len(option_labels) <= 12:
            # Show all as clickable buttons
            decision_options = [{"label": lbl, "value": lbl} for lbl in option_labels]
        else:
            # Too many to show as buttons — text input with option list in placeholder
            decision_options = [{
                "type": "text_input",
                "label": field_label,
                "placeholder": f"e.g. {option_labels[0]}" if option_labels else f"Type {field_label}...",
            }]

        decision = HumanDecision(
            session_id=self._session_id,
            question=question,
            context=(
                f"Select the {field_label} for this application. "
                "Your selection will be remembered for all future test runs."
            ),
            options=decision_options,
        )
        self.db.add(decision)
        await self.db.commit()

        event_payload: dict = {
            "session_id": self._session_id,
            "decision_id": decision.id,
            "question": decision.question,
            "options": decision.options,
        }
        if screenshot_url:
            event_payload["screenshot_url"] = screenshot_url
        await self._emit_event("human_decision_required", event_payload)
        await self._log("WARNING", "login",
            f"Waiting for user to select {field_label!r} — {len(option_labels)} option(s) available")

        decided = await self._wait_for_decision(decision.id, timeout=300)
        if not decided or not decided.selected_option:
            await self._log("WARNING", "login",
                f"No {field_label} selected — continuing from current page")
            return

        raw_value = (
            decided.selected_option.get("value")
            or decided.selected_option.get("label")
            or ""
        ).strip()

        if not raw_value:
            await self._log("WARNING", "login", "Empty selection received — skipping")
            return

        # Fuzzy-match the user's input against known options
        matched_label = self._fuzzy_match_option(raw_value, option_labels) or raw_value
        await self._log("INFO", "login",
            f"User selected: {raw_value!r} → matched to: {matched_label!r}")

        # Use FieldInspector smart_select — re-opens the dropdown and selects correctly
        ok = await self._select_via_field_inspector(field_label, matched_label)

        if not ok:
            # Fallback: try the raw value directly
            await self._log("INFO", "login",
                f"smart_select failed for {matched_label!r} — trying raw value {raw_value!r}")
            ok = await self._select_via_field_inspector(field_label, raw_value)

        if ok:
            await self._log("SUCCESS", "login", f"Selected {matched_label!r} via smart field interaction")
        else:
            await self._log("WARNING", "login",
                f"Could not select {matched_label!r} — trying JS click fallback")
            # Last resort: JS text click
            from app.intelligence.field_inspector import FieldInspector
            inspector = FieldInspector(self._browser.driver)
            ok = await asyncio.to_thread(inspector._js_click_by_text, matched_label.lower())
            if ok:
                await self._log("SUCCESS", "login", f"JS fallback selected: {matched_label!r}")

        await asyncio.sleep(1.5)
        await asyncio.to_thread(self._try_submit_after_selection)

    def _fuzzy_match_option(self, user_input: str, options: list[str]) -> str | None:
        """
        Match user's typed input against a list of known option labels.
        Pass 1: exact (case-insensitive)
        Pass 2: user_input contained in option or option contained in user_input
        Pass 3: word-overlap ≥ 50%
        Returns the best matching option label, or None.
        """
        target = user_input.lower().strip()
        if not target or not options:
            return None

        # Pass 1: exact
        for opt in options:
            if opt.lower().strip() == target:
                return opt

        # Pass 2: containment
        for opt in options:
            ol = opt.lower()
            if target in ol or ol in target:
                return opt

        # Pass 3: word overlap
        target_words = {w for w in target.split() if len(w) > 2}
        best: str | None = None
        best_score = 0.0
        for opt in options:
            opt_words = {w.lower() for w in opt.split() if len(w) > 2}
            if not opt_words:
                continue
            overlap = len(target_words & opt_words)
            ratio = overlap / len(opt_words)
            if ratio > best_score:
                best_score = ratio
                best = opt

        return best if best and best_score >= 0.5 else None

    async def _handle_choice_decision(
        self,
        label: str,
        options: list[dict],
        sel_type: str,
        selector_info: dict,
        screenshot_url: str | None = None,
    ):
        """Present extracted options as buttons and click the user's choice."""
        decision = HumanDecision(
            session_id=self._session_id,
            question=f"Please select the {label} for this application.",
            context=(
                f"The application shows a {sel_type.replace('_', ' ')} selector after login. "
                "The selected value will be saved as the default for all future test runs."
            ),
            options=[{"label": opt["label"], "value": opt["value"]} for opt in options[:20]],
        )
        self.db.add(decision)
        await self.db.commit()

        event_payload: dict = {
            "session_id": self._session_id,
            "decision_id": decision.id,
            "question": decision.question,
            "options": decision.options,
        }
        if screenshot_url:
            event_payload["screenshot_url"] = screenshot_url
        await self._emit_event("human_decision_required", event_payload)
        await self._log("WARNING", "login", f"Waiting for user to choose: {label}")

        decided = await self._wait_for_decision(decision.id, timeout=300)
        if not decided or not decided.selected_option:
            await self._log("WARNING", "login", "No selection made — continuing from current page")
            return

        chosen_label = decided.selected_option.get("label", "").strip()
        chosen_value = decided.selected_option.get("value", "").strip()
        await self._log("INFO", "login", f"User selected: {chosen_label!r}")

        # The modal/dropdown may have closed while waiting for the user. Re-open it if needed
        # by re-clicking the trigger button, then searching for the chosen item.
        clicked = await asyncio.to_thread(
            self._click_dom_option, sel_type, chosen_label, chosen_value, selector_info
        )
        if not clicked:
            # Trigger may have closed — re-click it and retry
            await self._log("INFO", "login", "Item not found — re-opening trigger and retrying")
            trigger_label = selector_info.get("label") or label
            await asyncio.to_thread(self._click_trigger_button, trigger_label)
            await asyncio.sleep(3)
            clicked = await asyncio.to_thread(
                self._click_dom_option, sel_type, chosen_label, chosen_value, selector_info
            )
        await asyncio.sleep(2)

        if clicked:
            await self._log("SUCCESS", "login", f"Activated '{chosen_label}' — proceeding")
            await asyncio.to_thread(self._try_submit_after_selection)
        else:
            await self._log("WARNING", "login",
                f"Could not activate '{chosen_label}' on page — continuing from current state")

    async def _handle_text_input_decision(self, label: str, selector_info: dict, screenshot_url: str | None = None):
        """Ask user to type a value when options can't be extracted from the DOM."""
        # Generate context-appropriate placeholder
        label_lower = label.lower()
        if any(k in label_lower for k in ("location", "branch", "office", "facility", "site", "store", "clinic")):
            placeholder = "e.g. Head Office, Main Branch, Lab 1"
        elif any(k in label_lower for k in ("department", "dept", "team", "unit", "division")):
            placeholder = "e.g. Finance, HR, Engineering"
        elif any(k in label_lower for k in ("company", "org", "organisation", "organization", "tenant", "client")):
            placeholder = "e.g. Acme Corp, Client A"
        elif any(k in label_lower for k in ("role", "user type", "usertype", "profile")):
            placeholder = "e.g. Admin, Manager, Operator"
        else:
            placeholder = f"Type the {label} value"

        screenshot_hint = " A screenshot of the browser is shown above — read the location name from there." if screenshot_url else ""
        decision = HumanDecision(
            session_id=self._session_id,
            question=f"The application requires a {label} selection after login. Please type your value.",
            context=(
                "The agent opened the location picker but could not read the options automatically "
                f"(they may use Shadow DOM or a canvas element).{screenshot_hint} "
                "Type the exact name and the agent will find and click the matching item on the page."
            ),
            options=[{
                "type": "text_input",
                "label": label,
                "placeholder": placeholder,
            }],
        )
        self.db.add(decision)
        await self.db.commit()

        text_event_payload: dict = {
            "session_id": self._session_id,
            "decision_id": decision.id,
            "question": decision.question,
            "options": decision.options,
        }
        if screenshot_url:
            text_event_payload["screenshot_url"] = screenshot_url
        await self._emit_event("human_decision_required", text_event_payload)
        await self._log("WARNING", "login", f"Waiting for user input: {label}")

        decided = await self._wait_for_decision(decision.id, timeout=300)
        if not decided or not decided.selected_option:
            await self._log("WARNING", "login", "No input provided — continuing from current page")
            return

        typed_value = decided.selected_option.get("value", "").strip()
        if not typed_value:
            return

        await self._log("INFO", "login", f"Received location input: {typed_value!r}")

        # Re-open the trigger if selector_info carries a trigger label
        trigger_label = selector_info.get("label")
        if trigger_label:
            await self._log("INFO", "login", f"Re-opening trigger: {trigger_label!r}")
            # Capture window handles before clicking — trigger may open a new window
            before_handles = await asyncio.to_thread(
                lambda: set(self._browser.driver.window_handles)
            )
            await asyncio.to_thread(self._click_trigger_button, trigger_label)
            await asyncio.sleep(4)
            # Switch to new window if one opened
            after_handles = await asyncio.to_thread(
                lambda: set(self._browser.driver.window_handles)
            )
            new_handles = after_handles - before_handles
            if new_handles:
                new_handle = next(iter(new_handles))
                await asyncio.to_thread(self._browser.driver.switch_to.window, new_handle)
                await self._log("INFO", "login", "Switched to new window opened by trigger")
                await asyncio.sleep(2)

        # Diagnostic: check if typed_value appears anywhere in page source
        in_source = await asyncio.to_thread(self._text_in_page_source, typed_value)
        await self._log("INFO", "login",
            f"Text '{typed_value}' {'FOUND' if in_source else 'NOT FOUND'} in page source")

        # Always try type-to-search: fill any visible input with the value and wait
        filled = await asyncio.to_thread(self._fill_any_visible_input, typed_value)
        if filled:
            await self._log("INFO", "login", "Typed into visible input — waiting for suggestions")
            await asyncio.sleep(2)

        await self._log("INFO", "login", f"Attempting to click: {typed_value!r}")
        clicked = await asyncio.to_thread(
            self._click_dom_option, "list", typed_value, typed_value, selector_info
        )

        if not clicked and filled:
            # Input was filled but click failed — try keyboard: Enter or first suggestion
            await self._log("INFO", "login", "Click failed after fill — trying keyboard Enter")
            clicked = await asyncio.to_thread(self._press_enter_on_focused_element)

        await asyncio.sleep(3)

        if clicked:
            await self._log("SUCCESS", "login", f"Selected '{typed_value}' — checking page state")
            await asyncio.sleep(2)
            await asyncio.to_thread(self._try_submit_after_selection)
        else:
            await self._log("WARNING", "login",
                f"All strategies failed for '{typed_value}'. "
                f"Text {'was' if in_source else 'was NOT'} in DOM source. "
                f"The picker may require manual interaction.")

    def _click_dom_option(
        self, sel_type: str, label: str, value: str, selector_info: dict
    ) -> bool:
        """
        Synchronous: click the correct DOM element for the user's choice.
        Strategy depends on the detected selector type.
        """
        from selenium.webdriver.common.by import By

        # Native <select> — most reliable
        if sel_type == "select":
            css = selector_info.get("cssSelector", "select")
            try:
                from selenium.webdriver.support.ui import Select as SeleniumSelect
                el = self._browser.driver.find_element(By.CSS_SELECTOR, css)
                sel = SeleniumSelect(el)
                try:
                    sel.select_by_visible_text(label)
                    return True
                except Exception:
                    try:
                        sel.select_by_value(value)
                        return True
                    except Exception:
                        pass
            except Exception:
                pass

        # Radio button
        if sel_type == "radio":
            try:
                radios = self._browser.driver.find_elements(By.CSS_SELECTOR, "input[type='radio']")
                for radio in radios:
                    lbl_el = None
                    try:
                        lbl_el = self._browser.driver.find_element(
                            By.CSS_SELECTOR, f"label[for='{radio.get_attribute('id')}']"
                        )
                    except Exception:
                        pass
                    lbl_text = (lbl_el.text if lbl_el else radio.get_attribute("value") or "").strip()
                    if lbl_text.lower() == label.lower() or radio.get_attribute("value") == value:
                        radio.click()
                        return True
            except Exception:
                pass

        # For all other types: JS-based search that pierces Shadow DOM
        clicked = self._browser.execute_script("""
            const target = arguments[0].toLowerCase().trim();
            const fallback = arguments[1].toLowerCase().trim();

            function isRendered(el) {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0
                    && s.display !== 'none' && s.visibility !== 'hidden';
            }
            function matchesText(el, exact) {
                const t = (el.textContent || '').trim().toLowerCase().replace(/\\s+/g, ' ');
                if (exact) return t === target || t === fallback;
                return t.includes(target) || t.includes(fallback);
            }

            const SEMANTIC = ['[role="option"]','[role="menuitem"]','[role="treeitem"]',
                              '[role="listitem"]','li','td','button','[role="button"]','a'];
            const BROAD = ['span','div','p','label'];

            // Search within a root (document or shadow root), recurse into nested shadows
            function searchRoot(root, exact) {
                // Semantic selectors first
                for (const css of SEMANTIC) {
                    try {
                        for (const el of root.querySelectorAll(css)) {
                            if (isRendered(el) && matchesText(el, exact)) {
                                el.click();
                                return (el.textContent || '').trim();
                            }
                        }
                    } catch(e) {}
                }
                // Broad selectors
                for (const css of BROAD) {
                    try {
                        for (const el of root.querySelectorAll(css)) {
                            if (isRendered(el) && matchesText(el, exact)) {
                                el.click();
                                return (el.textContent || '').trim();
                            }
                        }
                    } catch(e) {}
                }
                // Recurse into open shadow roots
                try {
                    for (const el of root.querySelectorAll('*')) {
                        if (el.shadowRoot) {
                            const found = searchRoot(el.shadowRoot, exact);
                            if (found) return found;
                        }
                    }
                } catch(e) {}
                return null;
            }

            // Try exact match first across all roots, then partial
            return searchRoot(document, true)
                || searchRoot(document, false)
                || null;
        """, label, value)

        if clicked:
            return True

        # Fallback 1: Selenium XPATH — finds text nodes that JS querySelectorAll misses
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.action_chains import ActionChains
        for text in (label, value):
            if not text:
                continue
            for xpath in (
                f"//*[normalize-space(text())='{text}']",
                f"//*[contains(normalize-space(text()),'{text}')]",
                f"//*[normalize-space(.)='{text}']",
            ):
                try:
                    els = self._browser.driver.find_elements(By.XPATH, xpath)
                    for el in els:
                        try:
                            if el.is_displayed():
                                el.click()
                                return True
                        except Exception:
                            try:
                                ActionChains(self._browser.driver).move_to_element(el).click().perform()
                                return True
                            except Exception:
                                pass
                except Exception:
                    pass

        # Fallback 2: JS dispatch full mouse event sequence (some React/Angular components
        # only respond to synthetic events, not native .click())
        dispatched = self._browser.execute_script("""
            const target = arguments[0].toLowerCase().trim();
            function fire(el) {
                ['mouseenter','mouseover','mousedown','mouseup','click'].forEach(type => {
                    el.dispatchEvent(new MouseEvent(type, {bubbles:true, cancelable:true, view:window}));
                });
                return true;
            }
            function search(root) {
                for (const el of root.querySelectorAll('*')) {
                    const t = (el.textContent || '').trim().toLowerCase().replace(/\\s+/g, ' ');
                    if (t === target || t.includes(target)) {
                        const r = el.getBoundingClientRect();
                        // Accept zero-dim elements too (virtual list off-screen items)
                        if (getComputedStyle(el).display !== 'none') {
                            return fire(el);
                        }
                    }
                    if (el.shadowRoot) { if (search(el.shadowRoot)) return true; }
                }
                return false;
            }
            return search(document);
        """, label)

        if dispatched:
            return True

        # Fallback 3: CDP accessibility tree + hardware mouse events
        # This is the only strategy that works for closed Shadow DOM and canvas-based UIs
        return self._click_via_cdp(label, value)

    def _click_via_cdp(self, label: str, value: str) -> bool:
        """
        Use CDP to locate an element by text in the accessibility tree (pierces closed Shadow DOM)
        and click it via hardware-level mouse events. Last resort for exotic UI frameworks.
        """
        try:
            tree = self._browser.driver.execute_cdp_cmd(
                "Accessibility.getFullAXTree", {"fetchRelatives": False}
            )
            nodes = tree.get("nodes", [])
            target_lower = label.lower().strip()
            fallback_lower = value.lower().strip()

            # Build search terms: full text + first significant word (for partial matches)
            first_word = target_lower.split()[0] if target_lower.split() else target_lower
            search_terms = {target_lower, fallback_lower, first_word}

            candidate_ids: list[int] = []
            for node in nodes:
                name_val = (node.get("name") or {}).get("value", "")
                desc_val = (node.get("description") or {}).get("value", "")
                combined = f"{name_val} {desc_val}".lower()
                if any(term in combined for term in search_terms if len(term) > 2):
                    bid = node.get("backendDOMNodeId")
                    if bid:
                        candidate_ids.append(int(bid))

            for backend_node_id in candidate_ids:
                try:
                    box_result = self._browser.driver.execute_cdp_cmd(
                        "DOM.getBoxModel", {"backendNodeId": backend_node_id}
                    )
                    model = box_result.get("model")
                    if not model:
                        continue
                    content = model.get("content", [])
                    if len(content) < 6:
                        continue
                    cx = (content[0] + content[2]) / 2
                    cy = (content[1] + content[5]) / 2
                    if cx <= 0 or cy <= 0:
                        continue
                    # Hardware-level mouse events via CDP
                    for ev in ("mouseMoved", "mousePressed", "mouseReleased"):
                        params: dict = {"type": ev, "x": cx, "y": cy, "modifiers": 0}
                        if ev != "mouseMoved":
                            params.update({"button": "left", "clickCount": 1})
                        self._browser.driver.execute_cdp_cmd("Input.dispatchMouseEvent", params)
                    log.debug("CDP click succeeded", text=label, cx=cx, cy=cy)
                    return True
                except Exception as e:
                    log.debug("CDP box model failed", backend_node_id=backend_node_id, error=str(e))
                    continue
        except Exception as e:
            log.debug("CDP click failed", error=str(e))
        return False

    def _click_trigger_button(self, label: str) -> bool:
        """Click a trigger/reveal button by matching its visible text."""
        clicked = self._browser.execute_script("""
            const target = arguments[0].toLowerCase();
            function isVisible(el) {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0
                    && getComputedStyle(el).display !== 'none';
            }
            const candidates = Array.from(document.querySelectorAll('button, [role="button"], a'))
                .filter(isVisible);
            for (const el of candidates) {
                const t = (el.textContent || '').trim().toLowerCase();
                if (t === target || t.includes(target) || target.includes(t)) {
                    el.click();
                    return true;
                }
            }
            return false;
        """, label.lower())
        return bool(clicked)

    def _text_in_page_source(self, text: str) -> bool:
        """Check if text appears anywhere in the current page HTML source."""
        try:
            return text.lower() in self._browser.driver.page_source.lower()
        except Exception:
            return False

    def _fill_any_visible_input(self, value: str) -> bool:
        """
        Fill any visible, enabled text/search input — broader than _fill_visible_input.
        Skips username/password/email fields. Returns True if any input was filled.
        """
        from selenium.webdriver.common.by import By
        skip_names = {"username", "password", "email", "user", "pass"}
        try:
            for inp in self._browser.driver.find_elements(
                By.CSS_SELECTOR,
                'input[type="text"],input[type="search"],input[type="tel"],'
                'input:not([type]),input[type=""]'
            ):
                try:
                    name = (inp.get_attribute("name") or "").lower()
                    typ = (inp.get_attribute("type") or "").lower()
                    if name in skip_names or typ == "password":
                        continue
                    if inp.is_displayed() and inp.is_enabled():
                        inp.clear()
                        inp.send_keys(value)
                        return True
                except Exception:
                    continue
        except Exception:
            pass
        return False

    def _press_enter_on_focused_element(self) -> bool:
        """Press Enter on whatever element currently has focus."""
        from selenium.webdriver.common.keys import Keys
        try:
            active = self._browser.driver.switch_to.active_element
            if active:
                active.send_keys(Keys.RETURN)
                return True
        except Exception:
            pass
        return False

    def _fill_visible_input(self, value: str) -> bool:
        """Fill the first visible, enabled text input (for type-to-filter patterns)."""
        from selenium.webdriver.common.by import By
        try:
            for inp in self._browser.driver.find_elements(
                By.CSS_SELECTOR, 'input[type="text"],input[type="search"],input:not([type])'
            ):
                if inp.is_displayed() and inp.is_enabled():
                    inp.clear()
                    inp.send_keys(value)
                    return True
        except Exception:
            pass
        return False

    def _try_submit_after_selection(self):
        """After context selection, look for a submit/continue button and click it."""
        # Fast path: JS search for button with any of these labels (instant, no timeout waits)
        button = self._browser.execute_script("""
            const labels = ["Submit", "Continue", "Proceed", "Sign In", "Login", "OK", "Confirm", "Next", "Go"];
            const buttons = Array.from(document.querySelectorAll('button, a[role="button"], input[type="submit"]'));
            for (const btn of buttons) {
                const text = btn.textContent.trim().toLowerCase();
                if (labels.some(l => text.includes(l.toLowerCase())) && btn.offsetHeight > 0) {
                    return btn;
                }
            }
            return null;
        """)

        if button:
            try:
                self._browser.execute_script("arguments[0].click();", button)
                return
            except Exception:
                pass

        # Fallback: healer with all variants in one combined query
        result = self._healer.find_element_any(
            ["Submit", "Continue", "Proceed", "Sign In", "Sign in", "Login",
             "Log In", "OK", "Confirm", "Next", "Go"]
        )
        if result[0]:
            try:
                result[0].click()
                return
            except Exception:
                pass

    # ─────────────────────────────────────────────────────────────────────────
    # Phase: Deep Element Scan
    # ─────────────────────────────────────────────────────────────────────────

    async def _phase_deep_scan_elements(self):
        """
        Phase 3b: For every page already saved in the DB, re-visit it and:
          1. Extract ALL interactive elements (buttons, inputs, links)
          2. Categorise each as add/edit/delete/submit/nav/form_field
          3. Click CRUD buttons, capture resulting dialog/form structure
          4. Save SemanticElement records so the executor can look up selectors

        OPTIMIZED: Skip if token budget is low, limit to 20 pages max.
        """
        # Check token budget before deep scan
        remaining = await self._token_budget.remaining()
        if remaining < 20000:
            await self._log("WARNING", "scan",
                f"Token budget low ({remaining} remaining) — skipping deep element scan")
            return

        await self._log("MILESTONE", "scan", "Deep-scanning pages for elements and selectors")

        # Query all pages saved so far for this application
        pages_result = await self.db.execute(
            select(ApplicationPage)
            .join(ApplicationModule, ApplicationPage.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == self._app.id)
        )
        pages = pages_result.scalars().all()

        if not pages:
            await self._log("WARNING", "scan", "No pages to deep-scan")
            return

        # Deep scan all discovered pages (budget checks in _deep_scan_page_elements prevent runaway)
        max_scan_pages = len(pages)
        await self._log("INFO", "scan", f"Deep-scanning {max_scan_pages}/{len(pages)} pages")

        for i, page in enumerate(pages):
            # Check stop signal
            if self._should_stop:
                await self._log("INFO", "scan", "Stop requested — halting element scan")
                return

            try:
                await self._log("INFO", "scan", f"Scanning [{i+1}/{len(pages)}] {page.title}")
                await asyncio.to_thread(self._browser.navigate, page.url)
                await asyncio.sleep(1.5)
                if await asyncio.to_thread(self._is_login_page):
                    # Try session recovery via dashboard before giving up
                    recovered = False
                    if self._dashboard_url:
                        try:
                            await asyncio.to_thread(self._browser.navigate, self._dashboard_url)
                            await asyncio.sleep(1.5)
                            if not await asyncio.to_thread(self._is_login_page):
                                await asyncio.to_thread(self._browser.navigate, page.url)
                                await asyncio.sleep(1.5)
                                recovered = not await asyncio.to_thread(self._is_login_page)
                        except Exception:
                            pass
                    if not recovered:
                        await self._log("WARNING", "scan", f"Login redirect — skipping: {page.url}")
                        continue
                await self._deep_scan_page_elements(page)
                await asyncio.sleep(0.3)
            except Exception as e:
                log.warning("Element scan failed", url=page.url, error=str(e))

        await self._log("SUCCESS", "scan", "Element scan complete — selectors stored in DB")

    async def _deep_scan_page_elements(self, page: ApplicationPage) -> list[dict]:
        """Extract and persist all interactive elements for one page. Returns enriched elements."""
        # Step 1: Scroll the page like a human to expose lazy-loaded content
        await asyncio.to_thread(self._human_step_scroll)

        # Step 2: Capture page state BEFORE clicking anything (empty state detection)
        initial_snapshot = await asyncio.to_thread(self._capture_current_state_snapshot)
        if initial_snapshot:
            page_data = page.page_data or {}
            page_data["initial_state"] = initial_snapshot
            page.page_data = page_data

        # Step 3: Extract all interactive elements via JS (after scroll so everything is loaded)
        raw_elements: list[dict] = await asyncio.to_thread(self._extract_page_elements_js)
        if not raw_elements:
            return []

        # Step 4: Test CRUD and generic action buttons: click → probe validation → complete roundtrip → close
        enriched: list[dict] = []
        tested_labels: set[str] = set()
        action_tested = 0  # limit generic "action" button testing to avoid excessive clicking
        add_roundtrip_done = False  # only do full roundtrip for the first add button per page
        for el in raw_elements:
            category = el.get("category", "")
            enriched_el = dict(el)
            label = el.get("label", "")

            should_test = (
                category in ("add", "edit", "delete") and el.get("selectors")
            ) or (
                category == "action" and el.get("selectors")
                and action_tested < 6
                and label not in tested_labels
            )

            if should_test and label not in tested_labels:
                tested_labels.add(label)
                if category == "action":
                    action_tested += 1
                # For "add" buttons: only do the full roundtrip for the first one per page
                do_roundtrip = (category == "add" and not add_roundtrip_done)
                dialog_data = await self._test_crud_operation(el, page.id, do_roundtrip=do_roundtrip)
                if dialog_data:
                    enriched_el["dialog"] = dialog_data
                    if dialog_data.get("fields"):
                        form_key = f"{category}_form"
                        enriched_el["dynamic_reveals"] = [{
                            "trigger": "click",
                            "type": form_key,
                            "title": dialog_data.get("title", ""),
                            "fields": dialog_data["fields"],
                            "submit_selector": dialog_data.get("submit_selector", ""),
                            "cancel_selector": dialog_data.get("cancel_selector", ""),
                            "validation_rules": dialog_data.get("validation_rules", {}),
                            "roundtrip": dialog_data.get("roundtrip"),
                        }]
                    if category == "add" and dialog_data.get("roundtrip"):
                        add_roundtrip_done = True

                    # Record structured workflow steps to KG so the planner can build
                    # exact-selector plans without AI for any explored module.
                    if page.module_id and category in ("add", "edit", "delete"):
                        try:
                            await self._record_workflow_to_kg(
                                page.module_id,
                                page.url or "",
                                el,
                                dialog_data,
                                category,
                            )
                        except Exception as _kg_err:
                            log.warning("KG workflow recording failed",
                                category=category, label=label,
                                error=str(_kg_err)[:120])

            enriched.append(enriched_el)

        # Update page.forms with any discovered dialog forms
        await self._merge_dialog_forms_into_page(page, enriched)

        # Persist SemanticElement records
        await self._save_semantic_elements(enriched, page.id)
        return enriched

    def _extract_page_elements_js(self) -> list[dict]:
        """
        JS extraction of all interactive elements on the current page.
        Returns a list of element descriptors with selectors, labels, types.
        """
        return self._browser.execute_script("""
        (function() {
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                if (r.width === 0 || r.height === 0 || s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
                const navSels = ['nav', '[role="navigation"]', 'aside', '[role="menubar"]', '[class*="sidebar" i]', '[class*="sider" i]', '[class*="menu-bar" i]'];
                if (el.closest(navSels.join(', '))) return false;
                return true;
            }
            function getSelectors(el) {
                const s = [];
                if (el.id && !/^\\d/.test(el.id) && el.id.length < 80) {
                    s.push({type:'css', value:'#'+el.id, confidence:0.95});
                }
                const tid = el.getAttribute('data-testid')||el.getAttribute('data-test-id')||el.getAttribute('data-cy');
                if (tid) s.push({type:'css', value:`[data-testid="${tid}"]`, confidence:0.92});
                const al = el.getAttribute('aria-label');
                if (al && al.length < 100) s.push({type:'css', value:`[aria-label="${al}"]`, confidence:0.88});
                const nm = el.getAttribute('name');
                if (nm && nm.length < 60 && !/^\\d/.test(nm)) {
                    s.push({type:'css', value:`${el.tagName.toLowerCase()}[name="${nm}"]`, confidence:0.82});
                }
                const txt = (el.textContent||el.value||'').trim().replace(/\\s+/g,' ').slice(0,60);
                if (txt && txt.length > 1 && txt.length < 60) {
                    s.push({type:'xpath', value:`//${el.tagName.toLowerCase()}[normalize-space(.)="${txt}"]`, confidence:0.7});
                }
                return s;
            }
            function categorize(text, tag) {
                const t = text.toLowerCase();
                if (/\\b(add|new|create|\\+)\\b/.test(t)) return 'add';
                if (/\\b(edit|update|modify|change)\\b/.test(t)) return 'edit';
                if (/\\b(delete|remove|trash|destroy)\\b/.test(t)) return 'delete';
                if (/\\b(save|submit|confirm|apply|done)\\b/.test(t)) return 'submit';
                if (/\\b(cancel|close|dismiss|back)\\b/.test(t)) return 'cancel';
                if (/\\b(search|find|filter|query)\\b/.test(t)) return 'search';
                if (tag === 'a') return 'navigation';
                return 'action';
            }

            const results = [];
            const seen = new Set();

            // ── Buttons, links, role=button ──────────────────────────────────
            for (const el of document.querySelectorAll(
                'button:not([disabled]),[role="button"],a[href],input[type="submit"],input[type="button"]'
            )) {
                if (!isVisible(el)) continue;
                const text = (el.textContent||el.value||el.getAttribute('aria-label')||'')
                    .trim().replace(/\\s+/g,' ');
                if (!text || text.length > 120) continue;
                const key = el.tagName + ':' + text.slice(0,40);
                if (seen.has(key)) continue;
                seen.add(key);
                const selectors = getSelectors(el);
                if (!selectors.length) continue;
                results.push({
                    tag: el.tagName.toLowerCase(),
                    type: 'button',
                    category: categorize(text, el.tagName.toLowerCase()),
                    label: text.slice(0,100),
                    role: el.getAttribute('role')||'',
                    href: el.getAttribute('href')||'',
                    selectors,
                });
            }

            // ── Form inputs ──────────────────────────────────────────────────
            for (const el of document.querySelectorAll(
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"]),'
                +'input:not([type="file"]),textarea,select'
            )) {
                if (!isVisible(el)) continue;
                const labelEl = el.id ? document.querySelector(`label[for="${el.id}"]`) : null;
                const label = (labelEl ? labelEl.textContent.trim() : '')
                    || el.getAttribute('placeholder') || el.getAttribute('aria-label')
                    || el.getAttribute('name') || '';
                if (!label) continue;
                const selectors = getSelectors(el);
                if (!selectors.length) continue;
                results.push({
                    tag: el.tagName.toLowerCase(),
                    type: el.tagName.toLowerCase() === 'select' ? 'dropdown' : 'input',
                    category: 'form_field',
                    label: label.trim().slice(0,100),
                    input_type: el.getAttribute('type')||'',
                    name: el.getAttribute('name')||'',
                    required: el.required || el.getAttribute('aria-required')==='true',
                    selectors,
                });
            }

            return results.slice(0, 120);
        })()
        """) or []

    async def _test_crud_operation(self, el_info: dict, page_id: str, do_roundtrip: bool = False) -> dict | None:
        """
        Click an add/edit/delete button, capture the resulting dialog/form.
        When do_roundtrip=True (first "add" button per page): also probe validation
        (submit empty) and complete a full fill+submit roundtrip.
        Otherwise just captures the form structure and closes the dialog.
        """
        from selenium.webdriver.common.by import By

        label = el_info.get("label", "")
        selectors = el_info.get("selectors", [])

        # Find element by stored selectors
        element = None
        for sel in selectors:
            try:
                by = By.CSS_SELECTOR if sel["type"] == "css" else By.XPATH
                el = self._browser.driver.find_element(by, sel["value"])
                if el.is_displayed():
                    element = el
                    break
            except Exception:
                continue

        if not element:
            # Fallback: find by exact text
            try:
                element = self._browser.driver.find_element(
                    By.XPATH,
                    f'//*[normalize-space(.)="{label}" or normalize-space(text())="{label}"]',
                )
            except Exception:
                return None

        if not element:
            return None

        before_url = self._browser.get_current_url()

        try:
            self._browser.execute_script(
                "arguments[0].scrollIntoView({block:'center'}); arguments[0].click()", element
            )
        except Exception:
            try:
                element.click()
            except Exception:
                return None

        await asyncio.sleep(1.5)

        dialog_info = await asyncio.to_thread(self._extract_dialog_or_form)
        if dialog_info:
            category = el_info.get("category", "")

            if do_roundtrip and category in ("add", "edit") and dialog_info.get("fields"):
                # Step 1: Probe validation contract — submit empty, capture required-field errors
                validation_errors = await asyncio.to_thread(self._probe_form_validation, dialog_info)
                if validation_errors:
                    dialog_info["validation_rules"] = validation_errors

                # Step 2: Complete-action roundtrip — fill with test data, submit, capture success
                if dialog_info.get("submit_selector"):
                    roundtrip = await asyncio.to_thread(self._complete_action_roundtrip, dialog_info)
                    dialog_info["roundtrip"] = roundtrip
                    current_url = self._browser.get_current_url()
                    if current_url != before_url:
                        try:
                            self._browser.driver.back()
                            await asyncio.sleep(1.0)
                        except Exception:
                            pass
                else:
                    await asyncio.to_thread(self._close_any_dialog)
                    await asyncio.sleep(0.5)
            else:
                # Just capture the form structure, then close
                await asyncio.to_thread(self._close_any_dialog)
                await asyncio.sleep(0.5)

            return dialog_info

        # Navigated to a new page?
        after_url = self._browser.get_current_url()
        if after_url != before_url:
            state = self._extractor.extract_page_state()
            forms = state.get("forms_detected", []) or []
            result = {"type": "navigation", "url": after_url, "fields": forms}
            try:
                self._browser.driver.back()
                await asyncio.sleep(1.0)
            except Exception:
                pass
            return result

        return None

    def _generate_field_test_value(self, field: dict) -> str:
        """Generate a realistic test value for an input field based on its label and type."""
        label = (field.get("label") or "").lower()
        f_type = (field.get("type") or "text").lower()
        opts = field.get("options", [])

        if opts:
            return opts[0]

        if f_type == "email":
            return f"qa_test_{int(time.time()) % 100000}@qatest.com"
        if f_type == "number":
            return "10"
        if f_type == "tel":
            return "+1-555-0100"
        if f_type == "date":
            return "2027-01-01"
        if f_type == "url":
            return "https://qatest.example.com"
        if f_type == "textarea":
            return f"QA automated test entry for {label}"

        if any(k in label for k in ("email",)):
            return f"qa_test_{int(time.time()) % 100000}@qatest.com"
        if any(k in label for k in ("phone", "mobile", "tel")):
            return "+1-555-0100"
        if any(k in label for k in ("price", "cost", "amount", "rate", "salary")):
            return "99.99"
        if any(k in label for k in ("date", "dob", "birthday", "expiry")):
            return "2027-01-01"
        if any(k in label for k in ("url", "website", "link")):
            return "https://qatest.example.com"
        if any(k in label for k in ("qty", "quantity", "count", "number", "no.", "age", "limit")):
            return "5"
        if any(k in label for k in ("zip", "postal", "pincode", "postcode")):
            return "10001"
        if any(k in label for k in ("address",)):
            return "123 QA Test Street, Suite 100"
        if any(k in label for k in ("city",)):
            return "QA City"
        if any(k in label for k in ("state", "province")):
            return "CA"
        if any(k in label for k in ("country",)):
            return "United States"
        if any(k in label for k in ("first", "fname")):
            return "QA"
        if any(k in label for k in ("last", "lname", "surname")):
            return "Tester"
        if any(k in label for k in ("company", "org", "organisation", "business")):
            return "QA Corp"
        if any(k in label for k in ("name", "title")):
            return f"QA Test {label.title()}"
        if any(k in label for k in ("desc", "note", "comment", "message", "detail", "reason")):
            return "Automated QA test entry - please ignore"
        if any(k in label for k in ("code", "id", "reference", "ref", "sku", "number")):
            return f"QA-{int(time.time()) % 100000}"
        if any(k in label for k in ("password", "passwd", "pass")):
            return "QA@Test#Secure1"

        return f"QA Test {label.title()}"[:50] if label else "QA Test Value"

    def _probe_form_validation(self, dialog_info: dict) -> dict:
        """
        Submit the currently-open dialog/form empty to discover validation rules.
        Captures per-field validation error messages without filling anything.
        Returns {field_label: [error_message, ...]} dict.
        """
        from selenium.webdriver.common.by import By

        submit_sel = dialog_info.get("submit_selector", "")
        btn = None

        if submit_sel:
            try:
                btn = self._browser.driver.find_element(By.CSS_SELECTOR, submit_sel)
                if not btn.is_displayed():
                    btn = None
            except Exception:
                pass

        if btn is None:
            for text in ("Save", "Submit", "Create", "Add", "OK", "Confirm", "Apply"):
                try:
                    b = self._browser.driver.find_element(
                        By.XPATH,
                        f'//button[contains(normalize-space(.), "{text}") and '
                        f'not(contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"cancel"))]',
                    )
                    if b.is_displayed():
                        btn = b
                        break
                except Exception:
                    pass

        if btn is None:
            return {}

        try:
            self._browser.execute_script("arguments[0].click()", btn)
            time.sleep(1.0)
        except Exception:
            return {}

        errors = self._browser.execute_script("""
        (function() {
            const result = {};
            const dialogs = document.querySelectorAll(
                '[role="dialog"],[aria-modal="true"],.modal.show,.modal.is-active,.MuiDialog-root'
            );
            const container = dialogs.length ? dialogs[0] : document.body;
            const ERROR_SELS = [
                '.mat-error', '.mat-form-field-hint', '.field-error', '.invalid-feedback',
                '[class*="error-message"]', '[class*="field-error"]', '[class*="validation-error"]',
                '[class*="form-error"]', '[class*="input-error"]',
                '[aria-live="polite"]', '[aria-live="assertive"]',
                'span[class*="error"]', 'p[class*="error"]', 'div[class*="error"]',
            ];
            for (const sel of ERROR_SELS) {
                try {
                    for (const el of container.querySelectorAll(sel)) {
                        const t = el.textContent.trim();
                        if (!t || t.length < 2 || t.length > 300) continue;
                        const r = el.getBoundingClientRect();
                        if (r.width === 0 || r.height === 0) continue;
                        // Find parent form group to identify which field this error belongs to
                        const group = el.closest(
                            '.mat-form-field, .form-group, .field-wrapper, [class*="form-field"], [class*="input-group"]'
                        );
                        let fieldLabel = 'general';
                        if (group) {
                            const lbl = group.querySelector(
                                'mat-label, label, [class*="label"], [class*="field-name"]'
                            );
                            if (lbl) fieldLabel = lbl.textContent.trim().slice(0, 80) || 'general';
                        }
                        if (!result[fieldLabel]) result[fieldLabel] = [];
                        if (!result[fieldLabel].includes(t)) result[fieldLabel].push(t);
                    }
                } catch(e) {}
            }
            return result;
        })()
        """) or {}

        return errors

    def _complete_action_roundtrip(self, dialog_info: dict) -> dict:
        """
        Fill the currently-open dialog form with realistic test data and submit it.
        Captures success indicators (toasts, URL changes, row count delta).
        Returns a structured result of what the UI did after submission.
        """
        from selenium.webdriver.common.by import By

        result = {
            "attempted": True,
            "submitted": False,
            "success_indicator": None,
            "error_on_submit": None,
            "navigation_url": None,
            "row_delta": 0,
            "filled_fields": [],
        }

        fields = dialog_info.get("fields", [])
        submit_sel = dialog_info.get("submit_selector", "")

        # Row count before
        try:
            rows_before = self._browser.execute_script("""
                return Math.max(
                    document.querySelectorAll('table tbody tr:not([style*="display: none"])').length,
                    document.querySelectorAll('[role="row"][aria-rowindex]').length, 0
                );
            """) or 0
        except Exception:
            rows_before = 0

        url_before = self._browser.get_current_url()

        # Fill fields
        for field in fields[:12]:
            label = field.get("label", "")
            f_type = (field.get("type") or "text").lower()
            selector = field.get("selector", "")
            name = field.get("name", "")
            if not (selector or name):
                continue

            value = self._generate_field_test_value(field)
            elem = None
            for locator in ([("css", selector)] if selector else []) + ([("css", f'[name="{name}"]')] if name else []):
                try:
                    by = By.CSS_SELECTOR if locator[0] == "css" else By.XPATH
                    e = self._browser.driver.find_element(by, locator[1])
                    if e.is_displayed():
                        elem = e
                        break
                except Exception:
                    pass

            if not elem:
                continue

            try:
                tag = elem.tag_name.lower()
                if tag == "select":
                    from selenium.webdriver.support.ui import Select as _Sel
                    opts = field.get("options", [])
                    if opts:
                        _Sel(elem).select_by_visible_text(opts[0])
                        result["filled_fields"].append({"field": label, "value": opts[0]})
                elif f_type in ("checkbox", "radio"):
                    if not elem.is_selected():
                        self._browser.execute_script("arguments[0].click()", elem)
                elif f_type == "date":
                    self._browser.execute_script(
                        "arguments[0].value = arguments[1];"
                        "arguments[0].dispatchEvent(new Event('input',{bubbles:true}));"
                        "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                        elem, value,
                    )
                    result["filled_fields"].append({"field": label, "value": value})
                else:
                    # React/Angular-aware input fill via native value setter
                    self._browser.execute_script("""
                        const inp = arguments[0]; const val = arguments[1];
                        const nativeSetter = Object.getOwnPropertyDescriptor(
                            inp.tagName === 'TEXTAREA'
                                ? window.HTMLTextAreaElement.prototype
                                : window.HTMLInputElement.prototype,
                            'value'
                        );
                        if (nativeSetter && nativeSetter.set) {
                            nativeSetter.set.call(inp, val);
                        } else {
                            inp.value = val;
                        }
                        inp.dispatchEvent(new Event('input',{bubbles:true}));
                        inp.dispatchEvent(new Event('change',{bubbles:true}));
                    """, elem, value)
                    result["filled_fields"].append({"field": label, "value": value})
                time.sleep(0.15)
            except Exception as e:
                log.debug("Field fill skipped during roundtrip", field=label, error=str(e)[:80])

        # Find and click submit button
        btn = None
        if submit_sel:
            try:
                btn = self._browser.driver.find_element(By.CSS_SELECTOR, submit_sel)
                if not btn.is_displayed():
                    btn = None
            except Exception:
                pass
        if btn is None:
            for text in ("Save", "Submit", "Create", "Add", "OK", "Confirm", "Apply"):
                try:
                    b = self._browser.driver.find_element(
                        By.XPATH,
                        f'//button[contains(normalize-space(.), "{text}") and '
                        f'not(contains(translate(@class,"ABCDEFGHIJKLMNOPQRSTUVWXYZ","abcdefghijklmnopqrstuvwxyz"),"cancel"))]',
                    )
                    if b.is_displayed():
                        btn = b
                        break
                except Exception:
                    pass

        if btn is None:
            result["error_on_submit"] = "Submit button not found after filling"
            self._close_any_dialog()
            return result

        try:
            self._browser.execute_script("arguments[0].click()", btn)
            result["submitted"] = True
        except Exception as e:
            result["error_on_submit"] = str(e)[:100]
            self._close_any_dialog()
            return result

        time.sleep(1.8)

        # Detect outcome
        url_after = self._browser.get_current_url()
        if url_after != url_before:
            result["navigation_url"] = url_after
            result["success_indicator"] = f"Navigated to {url_after} after submit"
            try:
                self._browser.driver.back()
                time.sleep(0.8)
            except Exception:
                pass
            return result

        # Check for visible toast/snackbar/alert
        toast = self._browser.execute_script("""
        (function() {
            const SELS = [
                '.mat-snack-bar-container', '[class*="toast"]', '[class*="snack-bar"]',
                '[class*="notification"]', '[role="status"]', '[role="alert"]',
                '[class*="alert-success"]', '[class*="success-message"]',
                '[class*="message"]:not(form *)',
            ];
            for (const sel of SELS) {
                try {
                    for (const el of document.querySelectorAll(sel)) {
                        const r = el.getBoundingClientRect();
                        const t = el.textContent.trim();
                        if (r.width > 0 && r.height > 0 && t.length > 3 && t.length < 300) return t;
                    }
                } catch(e) {}
            }
            return null;
        })()
        """)
        if toast:
            result["success_indicator"] = toast

        # Is dialog still open?
        still_open = self._browser.execute_script("""
            const d = document.querySelector('[role="dialog"],[aria-modal="true"],.MuiDialog-root');
            if (!d) return false;
            const r = d.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        """)

        if still_open:
            # Dialog still open = likely a validation error or server error
            err = self._browser.execute_script("""
                const d = document.querySelector('[role="dialog"],[aria-modal="true"],.MuiDialog-root');
                if (!d) return null;
                const e = d.querySelector('[class*="error"],[role="alert"],[class*="alert-danger"]');
                return e ? e.textContent.trim().slice(0,200) : null;
            """)
            result["error_on_submit"] = err or "Dialog remained open after submit"
            self._close_any_dialog()
        else:
            # Dialog closed = implicit success
            if not result["success_indicator"]:
                result["success_indicator"] = "Dialog closed after submit (success)"
            # Detect row count delta
            try:
                rows_after = self._browser.execute_script("""
                    return Math.max(
                        document.querySelectorAll('table tbody tr:not([style*="display: none"])').length,
                        document.querySelectorAll('[role="row"][aria-rowindex]').length, 0
                    );
                """) or 0
                result["row_delta"] = rows_after - rows_before
            except Exception:
                pass

        return result

    async def _record_workflow_to_kg(
        self,
        module_id: str,
        page_url: str,
        el_info: dict,
        dialog_info: dict,
        category: str,
    ) -> None:
        """
        Convert a recorded interaction (button click → form fill → submit → verify) into
        a structured ApplicationWorkflow with exact CSS selectors and stored in the KG.

        Called after every CRUD operation test during element scanning so the scenario
        planner can build precise, AI-free plans from real selectors instead of guessing.

        workflow_type mapping:
          add    → crud_create
          edit   → crud_update
          delete → crud_delete
        """
        from app.db.models import ApplicationWorkflow
        from sqlalchemy import delete as sa_delete

        workflow_type_map = {"add": "crud_create", "edit": "crud_update", "delete": "crud_delete"}
        workflow_type = workflow_type_map.get(category, category)

        def best_css(selectors: list) -> str:
            for s in (selectors or []):
                if s.get("type") == "css":
                    return s.get("value", "")
            for s in (selectors or []):
                if s.get("type") == "xpath":
                    return s.get("value", "")
            return ""

        button_label = el_info.get("label", "")
        button_selector = best_css(el_info.get("selectors", []))
        fields = dialog_info.get("fields", [])
        submit_selector = dialog_info.get("submit_selector", "")
        roundtrip = dialog_info.get("roundtrip") or {}
        filled_map = {f["field"]: f["value"] for f in roundtrip.get("filled_fields", [])}
        success_indicator = roundtrip.get("success_indicator", "")

        stages: list[dict] = []
        seq = 1

        # Always start: wait for list/table, then screenshot
        stages.append({
            "seq": seq, "action": "wait_element",
            "target": "table|tbody|mat-table|ag-grid|[class*=table]|[class*=list]|[class*=grid]",
            "description": "Wait for module list to load",
            "phase": "NAVIGATE", "on_fail": "skip", "timeout_ms": 15000,
        })
        seq += 1
        stages.append({
            "seq": seq, "action": "screenshot",
            "target": "", "description": "Capture initial module state", "phase": "NAVIGATE",
        })
        seq += 1

        if category == "delete":
            stages.append({
                "seq": seq, "action": "click",
                "target": button_selector or "Delete|Remove|trash icon",
                "description": f"Click {button_label}",
                "phase": "DELETE",
            })
            seq += 1
            stages.append({
                "seq": seq, "action": "assert_visible",
                "target": "confirm|are you sure|delete|yes",
                "description": "Verify delete confirmation dialog appeared",
                "phase": "DELETE", "on_fail": "skip", "timeout_ms": 8000,
            })
            seq += 1
            stages.append({
                "seq": seq, "action": "click",
                "target": submit_selector or "Confirm|Yes|Delete|OK",
                "description": "Confirm deletion",
                "phase": "DELETE",
            })
            seq += 1
            stages.append({
                "seq": seq, "action": "wait_network",
                "target": "", "description": "Wait for deletion to complete", "phase": "DELETE",
            })
            seq += 1
        else:
            # Open form/dialog
            stages.append({
                "seq": seq, "action": "click",
                "target": button_selector or button_label,
                "description": f"Click '{button_label}'",
                "phase": "FORM_OPEN",
            })
            seq += 1
            stages.append({
                "seq": seq, "action": "wait_element",
                "target": "[role='dialog']|.modal|dialog|.mat-dialog-container|.cdk-overlay-pane|form",
                "description": "Wait for form/dialog to appear",
                "phase": "FORM_OPEN", "timeout_ms": 10000,
            })
            seq += 1
            stages.append({
                "seq": seq, "action": "screenshot",
                "target": "", "description": "Capture form state", "phase": "FORM_OPEN",
            })
            seq += 1

            # Fill each field with its exact selector and observed test value
            for field in fields[:10]:
                field_sel = field.get("selector") or (
                    f'[name="{field["name"]}"]' if field.get("name") else ""
                )
                if not field_sel:
                    continue
                field_label = field.get("label", "")
                test_val = filled_map.get(field_label) or field.get("test_value", "")
                stages.append({
                    "seq": seq, "action": "fill",
                    "target": field_sel,
                    "value": test_val,
                    "description": f"Fill '{field_label}'",
                    "phase": "DATA_ENTRY",
                    "on_fail": "fail" if field.get("required") else "skip",
                })
                seq += 1

            stages.append({
                "seq": seq, "action": "wait_network",
                "target": "", "description": "Wait for async field validation",
                "phase": "DATA_ENTRY",
            })
            seq += 1
            stages.append({
                "seq": seq, "action": "screenshot",
                "target": "", "description": "Capture filled form", "phase": "DATA_ENTRY",
            })
            seq += 1

            # Submit
            stages.append({
                "seq": seq, "action": "click",
                "target": submit_selector or "button[type='submit']",
                "description": "Submit form",
                "phase": "SUBMIT",
            })
            seq += 1
            stages.append({
                "seq": seq, "action": "wait_network",
                "target": "", "description": "Wait for save to complete", "phase": "SUBMIT",
            })
            seq += 1

            # Assert success if we observed one during roundtrip
            if success_indicator:
                stages.append({
                    "seq": seq, "action": "assert_visible",
                    "target": success_indicator[:150],
                    "description": "Verify operation success indicator",
                    "phase": "VERIFY",
                    "on_fail": "skip", "timeout_ms": 10000, "checkpoint": True,
                })
                seq += 1

        stages.append({
            "seq": seq, "action": "screenshot",
            "target": "", "description": "Capture final state", "phase": "VERIFY",
        })

        # Replace any existing workflow of the same type for this module
        await self.db.execute(
            sa_delete(ApplicationWorkflow).where(
                ApplicationWorkflow.module_id == module_id,
                ApplicationWorkflow.workflow_type == workflow_type,
            )
        )
        wf = ApplicationWorkflow(
            module_id=module_id,
            name=f"{button_label}",
            description=f"Recorded during exploration: {button_label}",
            workflow_type=workflow_type,
            stages=stages,
            entry_point={
                "url": page_url or "",
                "trigger": "click",
                "selector": button_selector,
                "label": button_label,
            },
            success_indicators=[success_indicator] if success_indicator else [],
        )
        self.db.add(wf)
        await self.db.flush()

        log.info(
            "Workflow recorded to KG",
            module_id=module_id,
            workflow_type=workflow_type,
            button=button_label,
            stages=len(stages),
            has_roundtrip=bool(roundtrip.get("submitted")),
        )

    # ─────────────────────────────────────────────────────────────────────────
    # KG-backed scenario generation — runs without AI from recorded workflows
    # ─────────────────────────────────────────────────────────────────────────

    async def _generate_kg_scenarios(self, application_id: str) -> int:
        """
        Generate precise, KG-backed test scenarios for every module that has
        ApplicationWorkflow records from exploration.  These scenarios are linked
        to exact selectors — the planner builds their plans at Tier 0 with no AI.

        Idempotent: titles are de-duplicated so re-exploring a module doesn't
        create duplicate scenarios.
        """
        _TEMPLATES: dict[str, dict] = {
            "crud_create": {
                "title": "Create {module} — Happy Path",
                "description": (
                    "1. Navigate to the {module} module.\n"
                    "2. Click the Add / New button.\n"
                    "3. Fill all required fields with valid data.\n"
                    "4. Click Save / Submit.\n"
                    "5. Verify the new record appears in the list."
                ),
                "priority": ScenarioPriority.HIGH,
                "tags": ["kg_backed", "functional", "crud", "create", "happy_path"],
            },
            "crud_update": {
                "title": "Edit {module} — Update Existing Record",
                "description": (
                    "1. Navigate to the {module} module.\n"
                    "2. Select an existing record.\n"
                    "3. Click the Edit button.\n"
                    "4. Modify one or more fields with new valid values.\n"
                    "5. Click Save.\n"
                    "6. Verify the record reflects the updated values in the list."
                ),
                "priority": ScenarioPriority.HIGH,
                "tags": ["kg_backed", "functional", "crud", "update", "happy_path"],
            },
            "crud_delete": {
                "title": "Delete {module} — Remove Record",
                "description": (
                    "1. Navigate to the {module} module.\n"
                    "2. Select a record to delete.\n"
                    "3. Click the Delete button.\n"
                    "4. Confirm the deletion in the confirmation dialog.\n"
                    "5. Verify the record is no longer present in the list."
                ),
                "priority": ScenarioPriority.MEDIUM,
                "tags": ["kg_backed", "functional", "crud", "delete"],
            },
        }

        # Load modules for this application
        mods_result = await self.db.execute(
            select(ApplicationModule).where(
                ApplicationModule.application_id == application_id
            )
        )
        modules = list(mods_result.scalars().all())
        if not modules:
            return 0

        module_ids = [m.id for m in modules]

        # Load recorded KG workflows
        wf_result = await self.db.execute(
            select(ApplicationWorkflow).where(
                ApplicationWorkflow.module_id.in_(module_ids)
            )
        )
        kg_workflows = list(wf_result.scalars().all())
        if not kg_workflows:
            return 0

        # Index by module
        wf_by_module: dict[str, list[str]] = {}
        for wf in kg_workflows:
            wf_by_module.setdefault(wf.module_id, []).append(wf.workflow_type)

        # Load existing kg_generated titles to avoid duplicates
        existing_result = await self.db.execute(
            select(Scenario.title).where(
                Scenario.application_id == application_id,
                Scenario.source == "kg_generated",
            )
        )
        existing_titles: set[str] = {t for (t,) in existing_result.all()}

        count = 0
        mod_by_id = {m.id: m for m in modules}

        for module_id_key, wf_types in wf_by_module.items():
            mod = mod_by_id.get(module_id_key)
            if not mod:
                continue
            module_name = mod.name

            # One happy-path scenario per recorded workflow type
            for wf_type in wf_types:
                tmpl = _TEMPLATES.get(wf_type)
                if not tmpl:
                    continue
                title = tmpl["title"].format(module=module_name)
                if title in existing_titles:
                    continue
                self.db.add(Scenario(
                    application_id=application_id,
                    title=title,
                    description=tmpl["description"].format(module=module_name),
                    priority=tmpl["priority"],
                    tags=list(tmpl["tags"]),
                    module_id=module_id_key,
                    source="kg_generated",
                    is_active=True,
                ))
                existing_titles.add(title)
                count += 1

            # End-to-end CRUD scenario when all three operations are recorded
            has_all_crud = all(
                t in wf_types for t in ("crud_create", "crud_update", "crud_delete")
            )
            if has_all_crud:
                e2e_title = f"Full CRUD — {module_name} End-to-End"
                if e2e_title not in existing_titles:
                    self.db.add(Scenario(
                        application_id=application_id,
                        title=e2e_title,
                        description=(
                            f"1. Navigate to the {module_name} module.\n"
                            f"2. Create a new {module_name} record with valid data — verify it appears in the list.\n"
                            f"3. Edit the created record with updated values — verify changes are saved.\n"
                            f"4. Delete the record — verify it is removed from the list.\n"
                            f"5. Confirm no data leakage or state bleed between operations."
                        ),
                        priority=ScenarioPriority.CRITICAL,
                        tags=["kg_backed", "functional", "crud", "end_to_end", "regression"],
                        module_id=module_id_key,
                        source="kg_generated",
                        is_active=True,
                    ))
                    existing_titles.add(e2e_title)
                    count += 1

        if count:
            await self.db.commit()
            await self._log(
                "SUCCESS", "scenarios",
                f"{count} KG-backed scenario(s) auto-generated from exploration "
                f"(exact selectors recorded — no AI needed for execution)",
            )
        return count

    async def _auto_link_existing_scenarios(self, application_id: str) -> int:
        """
        Scan all unlinked scenarios for this application and assign module_id
        based on title/description keyword overlap with module names.
        Runs after exploration so newly-discovered modules are matched.
        """
        unlinked_result = await self.db.execute(
            select(Scenario).where(
                Scenario.application_id == application_id,
                Scenario.module_id.is_(None),
            )
        )
        unlinked = list(unlinked_result.scalars().all())
        if not unlinked:
            return 0

        mods_result = await self.db.execute(
            select(ApplicationModule).where(
                ApplicationModule.application_id == application_id
            )
        )
        modules = list(mods_result.scalars().all())
        if not modules:
            return 0

        def _match_score(text: str, module_name: str) -> float:
            tl, nl = text.lower(), module_name.lower()
            if nl in tl:
                return 1.0
            name_words = set(re.findall(r"\w+", nl))
            text_words = set(re.findall(r"\w+", tl))
            if not name_words:
                return 0.0
            return len(name_words & text_words) / len(name_words)

        count = 0
        for scenario in unlinked:
            search_text = (scenario.title or "") + " " + (scenario.description or "")[:200]
            best_mod = None
            best_score = 0.4
            for mod in modules:
                score = _match_score(search_text, mod.name)
                if score > best_score:
                    best_score = score
                    best_mod = mod
            if best_mod:
                scenario.module_id = best_mod.id
                count += 1

        if count:
            await self.db.commit()
            await self._log(
                "INFO", "scenarios",
                f"Auto-linked {count} unlinked scenario(s) to their matching module",
            )
        return count

    def _capture_current_state_snapshot(self) -> dict:
        """Lightweight snapshot of the current page list state — rows, empty message, URL."""
        return self._browser.execute_script("""
        (function() {
            const rowCount = Math.max(
                document.querySelectorAll('table tbody tr:not([style*="display:none"]):not([style*="display: none"])').length,
                document.querySelectorAll('[role="row"][aria-rowindex]').length,
                document.querySelectorAll('[class*="list-item"],[class*="card-item"]').length,
                0
            );
            let emptyMsg = null;
            for (const sel of [
                '[class*="empty-state"]','[class*="no-data"]','[class*="no-records"]',
                '[class*="no-results"]','[class*="empty-placeholder"]',
                '[class*="empty"]:not(button):not(input)',
            ]) {
                try {
                    for (const el of document.querySelectorAll(sel)) {
                        const r = el.getBoundingClientRect();
                        const t = el.textContent.trim();
                        if (r.width > 0 && r.height > 0 && t.length > 3 && t.length < 300) {
                            emptyMsg = t; break;
                        }
                    }
                } catch(e) {}
                if (emptyMsg) break;
            }
            return {row_count: rowCount, is_empty: rowCount === 0, empty_message: emptyMsg};
        })()
        """) or {"row_count": 0, "is_empty": True, "empty_message": None}

    def _extract_dialog_or_form(self) -> dict | None:
        """Detect and extract the structure of any dialog/modal open on the page."""
        return self._browser.execute_script("""
        (function() {
            function isVisible(el) {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            }
            const DIALOG_SELS = [
                '[role="dialog"]','[role="alertdialog"]',
                '.modal.show','.modal.is-active','[class*="modal-open"]',
                '.MuiDialog-root','.ant-modal',
                '[data-modal="true"]','[aria-modal="true"]',
                '[class*="dialog"]:not(head):not(script)',
            ];
            let dialog = null;
            for (const sel of DIALOG_SELS) {
                try {
                    for (const el of document.querySelectorAll(sel)) {
                        if (isVisible(el) && el.querySelectorAll('*').length > 3) {
                            dialog = el; break;
                        }
                    }
                } catch(e) {}
                if (dialog) break;
            }
            if (!dialog) return null;

            function getBestSelector(el) {
                const tid = el.getAttribute('data-testid')||el.getAttribute('data-test')||el.getAttribute('data-cy');
                if (tid) return '[data-testid="'+tid+'"]';
                if (el.id && !/^\d/.test(el.id) && el.id.length < 80) return '#'+el.id;
                const al = el.getAttribute('aria-label');
                if (al && al.length < 80) return '[aria-label="'+al+'"]';
                const nm = el.getAttribute('name');
                if (nm && nm.length < 60) return el.tagName.toLowerCase()+'[name="'+nm+'"]';
                return '';
            }

            const fields = [];
            for (const inp of dialog.querySelectorAll(
                'input:not([type="hidden"]):not([type="submit"]):not([type="button"]),textarea,select'
            )) {
                if (!isVisible(inp)) continue;
                const lel = inp.id ? document.querySelector(`label[for="${inp.id}"]`) : null;
                const label = (lel ? lel.textContent.trim() : '')
                    || inp.getAttribute('placeholder') || inp.getAttribute('aria-label')
                    || inp.getAttribute('name') || '';
                if (!label) continue;
                const isSelect = inp.tagName.toLowerCase() === 'select';
                const opts = [];
                if (isSelect) {
                    for (const o of inp.options) {
                        if (!o.disabled && o.value !== '' && o.text.trim() !== '') {
                            opts.push(o.text.trim());
                        }
                    }
                }
                fields.push({
                    label: label.slice(0,100),
                    type: isSelect ? 'dropdown' : (inp.getAttribute('type')||'text'),
                    name: inp.getAttribute('name')||'',
                    required: inp.required || inp.getAttribute('aria-required')==='true',
                    selector: getBestSelector(inp),
                    options: opts.slice(0, 20),
                });
            }

            // Capture submit and cancel selectors from the dialog
            let submit_selector = '', cancel_selector = '';
            for (const btn of dialog.querySelectorAll('button,[role="button"],input[type="submit"]')) {
                if (!isVisible(btn)) continue;
                const t = (btn.textContent||btn.value||btn.getAttribute('aria-label')||'').trim().toLowerCase();
                if (!submit_selector && /^(save|submit|create|add|confirm|ok|done|apply)/.test(t))
                    submit_selector = getBestSelector(btn) || ('button:contains("'+btn.textContent.trim().slice(0,30)+'")');
                if (!cancel_selector && /^(cancel|close|dismiss|back|no)/.test(t))
                    cancel_selector = getBestSelector(btn) || ('button:contains("'+btn.textContent.trim().slice(0,30)+'")');
            }

            const titleEl = dialog.querySelector(
                'h1,h2,h3,h4,[class*="title"],[class*="header"] h1,[class*="header"] h2'
            );
            const title = titleEl ? titleEl.textContent.trim().slice(0,120) : 'Dialog';
            return {type:'dialog', title, fields, submit_selector, cancel_selector};
        })()
        """)

    def _close_any_dialog(self):
        """Close any open dialog/modal via close-button or Escape."""
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.common.action_chains import ActionChains

        for sel in (
            'button[aria-label="Close"]', 'button[aria-label="close"]',
            'button.close', '.btn-close', '[data-dismiss="modal"]',
            'button[class*="close"]', 'button[class*="Cancel"]',
            'button[class*="cancel"]',
        ):
            try:
                for btn in self._browser.driver.find_elements(By.CSS_SELECTOR, sel):
                    if btn.is_displayed():
                        self._browser.execute_script("arguments[0].click()", btn)
                        time.sleep(0.4)
                        return
            except Exception:
                pass
        try:
            ActionChains(self._browser.driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.3)
        except Exception:
            pass

    async def _explore_table_rows(self, page: ApplicationPage) -> list[dict]:
        """
        Click the first data row in every visible table to discover whether rows are interactive
        (open a detail/edit view, an inline dialog, or nothing).
        When a row click does nothing, scroll the table right to look for hidden action columns.
        Returns a list of discovered interactions.
        """
        discoveries: list[dict] = []
        page_url = page.url or ""

        row_info = await asyncio.to_thread(self._browser.execute_script, """
        (function() {
            function isVisible(el) {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
            }
            const ROW_SELS = [
                'table tbody tr',
                '[role="grid"] [role="row"]',
                '[role="rowgroup"] [role="row"]',
                '.mat-row', '.ant-table-row', '.ag-row'
            ];
            for (const sel of ROW_SELS) {
                try {
                    const rows = document.querySelectorAll(sel);
                    for (const row of rows) {
                        if (!isVisible(row)) continue;
                        const cells = row.querySelectorAll('td, [role="cell"], [role="gridcell"]');
                        if (cells.length < 2) continue;
                        const firstText = (cells[0].textContent || '').trim().slice(0, 60);
                        return {found: true, row_sel: sel, first_cell_text: firstText};
                    }
                } catch(e) {}
            }
            return {found: false};
        })()
        """) or {}

        if not row_info.get("found"):
            return discoveries

        row_sel = row_info.get("row_sel", "table tbody tr")
        first_cell_text = row_info.get("first_cell_text", "row")
        before_url = self._browser.get_current_url()

        # Click first cell of first row
        clicked = await asyncio.to_thread(self._browser.execute_script, f"""
        (function() {{
            const rows = document.querySelectorAll('{row_sel}');
            for (const row of rows) {{
                const r = row.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                const cell = row.querySelector('td, [role="cell"], [role="gridcell"]');
                if (cell) {{ cell.click(); return true; }}
                row.click(); return true;
            }}
            return false;
        }})()
        """)

        if not clicked:
            return discoveries

        await asyncio.sleep(1.5)
        after_url = self._browser.get_current_url()

        if after_url != before_url:
            await self._log("INFO", "exploration", f"Table row click → navigated to detail: {after_url}")
            discoveries.append({
                "type": "row_opens_detail",
                "detail_url": after_url,
                "description": f"Clicking a table row navigates to a detail/edit page ({after_url})",
            })
            try:
                self._browser.driver.back()
                await asyncio.sleep(1.5)
            except Exception:
                await asyncio.to_thread(self._browser.navigate, page_url)
                await asyncio.sleep(2.0)
        else:
            dialog_info = await asyncio.to_thread(self._extract_dialog_or_form)
            if dialog_info and dialog_info.get("fields"):
                await self._log("INFO", "exploration",
                    f"Table row click → dialog: '{dialog_info.get('title', 'Form')}'")
                discoveries.append({
                    "type": "row_opens_dialog",
                    "dialog": dialog_info,
                    "description": f"Clicking a table row opens '{dialog_info.get('title', 'a form')}'",
                })
                await asyncio.to_thread(self._close_any_dialog)
                await asyncio.sleep(0.5)
            else:
                # Nothing visible happened — try horizontal scroll to find action buttons
                await self._log("INFO", "exploration",
                    "Row click had no visible effect — scrolling table right to find action buttons")
                row_actions = await self._discover_row_actions_via_scroll(page_url)
                discoveries.extend(row_actions)

        return discoveries

    async def _discover_row_actions_via_scroll(self, page_url: str) -> list[dict]:
        """Scroll the table container right to reveal hidden action columns, then click each action button."""
        discoveries: list[dict] = []

        # Scroll every overflow table container right
        await asyncio.to_thread(self._browser.execute_script, """
        (function() {
            const candidates = document.querySelectorAll(
                'table, [role="grid"], [class*="table"], [class*="datagrid"], .mat-table'
            );
            for (const el of candidates) {
                let p = el.parentElement;
                while (p && p !== document.body) {
                    if (p.scrollWidth > p.clientWidth + 10) {
                        p.scrollLeft = p.scrollWidth;
                        break;
                    }
                    p = p.parentElement;
                }
            }
        })();
        """)
        await asyncio.sleep(0.8)

        # Collect visible action buttons that appeared in the last table cell
        action_btns = await asyncio.to_thread(self._browser.execute_script, """
        (function() {
            function isVisible(el) {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
            }
            function getBestSelector(el) {
                const tid = el.getAttribute('data-testid') || el.getAttribute('data-cy');
                if (tid) return '[data-testid="' + tid + '"]';
                if (el.id && !/^\\d/.test(el.id)) return '#' + el.id;
                const al = el.getAttribute('aria-label');
                if (al && al.length < 80) return '[aria-label="' + al + '"]';
                return '';
            }
            const results = [];
            const seen = new Set();
            const lastCellSels = [
                'tbody tr td:last-child',
                '[role="row"] [role="cell"]:last-child',
                '[role="row"] [role="gridcell"]:last-child',
                '.mat-row .mat-cell:last-child',
            ];
            for (const sel of lastCellSels) {
                for (const cell of document.querySelectorAll(sel)) {
                    if (!isVisible(cell)) continue;
                    for (const btn of cell.querySelectorAll(
                        'button, [role="button"], a[href], mat-icon-button, [class*="icon-btn"], [class*="action-btn"]'
                    )) {
                        if (!isVisible(btn)) continue;
                        const text = (
                            btn.textContent || btn.getAttribute('aria-label') || btn.getAttribute('title') || ''
                        ).trim().replace(/\\s+/g, ' ');
                        const key = text.slice(0, 30);
                        if (!key || seen.has(key)) continue;
                        seen.add(key);
                        const s = getBestSelector(btn);
                        if (s) results.push({label: text.slice(0, 80), selector: s});
                    }
                    if (results.length >= 6) break;
                }
                if (results.length >= 6) break;
            }
            return results;
        })()
        """) or []

        # Click each found action button and capture what opens
        before_page_url = self._browser.get_current_url()
        for btn_info in action_btns[:4]:
            label = btn_info.get("label", "")
            selector = btn_info.get("selector", "")
            if not selector:
                continue

            before_url = self._browser.get_current_url()
            try:
                await asyncio.to_thread(self._browser.execute_script, f"""
                    const btn = document.querySelector('{selector}');
                    if (btn) {{ btn.scrollIntoView({{block:'center'}}); btn.click(); }}
                """)
            except Exception:
                continue

            await asyncio.sleep(1.5)
            after_url = self._browser.get_current_url()

            if after_url != before_url:
                await self._log("INFO", "exploration",
                    f"Row action '{label}' → navigated to: {after_url}")
                discoveries.append({
                    "type": "row_action_navigates",
                    "action": label,
                    "selector": selector,
                    "detail_url": after_url,
                    "description": f"Row action '{label}' navigates to a detail/edit page",
                })
                try:
                    self._browser.driver.back()
                    await asyncio.sleep(1.5)
                except Exception:
                    await asyncio.to_thread(self._browser.navigate, page_url)
                    await asyncio.sleep(2.0)
            else:
                dialog_info = await asyncio.to_thread(self._extract_dialog_or_form)
                if dialog_info and dialog_info.get("fields"):
                    await self._log("INFO", "exploration",
                        f"Row action '{label}' → dialog: '{dialog_info.get('title', 'Form')}'")
                    discoveries.append({
                        "type": "row_action_opens_dialog",
                        "action": label,
                        "selector": selector,
                        "dialog": dialog_info,
                        "description": f"Row action '{label}' opens '{dialog_info.get('title', 'a dialog')}'",
                    })
                    await asyncio.to_thread(self._close_any_dialog)
                    await asyncio.sleep(0.5)

        # Scroll tables back left
        await asyncio.to_thread(self._browser.execute_script, """
        (function() {
            const candidates = document.querySelectorAll(
                'table, [role="grid"], [class*="table"], [class*="datagrid"], .mat-table'
            );
            for (const el of candidates) {
                let p = el.parentElement;
                while (p && p !== document.body) {
                    if (p.scrollLeft > 0) { p.scrollLeft = 0; break; }
                    p = p.parentElement;
                }
            }
        })();
        """)

        return discoveries

    async def _explore_page_tabs(self, page: ApplicationPage) -> list[dict]:
        """
        Find tab buttons on the page, click each one, and capture what elements/forms appear
        in that tab's content area. Returns a list of tab content discoveries.
        """
        discoveries: list[dict] = []
        page_url = page.url or ""

        tabs = await asyncio.to_thread(self._browser.execute_script, """
        (function() {
            function isVisible(el) {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
            }
            const TAB_SELS = [
                '[role="tab"]', '.mat-tab-label', '.ant-tabs-tab',
                '.tab-link', '.nav-link', '.p-tabview-nav li a',
                '[class*="tab-btn"]', '[class*="tab-header"] button',
                '.MuiTab-root',
            ];
            const tabs = [];
            const seen = new Set();
            for (const sel of TAB_SELS) {
                try {
                    for (const el of document.querySelectorAll(sel)) {
                        if (!isVisible(el)) continue;
                        const text = (el.textContent || el.getAttribute('aria-label') || '').trim()
                            .replace(/\\s+/g, ' ');
                        if (!text || seen.has(text) || text.length > 60) continue;
                        seen.add(text);
                        const tid = el.getAttribute('data-testid') || el.getAttribute('data-cy');
                        const id = el.id && !/^\\d/.test(el.id) ? '#' + el.id : '';
                        const al = el.getAttribute('aria-label');
                        const s = tid ? '[data-testid="' + tid + '"]' : (id || (al ? '[aria-label="' + al + '"]' : ''));
                        tabs.push({label: text, selector: s});
                    }
                } catch(e) {}
                if (tabs.length >= 8) break;
            }
            return tabs;
        })()
        """) or []

        if len(tabs) <= 1:
            return discoveries

        await self._log("INFO", "exploration",
            f"Found {len(tabs)} tab(s): {', '.join(t.get('label','') for t in tabs[:6])}")

        # Click each non-first tab and extract what it shows
        for tab in tabs[1:4]:
            label = tab.get("label", "")
            if not label:
                continue

            try:
                await asyncio.to_thread(self._browser.execute_script, """
                (function(targetText) {
                    const TAB_SELS = [
                        '[role="tab"]','.mat-tab-label','.ant-tabs-tab',
                        '.tab-link','.nav-link','.MuiTab-root',
                        '[class*="tab-btn"]','[class*="tab-header"] button'
                    ];
                    for (const sel of TAB_SELS) {
                        for (const el of document.querySelectorAll(sel)) {
                            const t = (el.textContent || '').trim().replace(/\\s+/g,' ');
                            if (t === targetText) { el.click(); return; }
                        }
                    }
                })(arguments[0]);
                """, label)
            except Exception:
                continue

            await asyncio.sleep(1.5)

            # Extract interactive elements visible in this tab
            tab_elements = await asyncio.to_thread(self._extract_page_elements_js)
            # Also capture forms visible under this tab
            tab_forms = await asyncio.to_thread(self._browser.execute_script, """
            (function() {
                function isVisible(el) {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
                }
                const forms = [];
                for (const form of document.querySelectorAll('form, [role="form"]')) {
                    if (!isVisible(form)) continue;
                    const fields = [];
                    for (const inp of form.querySelectorAll('input, textarea, select')) {
                        if (!isVisible(inp)) continue;
                        const lbl = inp.id ? document.querySelector('label[for="' + inp.id + '"]') : null;
                        const label = (lbl ? lbl.textContent.trim() : '')
                            || inp.getAttribute('placeholder') || inp.getAttribute('aria-label') || '';
                        if (label) fields.push({label, type: inp.getAttribute('type') || inp.tagName.toLowerCase()});
                    }
                    if (fields.length) forms.push({fields});
                }
                return forms.slice(0, 4);
            })()
            """) or []

            btn_count = len([e for e in tab_elements if e.get("type") == "button"])
            if tab_elements or tab_forms:
                await self._log("INFO", "exploration",
                    f"  Tab '{label}': {btn_count} buttons, {len(tab_forms)} form(s)")
                discoveries.append({
                    "type": "tab_content",
                    "tab_label": label,
                    "elements_count": len(tab_elements),
                    "button_labels": [e.get("label", "") for e in tab_elements
                                      if e.get("type") == "button"][:8],
                    "forms": tab_forms[:3],
                })

                # Also click action buttons within this tab
                for el in tab_elements[:20]:
                    if el.get("category") in ("add", "edit", "delete") and el.get("selectors"):
                        dialog_data = await self._test_crud_operation(el, page.id)
                        if dialog_data and dialog_data.get("fields"):
                            discoveries.append({
                                "type": "tab_action_dialog",
                                "tab_label": label,
                                "action": el.get("label", ""),
                                "dialog": dialog_data,
                            })

        # Navigate back to reset page state
        await asyncio.to_thread(self._browser.navigate, page_url)
        await asyncio.sleep(1.5)

        return discoveries

    # ─────────────────────────────────────────────────────────────────────────
    # Pattern Discovery — QA Engineer Intelligence Layer
    # Each method answers one "how does X work on this page?" question.
    # ─────────────────────────────────────────────────────────────────────────

    def _discover_action_icons(self) -> dict:
        """
        Scan table rows for icon-based action buttons: edit (pencil), delete (trash),
        approve (checkmark), view (eye). Works after horizontal scroll since icons
        may be in the rightmost columns.

        Returns: {action_type: {selector, label, is_icon_only}} or empty dict.
        """
        return self._browser.execute_script("""
        (function() {
            function isVisible(el) {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0
                    && getComputedStyle(el).display !== 'none'
                    && getComputedStyle(el).visibility !== 'hidden';
            }
            function getBestSel(el) {
                const al = el.getAttribute('aria-label');
                const tid = el.getAttribute('data-testid') || el.getAttribute('data-cy');
                const id = el.id && !/^\\d/.test(el.id) ? '#' + el.id : '';
                const title = el.getAttribute('title');
                if (tid) return '[data-testid="' + tid + '"]';
                if (al) return '[aria-label="' + al + '"]';
                if (id) return id;
                if (title) return '[title="' + title + '"]';
                return '';
            }
            // Icon keyword sets per action type
            const PATTERNS = {
                edit: ['pencil','edit','pen','modify','update','fa-edit','fa-pen',
                       'mdi-pencil','bi-pencil','edit_outline','mode_edit','create'],
                delete: ['trash','delete','remove','bin','fa-trash','mdi-delete',
                         'bi-trash','delete_outline','clear','fa-remove'],
                approve: ['check','approve','accept','confirm','verify','done',
                          'fa-check','mdi-check','bi-check','check_circle',
                          'fa-thumbs-up','mdi-thumb-up'],
                view: ['eye','view','detail','show','preview','fa-eye','mdi-eye',
                       'bi-eye','visibility','fa-search-plus'],
                reject: ['close','reject','decline','deny','cancel','fa-times',
                         'mdi-close','bi-x','cancel_circle'],
            };
            const result = {};
            // Scan all table rows — look at cells (prefer last 3 for action column)
            const ROW_SELS = [
                'table tbody tr',
                '[role="grid"] [role="row"]:not([aria-rowindex="0"])',
                '[class*="mat-row"]', '[class*="ag-row"]',
            ];
            for (const rowSel of ROW_SELS) {
                const rows = Array.from(document.querySelectorAll(rowSel)).filter(isVisible);
                if (!rows.length) continue;
                for (const row of rows.slice(0, 3)) {
                    const cells = row.querySelectorAll('td, [role="cell"], [class*="mat-cell"]');
                    const cellArr = Array.from(cells);
                    // Check last 3 cells (action columns are typically on the right)
                    for (const cell of cellArr.slice(-3)) {
                        const btns = cell.querySelectorAll(
                            'button,[role="button"],a[href="javascript:void(0)"],'
                            + 'mat-icon,i[class*="fa"],i[class*="bi"],i[class*="mdi"]'
                        );
                        for (const btn of btns) {
                            if (!isVisible(btn)) continue;
                            // Collect all text signals for this button
                            const signals = [
                                (btn.getAttribute('aria-label') || '').toLowerCase(),
                                (btn.getAttribute('title') || '').toLowerCase(),
                                (btn.className || '').toLowerCase(),
                                (btn.textContent || '').trim().toLowerCase(),
                                ((btn.querySelector('mat-icon,svg,i') || {}).textContent || '').trim().toLowerCase(),
                                (btn.getAttribute('data-icon') || '').toLowerCase(),
                            ].join(' ');

                            for (const [actionType, keywords] of Object.entries(PATTERNS)) {
                                if (result[actionType]) continue;
                                if (keywords.some(kw => signals.includes(kw))) {
                                    const sel = getBestSel(btn);
                                    const visText = (btn.textContent || '').trim();
                                    result[actionType] = {
                                        selector: sel,
                                        label: (btn.getAttribute('aria-label') || btn.getAttribute('title') || visText || actionType).slice(0, 60),
                                        is_icon_only: visText.length === 0 || visText.length <= 2,
                                    };
                                    break;
                                }
                            }
                        }
                    }
                }
                if (Object.keys(result).length) break;
            }
            return result;
        })()
        """) or {}

    def _detect_status_tabs(self) -> list[dict]:
        """
        Detect workflow status tabs: Pending, Active, Approved, Rejected, Draft, etc.
        Returns a list of {label, selector, is_status_tab} for all visible tabs,
        with is_status_tab=True for tabs that look like workflow status indicators.
        """
        STATUS_KEYWORDS = {
            "pending", "active", "approved", "rejected", "draft", "review",
            "submitted", "cancelled", "closed", "completed", "open", "new",
            "in progress", "on hold", "expired", "archived", "published",
            "inactive", "all",
        }
        tabs = self._browser.execute_script("""
        (function() {
            function isVisible(el) {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
            }
            const TAB_SELS = [
                '[role="tab"]', '.mat-tab-label', '.ant-tabs-tab',
                '.nav-tabs .nav-link', '.tab-btn', '[class*="tab-header"] button',
                '.MuiTab-root', '[class*="tab-item"]', 'li[role="tab"]',
            ];
            const tabs = [];
            const seen = new Set();
            for (const sel of TAB_SELS) {
                for (const el of document.querySelectorAll(sel)) {
                    if (!isVisible(el)) continue;
                    const text = (el.textContent || el.getAttribute('aria-label') || '')
                        .trim().replace(/\\s+/g, ' ');
                    if (!text || seen.has(text.toLowerCase()) || text.length > 50) continue;
                    seen.add(text.toLowerCase());
                    const al = el.getAttribute('aria-label');
                    const tid = el.getAttribute('data-testid');
                    const id = el.id && !/^\\d/.test(el.id) ? '#'+el.id : '';
                    const sel2 = tid ? '[data-testid="'+tid+'"]' : al ? '[aria-label="'+al+'"]' : id || '';
                    const active = el.getAttribute('aria-selected') === 'true'
                        || el.classList.contains('active')
                        || el.classList.contains('mat-tab-label-active');
                    tabs.push({label: text, selector: sel2, is_active: active});
                }
                if (tabs.length >= 10) break;
            }
            return tabs;
        })()
        """) or []

        # Mark which tabs are status-related
        for tab in tabs:
            label_lower = tab.get("label", "").lower()
            tab["is_status_tab"] = any(kw in label_lower for kw in STATUS_KEYWORDS)

        return tabs

    async def _discover_bulk_delete_pattern(self) -> dict | None:
        """
        Detect bulk delete: click a row checkbox → watch for 'Actions' button to appear
        in the header → click it → look for 'Delete' in the dropdown.

        Returns a pattern dict or None if not found.
        Always restores state (unchecks checkbox / presses Escape).
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        # Find first visible row checkbox
        checkbox_sel = await asyncio.to_thread(self._browser.execute_script, """
        (function() {
            // Look for checkboxes in table rows — skip the header "select all" checkbox
            const SELS = [
                'table tbody tr td input[type="checkbox"]',
                '[role="row"]:not([aria-rowindex="0"]) input[type="checkbox"]',
                '[class*="mat-row"] mat-checkbox input',
                'tbody tr .ant-checkbox-input',
            ];
            for (const sel of SELS) {
                const els = document.querySelectorAll(sel);
                for (const el of els) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 || r.height > 0) {
                        // Get the wrapper (mat-checkbox or label) for clicking
                        const wrapper = el.closest('mat-checkbox,label,.ant-checkbox-wrapper')
                            || el;
                        const id = wrapper.id && !/^\\d/.test(wrapper.id) ? '#'+wrapper.id : '';
                        const al = wrapper.getAttribute('aria-label');
                        const tid = wrapper.getAttribute('data-testid');
                        return tid ? '[data-testid="'+tid+'"]'
                             : al  ? '[aria-label="'+al+'"]'
                             : id  || 'table tbody tr td input[type="checkbox"]';
                    }
                }
            }
            return null;
        })()
        """)
        if not checkbox_sel:
            return None

        # Click the checkbox
        try:
            el = self._browser.driver.find_element(By.CSS_SELECTOR, checkbox_sel)
            self._browser.execute_script("arguments[0].click()", el)
            await asyncio.sleep(0.8)
        except Exception:
            return None

        # Look for an "Actions" or "Bulk Actions" button that appeared
        actions_btn_sel = await asyncio.to_thread(self._browser.execute_script, """
        (function() {
            const LABELS = ['actions','bulk actions','action','more actions','options'];
            const all = document.querySelectorAll('button,[role="button"],[mat-button]');
            for (const el of all) {
                const r = el.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                const t = (el.textContent || el.getAttribute('aria-label') || '').trim().toLowerCase();
                if (LABELS.some(l => t.includes(l))) {
                    const al = el.getAttribute('aria-label');
                    const tid = el.getAttribute('data-testid');
                    return tid ? '[data-testid="'+tid+'"]' : al ? '[aria-label="'+al+'"]' : 'button';
                }
            }
            return null;
        })()
        """)

        result = None
        if actions_btn_sel:
            # Click the Actions button
            try:
                actions_el = self._browser.driver.find_element(By.CSS_SELECTOR, actions_btn_sel)
                actions_el_text = actions_el.text.strip()
                self._browser.execute_script("arguments[0].click()", actions_el)
                await asyncio.sleep(0.6)

                # Look for Delete in the opened dropdown
                delete_sel = self._browser.execute_script("""
                (function() {
                    const LABELS = ['delete','remove','destroy'];
                    const MENU_SELS = [
                        '[role="menu"] [role="menuitem"]',
                        '.mat-menu-content button', '.dropdown-menu .dropdown-item',
                        '[class*="menu"] li', '.ant-dropdown-menu-item',
                    ];
                    for (const sel of MENU_SELS) {
                        for (const el of document.querySelectorAll(sel)) {
                            const r = el.getBoundingClientRect();
                            if (r.width === 0 || r.height === 0) continue;
                            const t = (el.textContent || '').trim().toLowerCase();
                            if (LABELS.some(l => t.includes(l))) {
                                const al = el.getAttribute('aria-label');
                                return al ? '[aria-label="'+al+'"]' : '';
                            }
                        }
                    }
                    return null;
                })()
                """)

                if delete_sel is not None:
                    result = {
                        "pattern": "bulk_select_actions_menu",
                        "steps": [
                            {"action": "click_checkbox", "description": "Click row checkbox to select the entry", "selector": checkbox_sel},
                            {"action": "click_button", "description": f"Click '{actions_el_text or 'Actions'}' button that appears in the header", "selector": actions_btn_sel},
                            {"action": "click_menu_item", "description": "Click 'Delete' in the dropdown menu", "selector": delete_sel or ""},
                        ],
                        "confirm_dialog_expected": True,
                    }
                    await self._log("INFO", "exploration",
                        "Discovered bulk delete pattern: checkbox → Actions → Delete")
            except Exception:
                pass

            # Close the dropdown
            try:
                self._browser.driver.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                await asyncio.sleep(0.3)
            except Exception:
                pass

        # Uncheck the checkbox
        try:
            el = self._browser.driver.find_element(By.CSS_SELECTOR, checkbox_sel)
            if el.is_selected():
                self._browser.execute_script("arguments[0].click()", el)
            await asyncio.sleep(0.3)
        except Exception:
            pass

        return result

    async def _discover_approve_pattern(self, status_tabs: list[dict]) -> dict | None:
        """
        Discover the approval workflow:
        1. Detect if page has Pending/Approved tabs
        2. Navigate to Pending tab, look for approve action (green checkmark in action column
           or Approve button inside entry detail)
        3. Document the full verification workflow (entry should appear in Approved tab after)

        Returns a pattern dict or None if no approval workflow found.
        """
        from selenium.webdriver.common.by import By

        # Find the pending tab
        pending_tab = None
        approved_tab = None
        for tab in status_tabs:
            lbl = tab.get("label", "").lower()
            if any(k in lbl for k in ("pending", "submitted", "awaiting", "review", "draft")):
                pending_tab = tab
            if any(k in lbl for k in ("approved", "active", "completed", "done", "accepted")):
                approved_tab = tab

        if not pending_tab and not approved_tab:
            # No status tabs — check action column icons already discovered
            return None

        result: dict = {
            "pattern": "none_found",
            "pending_tab": pending_tab.get("label", "") if pending_tab else "",
            "approved_tab": approved_tab.get("label", "") if approved_tab else "",
        }

        # Navigate to pending tab to look for approve action
        if pending_tab and pending_tab.get("selector"):
            try:
                tab_el = self._browser.driver.find_element(By.CSS_SELECTOR, pending_tab["selector"])
                self._browser.execute_script("arguments[0].click()", tab_el)
                await asyncio.sleep(1.2)
            except Exception:
                pass

        # Look for approve icons in action column (already discovered by _discover_action_icons)
        # We already call that separately — just check if we have an approve icon
        approve_icons = self._discover_action_icons()
        if approve_icons.get("approve"):
            result["pattern"] = "action_column"
            result["approve_selector"] = approve_icons["approve"].get("selector", "")
            result["approve_label"] = approve_icons["approve"].get("label", "Approve")
            result["workflow"] = (
                f"1. Go to '{pending_tab.get('label', 'Pending')}' tab\n"
                f"2. Click approve icon ({approve_icons['approve'].get('label', 'green checkmark')}) on the entry\n"
                + (f"3. Verify entry moves to '{approved_tab.get('label', 'Approved')}' tab"
                   if approved_tab else "3. Verify entry status changes")
            )
            return result

        # Check if clicking first row opens a detail/edit view with an Approve button
        row_approve = await asyncio.to_thread(self._check_entry_detail_for_approve_button)
        if row_approve:
            result["pattern"] = "entry_detail"
            result["approve_selector"] = row_approve.get("selector", "")
            result["approve_label"] = row_approve.get("label", "Approve")
            result["workflow"] = (
                f"1. Go to '{pending_tab.get('label', 'Pending')}' tab\n"
                f"2. Click an entry to open its detail view\n"
                f"3. Click '{row_approve.get('label', 'Approve')}' button\n"
                + (f"4. Verify entry moves to '{approved_tab.get('label', 'Approved')}' tab"
                   if approved_tab else "4. Verify entry status changes")
            )
            return result

        # We have status tabs but no clear approve button yet — still document the tab structure
        if pending_tab or approved_tab:
            result["pattern"] = "status_tabs_only"
            result["workflow"] = (
                "Status tabs detected but approve action not found. "
                "May require role/permission to see approve controls."
            )
            return result

        return None

    def _check_entry_detail_for_approve_button(self) -> dict | None:
        """
        Click the first visible table row, check if an Approve/Accept button
        appears in the resulting dialog or detail page, then close/navigate back.
        """
        from selenium.webdriver.common.by import By

        APPROVE_LABELS = ["approve", "accept", "verify", "confirm", "authorize"]

        # Find first data row
        row = None
        for sel in ("table tbody tr", "[role='row'][aria-rowindex]", "[class*='mat-row']"):
            try:
                rows = self._browser.driver.find_elements(By.CSS_SELECTOR, sel)
                visible = [r for r in rows if r.is_displayed()]
                if visible:
                    row = visible[0]
                    break
            except Exception:
                pass

        if not row:
            return None

        url_before = self._browser.get_current_url()
        try:
            cells = row.find_elements(By.CSS_SELECTOR, "td, [role='cell']")
            if cells:
                self._browser.execute_script("arguments[0].scrollIntoView({block:'center'}); arguments[0].click()", cells[0])
            time.sleep(1.0)
        except Exception:
            return None

        # Check for approve button in dialog or new page
        approve_info = self._browser.execute_script("""
        (function() {
            const LABELS = arguments[0];
            const SELS = ['[role="dialog"]', '[aria-modal="true"]', '.modal.show'];
            let container = document;
            for (const sel of SELS) {
                const el = document.querySelector(sel);
                if (el) { const r = el.getBoundingClientRect(); if (r.width > 0) { container = el; break; } }
            }
            for (const btn of container.querySelectorAll('button,[role="button"]')) {
                const r = btn.getBoundingClientRect();
                if (r.width === 0 || r.height === 0) continue;
                const t = (btn.textContent || btn.getAttribute('aria-label') || '').trim().toLowerCase();
                if (LABELS.some(l => t.includes(l))) {
                    const al = btn.getAttribute('aria-label');
                    const tid = btn.getAttribute('data-testid');
                    return {
                        label: (btn.textContent || btn.getAttribute('aria-label') || '').trim().slice(0, 60),
                        selector: tid ? '[data-testid="'+tid+'"]' : al ? '[aria-label="'+al+'"]' : '',
                    };
                }
            }
            return null;
        })(arguments[0])
        """, APPROVE_LABELS)

        # Restore state
        url_after = self._browser.get_current_url()
        if url_after != url_before:
            try:
                self._browser.driver.back()
                time.sleep(0.8)
            except Exception:
                pass
        else:
            self._close_any_dialog()
            time.sleep(0.3)

        return approve_info

    async def _probe_search_no_data_state(self) -> dict | None:
        """
        Find a search input, type a string that cannot match any real record,
        trigger the search, capture the 'no results' message, then restore.

        Returns {no_results_message, search_selector} or None if no search found.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        # Find search input
        search_info = await asyncio.to_thread(self._browser.execute_script, """
        (function() {
            const SELS = [
                'input[type="search"]',
                'input[placeholder*="search" i]',
                'input[placeholder*="find" i]',
                'input[placeholder*="filter" i]',
                '[aria-label*="search" i]',
                'input[class*="search"]',
                'input[name*="search" i]',
                '.search-input input',
                '[class*="search-bar"] input',
            ];
            for (const sel of SELS) {
                for (const el of document.querySelectorAll(sel)) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none') {
                        const al = el.getAttribute('aria-label');
                        const id = el.id && !/^\\d/.test(el.id) ? '#'+el.id : '';
                        const nm = el.getAttribute('name');
                        return {
                            selector: al ? '[aria-label="'+al+'"]' : id || (nm ? '[name="'+nm+'"]' : sel),
                            placeholder: el.getAttribute('placeholder') || '',
                        };
                    }
                }
            }
            return null;
        })()
        """)
        if not search_info:
            return None

        sel = search_info.get("selector", "")
        if not sel:
            return None

        # Find search button
        search_btn_sel = await asyncio.to_thread(self._browser.execute_script, """
        (function() {
            const SELS = [
                'button[type="submit"]',
                'button[aria-label*="search" i]',
                'button[class*="search"]',
                '.search-btn', '[class*="search-button"]',
                'input[type="submit"]',
            ];
            for (const sel of SELS) {
                for (const el of document.querySelectorAll(sel)) {
                    const r = el.getBoundingClientRect();
                    if (r.width > 0 && r.height > 0) {
                        const al = el.getAttribute('aria-label');
                        return al ? '[aria-label="'+al+'"]' : sel;
                    }
                }
            }
            return null;
        })()
        """)

        # Record row count before
        rows_before = await asyncio.to_thread(self._browser.execute_script,
            "return document.querySelectorAll('table tbody tr').length || 0") or 0

        IMPOSSIBLE_STRING = "xZqQA_NoMatch_99771_Test"

        try:
            input_el = self._browser.driver.find_element(By.CSS_SELECTOR, sel)
        except Exception:
            return None

        try:
            # Clear existing value and type the impossible string
            self._browser.execute_script("""
                const el = arguments[0]; const val = arguments[1];
                el.value = '';
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
                if (setter && setter.set) setter.set.call(el, val);
                else el.value = val;
                ['input','change'].forEach(e => el.dispatchEvent(new Event(e, {bubbles:true})));
            """, input_el, IMPOSSIBLE_STRING)
            await asyncio.sleep(0.3)

            # Click search button or press Enter
            if search_btn_sel:
                try:
                    btn = self._browser.driver.find_element(By.CSS_SELECTOR, search_btn_sel)
                    self._browser.execute_script("arguments[0].click()", btn)
                except Exception:
                    input_el.send_keys(Keys.RETURN)
            else:
                input_el.send_keys(Keys.RETURN)

            await asyncio.sleep(1.5)

            # Capture the no-results message
            no_results_msg = await asyncio.to_thread(self._browser.execute_script, """
            (function() {
                const SELS = [
                    '[class*="no-data"]', '[class*="no-results"]', '[class*="empty-state"]',
                    '[class*="not-found"]', '[class*="no-records"]', '[class*="empty"]',
                    '[class*="no-match"]', '[class*="zero-state"]',
                    'td[colspan]', 'div[class*="empty-message"]',
                ];
                for (const sel of SELS) {
                    for (const el of document.querySelectorAll(sel)) {
                        const r = el.getBoundingClientRect();
                        const t = el.textContent.trim();
                        if (r.width > 0 && r.height > 0 && t.length > 3 && t.length < 300) return t;
                    }
                }
                // Check if table rows disappeared (compared to before)
                const rows = document.querySelectorAll('table tbody tr');
                if (rows.length === 1) {
                    const t = rows[0].textContent.trim();
                    if (t.length > 3 && t.length < 300) return t;
                }
                return null;
            })()
            """)

            result = {
                "search_selector": sel,
                "search_button_selector": search_btn_sel,
                "trigger_string": IMPOSSIBLE_STRING,
                "no_results_message": no_results_msg or "No results message not detected — rows disappeared",
            }

            await self._log("INFO", "exploration",
                f"No-data state: '{no_results_msg or 'rows cleared'}' (searched for impossible string)")

        except Exception as e:
            log.debug("Search no-data probe failed", error=str(e)[:80])
            result = None
        finally:
            # Restore: clear search
            try:
                input_el2 = self._browser.driver.find_element(By.CSS_SELECTOR, sel)
                self._browser.execute_script("""
                    const el = arguments[0];
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
                    if (setter && setter.set) setter.set.call(el, '');
                    else el.value = '';
                    ['input','change'].forEach(e => el.dispatchEvent(new Event(e, {bubbles:true})));
                """, input_el2)
                if search_btn_sel:
                    btn = self._browser.driver.find_element(By.CSS_SELECTOR, search_btn_sel)
                    self._browser.execute_script("arguments[0].click()", btn)
                else:
                    input_el2.send_keys(Keys.RETURN)
                await asyncio.sleep(0.8)
            except Exception:
                pass

        return result

    async def _merge_dialog_forms_into_page(self, page: ApplicationPage, elements: list[dict]):
        """Enrich page.forms with any dialog forms discovered by CRUD testing."""
        extra_forms = []
        for el in elements:
            dialog = el.get("dialog")
            if not dialog or not dialog.get("fields"):
                continue
            form_entry = {
                "name": dialog.get("title", el.get("label", "Form")),
                "trigger": el.get("label", ""),
                "trigger_category": el.get("category", ""),
                "purpose": f"Dialog opened by '{el.get('label','')}'",
                "fields": dialog["fields"],
            }
            extra_forms.append(form_entry)

        if extra_forms:
            existing = list(page.forms or [])
            existing.extend(extra_forms)
            page.forms = existing
            await self.db.commit()

    async def _save_semantic_elements(self, elements: list[dict], page_id: str):
        """Persist extracted elements as SemanticElement records."""
        # Delete stale elements from a previous scan of this page
        existing_result = await self.db.execute(
            select(SemanticElement).where(SemanticElement.page_id == page_id)
        )
        for stale in existing_result.scalars().all():
            await self.db.delete(stale)

        for el in elements:
            label = el.get("label", "").strip()
            if not label:
                continue
            elem = SemanticElement(
                page_id=page_id,
                semantic_label=label[:512],
                element_type=el.get("type", "button"),
                role=el.get("role", ""),
                purpose=el.get("category", ""),
                selectors=el.get("selectors", []),
                confidence=0.85,
                dynamic_reveals=el.get("dynamic_reveals", []),
            )
            self.db.add(elem)

        await self.db.commit()

    # ─────────────────────────────────────────────────────────────────────────
    # Phase: Test Scenario Generation
    # ─────────────────────────────────────────────────────────────────────────

    async def _generate_test_scenarios(self, application_id: str, session_id: str, module_ids: list[str] | None = None) -> int:
        """
        Phase 6: Generate AI test scenarios from exploration data.
        Uses smaller batches (2 modules per call) to avoid token-limit issues.
        Skips if token budget is critical.
        """
        # Check if we have token budget for scenarios
        remaining = await self._token_budget.remaining()
        if remaining < 50000:
            await self._log("WARNING", "scenarios",
                f"Token budget low ({remaining} remaining) — skipping scenario generation")
            return 0

        await self._log("MILESTONE", "scenarios", "Generating test scenarios from exploration data")
        budget = await self._token_budget.summary()
        await self._log("INFO", "scenarios",
            f"Token budget available: {budget['remaining']}/{budget['limit']} tokens")

        # Delete old AI-generated scenarios so we regenerate fresh ones (scoped by module_ids if provided)
        del_stmt = select(Scenario).where(
            Scenario.application_id == application_id,
            Scenario.source == "ai_generated",
        )
        if module_ids:
            del_stmt = del_stmt.where(Scenario.module_id.in_(module_ids))

        existing_result = await self.db.execute(del_stmt)
        for old in existing_result.scalars().all():
            await self.db.delete(old)
        await self.db.commit()

        # Load modules
        mod_stmt = select(ApplicationModule).where(ApplicationModule.application_id == application_id)
        if module_ids:
            mod_stmt = mod_stmt.where(ApplicationModule.id.in_(module_ids))
        mods_result = await self.db.execute(mod_stmt)
        all_modules = list(mods_result.scalars().all())

        # Also load child modules created during accordion exploration
        # (pages/workflows for accordion parents are stored under their children)
        parent_to_children: dict[str, list[str]] = {}
        if module_ids:
            child_stmt = select(ApplicationModule).where(
                ApplicationModule.parent_id.in_(module_ids),
                ApplicationModule.application_id == application_id,
            )
            child_result = await self.db.execute(child_stmt)
            for cm in child_result.scalars().all():
                parent_to_children.setdefault(cm.parent_id, []).append(cm.id)

        child_module_ids = [cid for ids in parent_to_children.values() for cid in ids]
        all_relevant_ids = (list(module_ids) + child_module_ids) if module_ids else None

        # Fetch pages and workflows using expanded ID set (includes accordion children)
        page_stmt = select(ApplicationPage).join(ApplicationModule, ApplicationPage.module_id == ApplicationModule.id).where(ApplicationModule.application_id == application_id)
        if all_relevant_ids:
            page_stmt = page_stmt.where(ApplicationModule.id.in_(all_relevant_ids))
        pages_result = await self.db.execute(page_stmt)
        pages = list(pages_result.scalars().all())

        wf_stmt = select(ApplicationWorkflow).join(ApplicationModule, ApplicationWorkflow.module_id == ApplicationModule.id).where(ApplicationModule.application_id == application_id)
        if all_relevant_ids:
            wf_stmt = wf_stmt.where(ApplicationModule.id.in_(all_relevant_ids))
        wf_result = await self.db.execute(wf_stmt)
        workflows = list(wf_result.scalars().all())

        await self._log("INFO", "scenarios",
            f"Loaded {len(all_modules)} module(s), {len(pages)} page(s), {len(workflows)} workflow(s) for scenario generation")

        # Include all selected modules (accordion parents get their context from child data below)
        modules = list(all_modules)

        if not modules:
            await self._log("WARNING", "scenarios", "No valid modules found — skipping scenario generation")
            return 0

        # ── Tier 0: Generate KG-backed scenarios first (no AI, no token budget) ──
        kg_gen_count = await self._generate_kg_scenarios(application_id)
        if kg_gen_count:
            await self._log("INFO", "scenarios",
                f"{kg_gen_count} KG-backed scenario(s) created before AI generation")

        # Build per-module detail context; for accordion parents, pull from child modules too
        def _module_ctx(m) -> dict:
            m_own_pages = [p for p in pages if p.module_id == m.id]
            child_ids = parent_to_children.get(m.id, [])
            m_child_pages = [p for p in pages if p.module_id in child_ids]
            m_pages = m_own_pages + m_child_pages

            m_forms = [
                {
                    "name": f.get("name", ""),
                    "fields": [fld.get("label", "") for fld in f.get("fields", [])[:6]],
                    "submit_action": f.get("submit_action", ""),
                }
                for p in m_pages[:3] for f in (p.forms or [])[:3]
            ]
            m_tables = [
                t.get("name", "")
                for p in m_pages[:3] for t in (p.tables or [])[:3]
            ]
            m_wfs = [w.name for w in workflows if w.module_id == m.id or w.module_id in child_ids][:6]

            # Dynamic target: 5 base + extras for CRUD forms, tables, and workflows
            target = 5
            target += len(m_forms) * 3        # create, edit, delete per form
            if m_tables:
                target += 3                   # search, filter, sort
            if len(m_wfs) > 1:
                target += (len(m_wfs) - 1) * 2
            target = min(target, 20)

            # Derive which coverage types apply
            coverage = ["view list", "navigation"]
            if m_forms:
                coverage += ["create record", "edit record", "delete record", "field validation", "required field validation"]
            if m_tables:
                coverage += ["search", "filter", "sort/pagination"]
            if m_wfs:
                coverage += ["end-to-end workflow", "workflow error handling"]
            coverage += ["boundary values", "permission/access"]

            return {
                "module": m.name,
                "url": m.url_pattern or "",
                "forms": m_forms[:6],
                "tables": m_tables[:6],
                "workflows": m_wfs,
                "target_scenario_count": target,
                "coverage_types": coverage,
            }

        priority_map = {
            "CRITICAL": ScenarioPriority.CRITICAL,
            "HIGH": ScenarioPriority.HIGH,
            "MEDIUM": ScenarioPriority.MEDIUM,
            "LOW": ScenarioPriority.LOW,
        }

        _system = (
            "You are a QA engineer. Generate test scenarios from the application data provided. "
            "Output ONLY a JSON object: {\"scenarios\": [...]}. No markdown, no explanation."
        )

        app_header = (
            f"Application: {self._app.name or 'Web Application'}\n"
            f"URL: {self._app.base_url}\n\n"
        )

        # ── Batch: 2 modules per AI call (smaller = fewer tokens, fewer 429s) ──
        BATCH_SIZE = 2
        all_scenario_infos: list[dict] = []
        batches = [modules[i:i+BATCH_SIZE] for i in range(0, len(modules), BATCH_SIZE)]
        await self._log("INFO", "scenarios", f"Generating scenarios in {len(batches)} batches (size={BATCH_SIZE})")

        for batch_idx, batch in enumerate(batches):
            # Check token budget before each batch
            remaining = await self._token_budget.remaining()
            if remaining < 30000:
                await self._log("WARNING", "scenarios",
                    f"Token budget critical ({remaining} remaining) — stopping scenario generation")
                break
            batch_ctx = [_module_ctx(m) for m in batch]
            module_names_str = ", ".join(m.name for m in batch)

            await self._log("INFO", "scenarios",
                f"Batch {batch_idx+1}/{len(batches)}: generating for [{module_names_str}] "
                f"(pages={sum(len([p for p in pages if p.module_id == m.id]) for m in batch)}, "
                f"workflows={sum(len([w for w in workflows if w.module_id == m.id]) for m in batch)})")

            # Compact JSON (no indent) cuts ~30% token overhead vs indent=1
            ctx_json = json.dumps(batch_ctx, separators=(",", ":"))

            prompt = (
                f"{app_header}"
                f"MODULES TO COVER: {module_names_str}\n\n"
                f"MODULE DETAILS:\n{ctx_json}\n\n"
                "TASK: For each module, generate exactly the number of scenarios specified in "
                "its 'target_scenario_count' field, covering all types listed in its "
                "'coverage_types' field. Modules with forms need create/edit/delete/validation "
                "scenarios. Modules with tables need search/filter/sort scenarios. "
                "Modules with workflows need end-to-end and error-handling scenarios. "
                "Each scenario needs: title (verb + object, max 80 chars), "
                "description (numbered steps with clear actions and expected results, min 4 steps), "
                "priority (CRITICAL/HIGH/MEDIUM/LOW — CRITICAL for core workflows, HIGH for CRUD, "
                "MEDIUM for search/filter, LOW for edge cases), "
                "module (exact name from MODULES TO COVER), tags (array), "
                "test_type (functional/smoke/regression/negative).\n\n"
                "Return ONLY this JSON:\n"
                "{\"scenarios\": [{\"title\": \"...\", \"description\": \"...\", "
                "\"priority\": \"HIGH\", \"module\": \"...\", "
                "\"tags\": [\"functional\"], \"test_type\": \"functional\"}]}"
            )

            batch_scenarios: list[dict] = []
            for attempt in range(1, 3):
                try:
                    response = await asyncio.wait_for(
                        self.ai.complete(
                            system=_system,
                            user=prompt,
                            fast=True,
                            json_mode=True,
                            max_tokens=8000,
                        ),
                        timeout=180.0,
                    )
                    # Track tokens for budget
                    await self._token_budget.add(
                        int(response.input_tokens * 0.7),
                        int(response.output_tokens * 0.3)
                    )
                    content = response.content.strip()
                    if not content:
                        await self._log("WARNING", "scenarios",
                            f"Batch {batch_idx+1}: AI returned empty response (attempt {attempt}/2)")
                        continue
                    # Try to parse — if JSON is truncated (finish_reason=length), attempt
                    # to salvage the already-complete scenario objects from the partial output.
                    try:
                        data = response.json()
                    except (json.JSONDecodeError, ValueError):
                        # Truncated JSON: extract all complete {"title":...} objects
                        salvaged = re.findall(r'\{[^{}]*"title"[^{}]*\}', content)
                        if salvaged:
                            data = {"scenarios": [json.loads(s) for s in salvaged if _is_valid_scenario_json(s)]}
                            await self._log("WARNING", "scenarios",
                                f"Batch {batch_idx+1}: response truncated — salvaged {len(data['scenarios'])} scenario(s) (attempt {attempt}/2)")
                        else:
                            await self._log("WARNING", "scenarios",
                                f"Batch {batch_idx+1}: response truncated and unrecoverable (attempt {attempt}/2)")
                            continue
                    # Handle both {"scenarios": [...]} and bare [...] response formats
                    if isinstance(data, list):
                        batch_scenarios = data
                    elif isinstance(data, dict):
                        batch_scenarios = data.get("scenarios") or []
                    else:
                        batch_scenarios = []
                    if batch_scenarios:
                        break
                    await self._log("WARNING", "scenarios",
                        f"Batch {batch_idx+1}: AI returned valid JSON but no scenarios (attempt {attempt}/2) — raw: {content[:100]}")
                except asyncio.TimeoutError:
                    await self._log("WARNING", "scenarios",
                        f"Batch {batch_idx+1}: AI call timed out after 180s (attempt {attempt}/2)")
                    log.warning("Scenario batch timed out", batch=batch_idx, attempt=attempt)
                except Exception as e:
                    await self._log("WARNING", "scenarios",
                        f"Batch {batch_idx+1}: AI call failed (attempt {attempt}/2): {str(e)[:200]}")
                    log.warning("Scenario batch failed", batch=batch_idx, attempt=attempt, error=str(e)[:200])

            if batch_scenarios:
                all_scenario_infos.extend(batch_scenarios)
                await self._log("INFO", "scenarios",
                    f"Batch {batch_idx+1}/{len(batches)}: {len(batch_scenarios)} scenarios for [{module_names_str}]")
            else:
                await self._log("WARNING", "scenarios",
                    f"Batch {batch_idx+1}/{len(batches)}: no scenarios generated for [{module_names_str}]")

        if not all_scenario_infos:
            await self._log("WARNING", "scenarios", "No scenario data from any batch — skipping")
            return 0

        # ── Persist all collected scenarios ──────────────────────────────────
        module_counts: dict[str, int] = {}
        count = 0

        for s_info in all_scenario_infos[:500]:
            title = (s_info.get("title") or "").strip()
            if not title or len(title) > 500:
                continue

            module_id = None
            s_module = (s_info.get("module") or "").lower().strip()
            if s_module:
                for m in modules:
                    if s_module == m.name.lower() or s_module in m.name.lower() or m.name.lower() in s_module:
                        module_id = m.id
                        module_counts[m.name] = module_counts.get(m.name, 0) + 1
                        break

            priority = priority_map.get(
                (s_info.get("priority") or "MEDIUM").upper(),
                ScenarioPriority.MEDIUM,
            )
            tags = list(s_info.get("tags") or [])
            test_type = s_info.get("test_type", "functional")
            if test_type and test_type not in tags:
                tags.append(test_type)

            self.db.add(Scenario(
                application_id=application_id,
                title=title,
                description=(s_info.get("description") or "").strip(),
                priority=priority,
                tags=tags,
                module_id=module_id,
                source="ai_generated",
                is_active=True,
            ))
            count += 1

        if count:
            await self.db.commit()
            modules_with_5plus = sum(1 for c in module_counts.values() if c >= 5)
            await self._log("SUCCESS", "scenarios",
                f"{count} test scenarios generated across {len(module_counts)} modules "
                f"({modules_with_5plus}/{len(modules)} modules have 5+ scenarios)")

        return count

    # ─────────────────────────────────────────────────────────────────────────
    # Enhanced scenario context: enrich planner with stored selectors
    # ─────────────────────────────────────────────────────────────────────────

    async def _store_exploration_memory(self, application_id: str):
        """
        Persist a compact exploration summary as an AIMemoryChunk so the
        ScenarioPlanner can retrieve it as a memory hint.
        """
        mods_result = await self.db.execute(
            select(ApplicationModule).where(ApplicationModule.application_id == application_id)
        )
        modules = mods_result.scalars().all()
        if not modules:
            return

        pages_result = await self.db.execute(
            select(ApplicationPage)
            .join(ApplicationModule, ApplicationPage.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == application_id)
            .limit(20)
        )
        pages = pages_result.scalars().all()

        lines = [f"Application: {self._app.name}", ""]
        for m in modules:
            lines.append(f"Module: {m.name}")
            for p in pages:
                if p.module_id == m.id:
                    lines.append(f"  Page: {p.title} ({p.url})")
                    for f in (p.forms or [])[:3]:
                        fields = ", ".join(fld.get("label","") for fld in f.get("fields",[])[:5])
                        lines.append(f"    Form '{f.get('name','')}': {fields}")

        chunk = AIMemoryChunk(
            application_id=application_id,
            kind=MemoryKind.MODULE,
            content="\n".join(lines),
            extra={"session_id": self._session_id, "source": "exploration"},
            confidence=0.9,
        )
        self.db.add(chunk)
        await self.db.commit()

    async def _store_interaction_guide(
        self,
        module_id: str,
        module_name: str,
        page: ApplicationPage,
        elements: list[dict],
        row_discoveries: list[dict] | None = None,
        tab_discoveries: list[dict] | None = None,
        action_icons: dict | None = None,
        status_tabs: list[dict] | None = None,
        bulk_delete_pattern: dict | None = None,
        approve_pattern: dict | None = None,
        search_no_data: dict | None = None,
    ) -> None:
        """
        Build and persist a structured interaction guide for a module page.

        This guide describes EXACTLY how to interact with every action on the page
        — which button to click, what form opens, each field's selector — so the
        execution planner can generate precise, selector-accurate test steps.

        Stored as AIMemoryChunk (kind=WORKFLOW, extra.guide_type='interaction').
        """
        # Delete any previous interaction guide for this module so we don't duplicate
        existing = await self.db.execute(
            select(AIMemoryChunk).where(
                AIMemoryChunk.application_id == self._app.id,
                AIMemoryChunk.kind == MemoryKind.WORKFLOW,
            )
        )
        for old_chunk in existing.scalars().all():
            if (old_chunk.extra or {}).get("guide_type") == "interaction" and \
               (old_chunk.extra or {}).get("module_id") == module_id:
                await self.db.delete(old_chunk)

        # Helper: pick best CSS selector from a selectors list
        def best_css(selectors: list) -> str:
            for s in (selectors or []):
                if s.get("type") == "css":
                    return s.get("value", "")
            for s in (selectors or []):
                if s.get("type") == "xpath":
                    return s.get("value", "")
            return ""

        # Empty state info
        initial_state = (page.page_data or {}).get("initial_state", {})

        lines = [
            f"MODULE: {module_name}",
            f"URL: {page.url or 'unknown'}",
            f"PAGE TYPE: {page.page_type or 'unknown'}",
            "",
            "NAVIGATION PATH: accessible from the application sidebar",
        ]

        # Empty state documentation
        if initial_state:
            if initial_state.get("is_empty") and initial_state.get("empty_message"):
                lines.append(f"\nEMPTY STATE: When no records exist, the page shows: \"{initial_state['empty_message']}\"")
            elif initial_state.get("row_count", 0) > 0:
                lines.append(f"\nINITIAL STATE: Page loads with {initial_state['row_count']} existing record(s).")

        lines.append("\nINTERACTIVE ACTIONS:")

        # CRUD/action buttons with their dialog context
        for el in elements:
            category = el.get("category", "")
            label = el.get("label", "")
            sel = best_css(el.get("selectors", []))
            reveals = el.get("dynamic_reveals", [])

            if category in ("add", "edit", "delete", "submit", "action") and label:
                lines.append(f"\n[{category.upper()}] \"{label}\" button")
                if sel:
                    lines.append(f"  Trigger selector: {sel}")

                for rev in (reveals or []):
                    if not isinstance(rev, dict):
                        continue
                    title = rev.get("title", "")
                    fields = rev.get("fields", [])
                    submit_sel = rev.get("submit_selector", "")
                    cancel_sel = rev.get("cancel_selector", "")
                    validation_rules = rev.get("validation_rules", {})
                    roundtrip = rev.get("roundtrip")

                    if title:
                        lines.append(f"  Opens: \"{title}\" dialog/form")
                    if fields:
                        lines.append("  Form fields:")
                        for f in fields[:15]:
                            if not isinstance(f, dict):
                                continue
                            f_label = f.get("label", "")
                            f_type = f.get("type", "text")
                            f_sel = f.get("selector", "")
                            f_name = f.get("name", "")
                            f_required = " (required)" if f.get("required") else ""
                            sel_hint = f_sel or (f"[name=\"{f_name}\"]" if f_name else "")
                            opts = f.get("options", [])
                            opts_hint = f" options=[{', '.join(opts[:5])}]" if opts else ""
                            # Inline validation error for this field
                            field_errors = validation_rules.get(f_label, []) if isinstance(validation_rules, dict) else []
                            err_hint = f" validation-error='{field_errors[0]}'" if field_errors else ""
                            lines.append(
                                f"    - {f_label} ({f_type}{f_required}){opts_hint}{err_hint}"
                                + (f" — selector: {sel_hint}" if sel_hint else "")
                            )
                    if validation_rules:
                        lines.append("  Validation rules (from live probe — submit empty):")
                        for vfield, verrors in list(validation_rules.items())[:8]:
                            lines.append(f"    {vfield}: \"{verrors[0]}\"" if verrors else f"    {vfield}: required")
                    if submit_sel:
                        lines.append(f"  Submit/Save selector: {submit_sel}")
                    if cancel_sel:
                        lines.append(f"  Cancel selector: {cancel_sel}")
                    if roundtrip and roundtrip.get("submitted"):
                        if roundtrip.get("success_indicator"):
                            lines.append(f"  SUCCESS INDICATOR: \"{roundtrip['success_indicator']}\"")
                        if roundtrip.get("row_delta", 0) > 0:
                            lines.append(f"  AFTER CREATE: list row count increases by {roundtrip['row_delta']}")
                        if roundtrip.get("navigation_url"):
                            lines.append(f"  AFTER CREATE: navigates to {roundtrip['navigation_url']}")
                        if roundtrip.get("error_on_submit"):
                            lines.append(f"  NOTE: Submit error observed: \"{roundtrip['error_on_submit'][:100]}\"")

                if not reveals:
                    dialog = el.get("dialog")
                    if dialog and dialog.get("fields"):
                        lines.append(f"  Opens dialog: \"{dialog.get('title', 'Form')}\"")

        # Search / filter inputs
        search_els = [e for e in elements if e.get("category") == "search"]
        if search_els:
            lines.append("\nSEARCH/FILTER:")
            for el in search_els[:3]:
                sel = best_css(el.get("selectors", []))
                lines.append(f"  \"{el.get('label', 'Search')}\" — {sel}")

        # Table info from page data
        for table in (page.tables or [])[:3]:
            if not isinstance(table, dict):
                continue
            t_name = table.get("name", "Table")
            row_actions = table.get("row_actions", [])
            raw_cols = table.get("columns", [])
            # AI may return columns as strings or dicts — handle both
            cols = [
                c.get("name", "") if isinstance(c, dict) else str(c)
                for c in (raw_cols or [])[:8]
                if (c.get("name", "") if isinstance(c, dict) else c)
            ]
            lines.append(f"\nTABLE: {t_name}")
            if cols:
                lines.append(f"  Columns: {', '.join(cols)}")
            if row_actions:
                lines.append(f"  Row actions: {', '.join(str(a) for a in row_actions[:5])}")

        # Table row interaction discoveries (from live clicking)
        for disc in (row_discoveries or []):
            if not isinstance(disc, dict):
                continue
            dtype = disc.get("type", "")
            if dtype == "row_opens_detail":
                lines.append(f"\nTABLE ROW INTERACTION: Clicking a row navigates to a detail page")
                lines.append(f"  Detail URL pattern: {disc.get('detail_url', '')}")
                lines.append(f"  NOTE: To edit/view a record, click the row to navigate to its detail page")
            elif dtype == "row_opens_dialog":
                dialog = disc.get("dialog", {})
                if not isinstance(dialog, dict):
                    dialog = {}
                lines.append(f"\nTABLE ROW INTERACTION: Clicking a row opens '{dialog.get('title', 'a dialog')}'")
                for f in dialog.get("fields", [])[:10]:
                    if not isinstance(f, dict):
                        continue
                    f_sel = f.get("selector", "") or (f"[name=\"{f.get('name', '')}\"]" if f.get("name") else "")
                    f_required = " (required)" if f.get("required") else ""
                    lines.append(f"  Field: {f.get('label', '')} ({f.get('type', 'text')}{f_required})"
                                 + (f" — selector: {f_sel}" if f_sel else ""))
                if dialog.get("submit_selector"):
                    lines.append(f"  Submit selector: {dialog['submit_selector']}")
            elif dtype == "row_action_opens_dialog":
                dialog = disc.get("dialog", {})
                if not isinstance(dialog, dict):
                    dialog = {}
                action = disc.get("action", "")
                lines.append(f"\nROW ACTION: '{action}' button (selector: {disc.get('selector', '')})")
                lines.append(f"  Opens: '{dialog.get('title', 'a dialog')}'")
                for f in dialog.get("fields", [])[:10]:
                    if not isinstance(f, dict):
                        continue
                    f_sel = f.get("selector", "") or (f"[name=\"{f.get('name', '')}\"]" if f.get("name") else "")
                    opts = f.get("options", [])
                    opts_hint = f" options=[{', '.join(opts[:5])}]" if opts else ""
                    lines.append(f"  Field: {f.get('label', '')} ({f.get('type', 'text')}){opts_hint}"
                                 + (f" — selector: {f_sel}" if f_sel else ""))
                if dialog.get("submit_selector"):
                    lines.append(f"  Submit selector: {dialog['submit_selector']}")
            elif dtype == "row_action_navigates":
                lines.append(f"\nROW ACTION: '{disc.get('action', '')}' button (selector: {disc.get('selector', '')})")
                lines.append(f"  Navigates to: {disc.get('detail_url', '')}")

        # Tab content discoveries (from live tab clicking)
        for disc in (tab_discoveries or []):
            if not isinstance(disc, dict):
                continue
            dtype = disc.get("type", "")
            if dtype == "tab_content":
                tab_label = disc.get("tab_label", "")
                btn_labels = disc.get("button_labels", [])
                tab_forms = disc.get("forms", [])
                lines.append(f"\nTAB: '{tab_label}'")
                if btn_labels:
                    lines.append(f"  Buttons: {', '.join(btn_labels[:6])}")
                for form in tab_forms[:2]:
                    if not isinstance(form, dict):
                        continue
                    field_names = [
                        f.get("label", "") for f in form.get("fields", [])[:6]
                        if isinstance(f, dict)
                    ]
                    if field_names:
                        lines.append(f"  Form fields: {', '.join(field_names)}")
            elif dtype == "tab_action_dialog":
                tab_label = disc.get("tab_label", "")
                action = disc.get("action", "")
                dialog = disc.get("dialog", {})
                if not isinstance(dialog, dict):
                    dialog = {}
                lines.append(f"\nTAB '{tab_label}' ACTION: '{action}'")
                lines.append(f"  Opens: '{dialog.get('title', 'a dialog')}'")
                for f in dialog.get("fields", [])[:8]:
                    if not isinstance(f, dict):
                        continue
                    f_sel = f.get("selector", "")
                    lines.append(f"  Field: {f.get('label', '')} ({f.get('type', 'text')})"
                                 + (f" — selector: {f_sel}" if f_sel else ""))

        # Workflows from page analysis
        for wf in (page.workflows or [])[:5]:
            wf_name = wf.get("name", "") if isinstance(wf, dict) else str(wf)
            if wf_name:
                lines.append(f"\nWORKFLOW: {wf_name}")
                if isinstance(wf, dict):
                    stages = wf.get("stages", [])
                    for stage in stages[:5]:
                        step = stage.get("step", "") if isinstance(stage, dict) else str(stage)
                        action = stage.get("action", "") if isinstance(stage, dict) else ""
                        if action:
                            lines.append(f"  {step}. {action}")

        # ── Pattern Intelligence Sections ─────────────────────────────────────

        # Icon-based action buttons in table rows
        if action_icons:
            lines.append("\nACTION COLUMN ICONS (discovered in table rows):")
            for action_type, info in action_icons.items():
                icon_only = " (icon-only button)" if info.get("is_icon_only") else ""
                lines.append(
                    f"  {action_type.upper()}: \"{info.get('label', action_type)}\""
                    + (f" — selector: {info['selector']}" if info.get("selector") else "")
                    + icon_only
                )

        # Status workflow tabs
        status_tabs_found = [t for t in (status_tabs or []) if t.get("is_status_tab")]
        if status_tabs_found:
            labels = [t["label"] for t in status_tabs_found]
            lines.append(f"\nSTATUS WORKFLOW TABS: {', '.join(labels)}")
            for tab in status_tabs_found:
                sel = tab.get("selector", "")
                active_marker = " [currently active]" if tab.get("is_active") else ""
                lines.append(
                    f"  Tab: \"{tab['label']}\""
                    + (f" — selector: {sel}" if sel else "")
                    + active_marker
                )

        # Bulk delete pattern
        if bulk_delete_pattern and bulk_delete_pattern.get("pattern") == "bulk_select_actions_menu":
            lines.append("\nBULK DELETE PATTERN:")
            lines.append("  Pattern: Select row checkbox → Actions button → Delete menu item")
            for step in bulk_delete_pattern.get("steps", []):
                action = step.get("action", "")
                desc = step.get("description", "")
                sel = step.get("selector", "")
                lines.append(f"  Step [{action}]: {desc}" + (f" — selector: {sel}" if sel else ""))
            if bulk_delete_pattern.get("confirm_dialog_expected"):
                lines.append("  NOTE: A confirmation dialog is expected before deletion completes.")

        # Approval workflow
        if approve_pattern and approve_pattern.get("pattern") not in (None, "none_found"):
            pattern_type = approve_pattern.get("pattern", "")
            lines.append(f"\nAPPROVAL WORKFLOW (pattern: {pattern_type}):")
            pending_tab = approve_pattern.get("pending_tab", "")
            approved_tab = approve_pattern.get("approved_tab", "")
            if pending_tab:
                lines.append(f"  Source tab: \"{pending_tab}\" (where pending entries live)")
            if approved_tab:
                lines.append(f"  Target tab: \"{approved_tab}\" (where approved entries appear)")
            approve_sel = approve_pattern.get("approve_selector", "")
            approve_label = approve_pattern.get("approve_label", "Approve")
            if approve_sel:
                lines.append(f"  Approve action: \"{approve_label}\" — selector: {approve_sel}")
            workflow = approve_pattern.get("workflow", "")
            if workflow:
                lines.append("  Workflow steps:")
                for wf_line in workflow.splitlines():
                    lines.append(f"    {wf_line.strip()}")
            lines.append("  VERIFICATION: After approving, entry must appear in the approved/active tab.")

        # Search no-data state
        if search_no_data:
            lines.append("\nSEARCH NO-RESULTS STATE:")
            search_sel = search_no_data.get("search_selector", "")
            btn_sel = search_no_data.get("search_button_selector", "")
            msg = search_no_data.get("no_results_message", "")
            if search_sel:
                lines.append(f"  Search input selector: {search_sel}")
            if btn_sel:
                lines.append(f"  Search button selector: {btn_sel}")
            if msg:
                lines.append(f"  No-results message: \"{msg[:200]}\"")
            lines.append("  TEST: Type an impossible string, verify no-results message appears, then clear.")

        # ── End Pattern Intelligence ───────────────────────────────────────────

        guide_text = "\n".join(lines)

        chunk = AIMemoryChunk(
            application_id=self._app.id,
            kind=MemoryKind.WORKFLOW,
            content=guide_text,
            extra={
                "guide_type": "interaction",
                "module_id": module_id,
                "module_name": module_name,
                "page_url": page.url or "",
                "source": "exploration",
                "session_id": self._session_id,
            },
            confidence=0.95,
        )
        self.db.add(chunk)
        await self.db.commit()

    async def _get_options_via_field_inspector(self, label: str) -> list[dict]:
        """
        Enumerate options for a dynamic dropdown field by its visible label text.
        Strips placeholder options (e.g. 'Select Location') from the returned list.
        """
        try:
            from app.intelligence.field_inspector import FieldInspector
            inspector = FieldInspector(self._browser.driver)
            trigger = await asyncio.to_thread(inspector._find_trigger_by_label, label)
            if trigger is None:
                return []
            options = await asyncio.to_thread(inspector.get_options, trigger)
            # Filter out placeholder options so they are never auto-selected or shown to users
            real = [o for o in options if not o.is_placeholder]
            return [o.to_dict() for o in real]
        except Exception as e:
            log.debug("FieldInspector enumeration failed", label=label, error=str(e))
        return []

    async def _select_via_field_inspector(self, field_label: str, option_label: str) -> bool:
        """Select a specific option from a dynamic dropdown field using smart interaction."""
        try:
            from app.intelligence.field_inspector import FieldInspector
            inspector = FieldInspector(self._browser.driver)
            trigger = await asyncio.to_thread(inspector._find_trigger_by_label, field_label)
            if trigger is None:
                return False
            result = await asyncio.to_thread(inspector.smart_select, trigger, option_label)
            if result.success:
                await self._log("INFO", "login",
                    f"Smart select: {result.field_type} | strategy={result.option_strategy} "
                    f"| method={result.selection_method} | selected={result.selected_label!r}")
            return result.success
        except Exception as e:
            log.debug("FieldInspector smart_select failed",
                      field=field_label, option=option_label, error=str(e))
        return False

    async def _enrich_forms_with_field_options(self, page_analysis: dict) -> dict:
        """
        Scan the current page with FieldInspector and attach discovered options
        to form fields identified by AI analysis, enriching test generation data.
        """
        try:
            from app.intelligence.field_inspector import FieldInspector
            inspector = FieldInspector(self._browser.driver)
            page_fields = await asyncio.to_thread(inspector.get_all_page_fields)
            if not page_fields:
                return page_analysis

            # Build lookup: normalised label → options
            field_opts: dict[str, list[dict]] = {}
            for f in page_fields:
                lbl = (f.get("label") or f.get("trigger_text") or "").strip().lower()
                if lbl and f.get("options"):
                    field_opts[lbl] = f["options"]

            # Merge into AI-discovered form fields
            for form in page_analysis.get("forms", []):
                for field in form.get("fields", []):
                    flbl = (field.get("label") or "").strip().lower()
                    if flbl in field_opts:
                        field["options"] = field_opts[flbl]

            # Store the raw field scan for test-plan generation
            if page_fields:
                page_analysis["discovered_fields"] = page_fields

        except Exception as e:
            log.debug("Form field enrichment failed", error=str(e))
        return page_analysis

    async def _ai_assisted_login(self, base_url: str, username: str, password: str, state: dict) -> bool:
        """
        JavaScript-based login for non-standard forms (Angular, React, Shadow DOM, etc.).
        Returns True only if login actually succeeds (browser leaves the login page).
        """
        await self._log("INFO", "login", "Analyzing login page structure with AI assistance")

        # Strategy 1: JS injection — pierces Shadow DOM and framework-wrapped inputs
        filled = await asyncio.to_thread(self._js_fill_login_form, username, password)
        if filled:
            await self._log("INFO", "login", "Login form filled via JS — submitting")
            await asyncio.sleep(0.5)
            await asyncio.to_thread(self._js_submit_login)
            await asyncio.sleep(4)
            if not await asyncio.to_thread(self._is_login_page):
                await self._log("SUCCESS", "login", "AI-assisted login successful")
                return True
            # Filled but browser didn't navigate — try clicking a submit button explicitly
            await asyncio.to_thread(self._click_submit_button_any)
            await asyncio.sleep(3)
            if not await asyncio.to_thread(self._is_login_page):
                await self._log("SUCCESS", "login", "AI-assisted login successful after button click")
                return True

        # Strategy 2: Raw Selenium keyboard input — last resort
        await self._log("INFO", "login", "Trying keyboard-based login as fallback")
        try:
            keyboard_ok = await asyncio.to_thread(self._keyboard_login, username, password)
            if keyboard_ok:
                await asyncio.sleep(4)
                if not await asyncio.to_thread(self._is_login_page):
                    await self._log("SUCCESS", "login", "Keyboard login successful")
                    return True
        except Exception as e:
            await self._log("WARNING", "login", f"Keyboard login error: {str(e)[:80]}")

        await self._log("WARNING", "login",
            "Could not complete login — credentials may be incorrect or the login form "
            "uses an unsupported UI pattern (Shadow DOM, canvas, or CAPTCHA)")
        return False

    def _js_fill_login_form(self, username: str, password: str) -> bool:
        """
        Fill login form via JavaScript — works for Angular, React, Vue, and Shadow DOM.
        Triggers all framework event listeners so controlled inputs pick up the values.
        """
        return bool(self._browser.execute_script("""
            const username = arguments[0];
            const password = arguments[1];

            function triggerFrameworkEvents(el) {
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
                el.dispatchEvent(new Event('blur', {bubbles: true}));
                // React: bypass controlled component by calling native setter
                try {
                    const setter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    );
                    if (setter && setter.set) { setter.set.call(el, el.value); }
                    el.dispatchEvent(new Event('input', {bubbles: true}));
                } catch(e) {}
            }

            function fillInput(el, value) {
                try { el.focus(); el.value = value; triggerFrameworkEvents(el); return true; }
                catch(e) { return false; }
            }

            function findInputs(root) {
                if (!root) return { user: null, pw: null };
                let userField = null, pwField = null;
                try { pwField = root.querySelector('input[type="password"]'); } catch(e) {}
                const userSelectors = [
                    'input[type="email"]',
                    'input[name*="user" i]', 'input[id*="user" i]',
                    'input[name*="email" i]', 'input[id*="email" i]',
                    'input[placeholder*="user" i]', 'input[placeholder*="email" i]',
                    'input[type="text"]',
                    'input:not([type="password"]):not([type="hidden"]):not([type="submit"])',
                ];
                for (const sel of userSelectors) {
                    try {
                        const el = root.querySelector(sel);
                        if (el && !el.disabled && el.type !== 'hidden') { userField = el; break; }
                    } catch(e) {}
                }
                // Recurse into open Shadow DOM roots
                if (!userField || !pwField) {
                    try {
                        for (const el of root.querySelectorAll('*')) {
                            if (el.shadowRoot) {
                                const sub = findInputs(el.shadowRoot);
                                if (!userField && sub.user) userField = sub.user;
                                if (!pwField && sub.pw) pwField = sub.pw;
                                if (userField && pwField) break;
                            }
                        }
                    } catch(e) {}
                }
                return { user: userField, pw: pwField };
            }

            const { user, pw } = findInputs(document);
            if (!pw) return false;
            if (user) fillInput(user, username);
            fillInput(pw, password);
            return true;
        """, username, password))

    def _js_submit_login(self) -> bool:
        """Submit the login form via JavaScript — tries submit buttons, then Enter keypress."""
        return bool(self._browser.execute_script("""
            // Prefer visible submit buttons inside a form
            const submitCandidates = Array.from(document.querySelectorAll(
                'button[type="submit"], input[type="submit"], button:not([type="button"]):not([type="reset"])'
            )).filter(el => {
                const r = el.getBoundingClientRect();
                return r.width > 0 && r.height > 0
                    && getComputedStyle(el).display !== 'none' && !el.disabled;
            });
            if (submitCandidates.length > 0) { submitCandidates[0].click(); return true; }

            // Any button whose text matches login keywords
            for (const btn of document.querySelectorAll('button,[role="button"],a')) {
                const t = (btn.textContent || btn.value || '').trim().toLowerCase();
                if (['sign in','log in','login','signin','submit','ok','continue'].some(k => t === k || t.includes(k))) {
                    btn.click(); return true;
                }
            }

            // Dispatch Enter on the password field (triggers Angular/React form handlers)
            const pw = document.querySelector('input[type="password"]');
            if (pw) {
                pw.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', keyCode:13, bubbles:true, cancelable:true}));
                pw.dispatchEvent(new KeyboardEvent('keyup', {key:'Enter', keyCode:13, bubbles:true}));
                const form = pw.closest('form');
                if (form) { try { form.submit(); } catch(e) {} }
                return true;
            }
            return false;
        """))

    def _click_submit_button_any(self) -> bool:
        """Try clicking login submit button via Selenium healer as a Selenium-level fallback."""
        # Fast path: JS search (instant, no timeout waits)
        clicked = self._browser.execute_script("""
            const labels = ["Sign In", "Login", "Log In", "Submit", "SIGN IN", "LOG IN", "LOGIN", "Continue"];
            const buttons = Array.from(document.querySelectorAll('button, a[role="button"], input[type="submit"]'));
            for (const btn of buttons) {
                const text = btn.textContent.trim().toLowerCase();
                if (labels.some(l => text.includes(l.toLowerCase()) || text === l.toLowerCase()) && btn.offsetHeight > 0) {
                    btn.click();
                    return true;
                }
            }
            return false;
        """)
        if clicked:
            return True

        # Fallback: healer with all variants in one combined query
        LOGIN_BTN_LABELS = ["Sign In", "Sign in", "signin", "Log In", "Log in",
                            "Login", "login", "LOG IN", "SIGN IN", "Submit", "Continue"]
        result = self._healer.find_element_any(LOGIN_BTN_LABELS)
        if result[0]:
            try:
                result[0].click()
                return True
            except Exception:
                try:
                    self._browser.execute_script("arguments[0].click()", result[0])
                    return True
                except Exception:
                    pass
        return False

    def _keyboard_login(self, username: str, password: str) -> bool:
        """
        Fill login form using raw Selenium find_elements — handles cases where JS injection
        can't locate inputs (e.g. inputs inside iframes or complex ARIA widgets).
        Does NOT filter by is_displayed() so Angular Material hidden inputs are included.
        """
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        SKIP_TYPES = {"hidden", "submit", "button", "checkbox", "radio", "file", "image"}

        def try_in_context(driver_ctx) -> bool:
            try:
                all_inputs = driver_ctx.find_elements(By.TAG_NAME, "input")
                usable = [
                    el for el in all_inputs
                    if (el.get_attribute("type") or "text").lower() not in SKIP_TYPES
                ]
                if not usable:
                    return False
                non_pw = [el for el in usable if (el.get_attribute("type") or "text").lower() != "password"]
                pw_inputs = [el for el in usable if (el.get_attribute("type") or "").lower() == "password"]
                if non_pw:
                    try:
                        non_pw[0].clear()
                        non_pw[0].send_keys(username)
                    except Exception:
                        pass
                if pw_inputs:
                    try:
                        pw_inputs[0].clear()
                        pw_inputs[0].send_keys(password)
                        pw_inputs[0].send_keys(Keys.RETURN)
                        return True
                    except Exception:
                        pass
            except Exception:
                pass
            return False

        # Try main document
        if try_in_context(self._browser.driver):
            return True

        # Try iframes
        try:
            iframes = self._browser.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes[:5]:
                try:
                    self._browser.driver.switch_to.frame(iframe)
                    if try_in_context(self._browser.driver):
                        return True
                except Exception:
                    pass
                finally:
                    try:
                        self._browser.driver.switch_to.default_content()
                    except Exception:
                        pass
        except Exception:
            pass

        return False

    def _wait_for_angular_stable(self, timeout: float = 30.0) -> bool:
        """
        Wait until Angular's Zone.js reports that all async operations are settled.
        Returns True if Angular stabilised within the timeout (or if not an Angular app).
        """
        import time as _time
        # Fast-path: not an Angular app
        try:
            is_ng = self._browser.execute_script(
                "return typeof window.getAllAngularTestabilities === 'function';"
            )
        except Exception:
            return True
        if not is_ng:
            return True

        deadline = _time.time() + timeout
        while _time.time() < deadline:
            try:
                stable = self._browser.execute_script("""
                    try {
                        const testabilities = window.getAllAngularTestabilities();
                        if (!testabilities || testabilities.length === 0) return true;
                        return testabilities.every(function(t) { return t.isStable(); });
                    } catch(e) { return true; }
                """)
                if stable:
                    return True
            except Exception:
                return True
            _time.sleep(0.5)
        return False  # timed out, but we'll still try looking for inputs

    def _count_inputs_js(self) -> int:
        """
        Count visible-or-enabled form inputs via JavaScript.
        Covers: standard <input>, contenteditable, Angular/Ionic/Web Component shadow roots.
        """
        try:
            return int(self._browser.execute_script("""
                function countIn(root) {
                    if (!root) return 0;
                    let n = 0;
                    try {
                        // Standard inputs (skip hidden/submit/button/file/checkbox/radio)
                        const SKIP = new Set(['hidden','submit','button','image','reset']);
                        for (const el of root.querySelectorAll('input')) {
                            if (!SKIP.has((el.type || 'text').toLowerCase())) n++;
                        }
                        // contenteditable elements used as rich text inputs
                        n += root.querySelectorAll('[contenteditable="true"]').length;
                        // Recurse into open shadow roots (Angular ViewEncapsulation.ShadowDom,
                        // Ionic, Lit, etc.)
                        for (const el of root.querySelectorAll('*')) {
                            if (el.shadowRoot) n += countIn(el.shadowRoot);
                        }
                    } catch(e) {}
                    return n;
                }
                return countIn(document);
            """) or 0)
        except Exception:
            return 0

    def _wait_for_any_input(self, timeout: int = 30) -> bool:
        """
        Block until at least one <input> element appears in the DOM, iframes, or Shadow DOM.
        Returns True as soon as one is found; False if timeout expires.
        """
        from selenium.webdriver.common.by import By
        import time as _time

        # For Angular SPAs: wait up to min(timeout, 30s) for the framework to be stable
        # before we start polling. This avoids false negatives where the component has
        # not yet been rendered by Angular's change detection.
        ng_wait = min(timeout, 30)
        self._wait_for_angular_stable(timeout=ng_wait)

        deadline = _time.time() + timeout
        while _time.time() < deadline:
            # Strategy 1: standard Selenium find_elements
            try:
                inputs = self._browser.driver.find_elements(By.TAG_NAME, "input")
                if inputs:
                    return True
            except Exception:
                pass

            # Strategy 2: broad JS scan (covers Shadow DOM + contenteditable)
            try:
                if self._count_inputs_js() > 0:
                    return True
            except Exception:
                pass

            # Strategy 3: iframe scan every ~2s
            if int(_time.time() * 2) % 4 == 0:
                try:
                    iframes = self._browser.driver.find_elements(By.TAG_NAME, "iframe")
                    for iframe in iframes[:3]:
                        try:
                            self._browser.driver.switch_to.frame(iframe)
                            inputs = self._browser.driver.find_elements(By.TAG_NAME, "input")
                            self._browser.driver.switch_to.default_content()
                            if inputs:
                                return True
                        except Exception:
                            try:
                                self._browser.driver.switch_to.default_content()
                            except Exception:
                                pass
                except Exception:
                    pass
            _time.sleep(0.5)
        return False

    def _try_navigate_to_login_page(self, base_url: str) -> bool:
        """
        Recovery: when no inputs found on the landing page, try to reach the login form by:
        1. Clicking visible Login / Sign In links or buttons
        2. Navigating to common Angular hash/path routes
        Returns True if inputs appear after the navigation attempt.
        """
        from selenium.webdriver.common.by import By
        import time as _time

        # Step 1: click any visible Login / Sign In element
        login_labels = ["Login", "Sign In", "Log In", "Sign in", "GET STARTED",
                        "Enter Portal", "Access", "Go to Login"]
        for label in login_labels:
            try:
                els = self._browser.driver.find_elements(
                    By.XPATH,
                    f'//*[normalize-space(.)="{label}" or @aria-label="{label}"]'
                )
                for el in els:
                    try:
                        if el.tag_name in ("a", "button") or el.get_attribute("role") in ("button", "link"):
                            self._browser.execute_script("arguments[0].click()", el)
                            _time.sleep(2.5)
                            if self._browser.driver.find_elements(By.TAG_NAME, "input"):
                                return True
                    except Exception:
                        pass
            except Exception:
                pass

        # Step 2: try common Angular / SPA login routes
        clean_base = base_url.rstrip("/")
        login_paths = [
            "/#/login", "/login", "/#login", "/auth/login", "/#/auth",
            "/account/login", "/#/account/login", "/users/sign_in",
            "/#/sign-in", "/sign-in",
        ]
        for path in login_paths:
            try:
                target = clean_base + path
                self._browser.navigate(target)
                _time.sleep(2)
                if self._browser.driver.find_elements(By.TAG_NAME, "input") or self._count_inputs_js() > 0:
                    return True
            except Exception:
                pass

        return False

    def _count_page_inputs(self) -> int:
        """Count all form inputs on the page (Shadow DOM, contenteditable, and iframes included)."""
        from selenium.webdriver.common.by import By
        # Use the improved JS-based counter first (covers Shadow DOM and contenteditable)
        js_count = self._count_inputs_js()
        if js_count > 0:
            return js_count
        # Fallback: legacy iframe scan
        count = 0
        try:
            count += len(self._browser.driver.find_elements(By.TAG_NAME, "input"))
            iframes = self._browser.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes[:5]:
                try:
                    self._browser.driver.switch_to.frame(iframe)
                    count += len(self._browser.driver.find_elements(By.TAG_NAME, "input"))
                except Exception:
                    pass
                finally:
                    try:
                        self._browser.driver.switch_to.default_content()
                    except Exception:
                        pass
        except Exception:
            pass
        return count

    async def _try_two_step_login(self, username_el, username: str, password: str, state: dict):
        """
        Handle two-step login flows where password field appears after submitting username.
        Returns True (logged in), False (failed), or None (not a two-step flow — caller
        should fall through to the standard single-page login path).
        """
        from selenium.webdriver.common.keys import Keys

        await self._log("INFO", "login", "Two-step login: filling username field")
        await asyncio.to_thread(self._fill_login_field, username_el, username)
        await asyncio.sleep(0.3)

        # Try pressing Enter or clicking a "Next" / "Continue" button
        clicked_next = False
        result = self._healer.find_element_any(
            ["Next", "Continue", "Proceed", "Sign In", "Sign in", "Login", "Log In"]
        )
        if result[0]:
            try:
                result[0].click()
                clicked_next = True
                await self._log("INFO", "login", f"Two-step login: clicked button via combined search")
            except Exception:
                pass
        if not clicked_next:
            try:
                username_el.send_keys(Keys.RETURN)
                clicked_next = True
                await self._log("INFO", "login", "Two-step login: pressed Enter on username field")
            except Exception:
                pass

        if not clicked_next:
            return None  # can't advance — not a two-step flow we can handle

        # Wait for the password field to appear (up to 8s)
        pw_appeared = await asyncio.to_thread(self._wait_for_password_field, timeout=8)
        if not pw_appeared:
            await self._log("WARNING", "login",
                "Two-step login: password field did not appear after username submission")
            return None  # fall through to JS/keyboard approaches

        # Find password field (and possibly a fresh username field)
        _, password_el = await asyncio.to_thread(self._find_login_fields_fast)
        if not password_el:
            return None

        await self._log("INFO", "login", "Two-step login: password field appeared — filling")
        await asyncio.to_thread(self._fill_login_field, password_el, password)
        await asyncio.sleep(0.3)

        # Submit — try all common variants in one combined query
        LOGIN_BTN_LABELS = ["Sign In", "Sign in", "signin", "Log In", "Log in",
                            "Login", "login", "LOG IN", "SIGN IN", "Submit", "Next", "Continue"]
        login_button = self._healer.find_element_any(LOGIN_BTN_LABELS)
        if login_button[0]:
            self._healer.click_with_healing(login_button[0])
        else:
            try:
                password_el.send_keys(Keys.RETURN)
            except Exception:
                await asyncio.to_thread(self._js_submit_login)

        await asyncio.sleep(4)
        if not await asyncio.to_thread(self._is_login_page):
            await self._log("SUCCESS", "login", "Two-step login successful")
            return True

        await self._log("WARNING", "login", "Two-step login: still on login page after submission")
        return False

    def _wait_for_password_field(self, timeout: int = 8) -> bool:
        """Poll until a password input appears in the DOM. Returns True when found."""
        from selenium.webdriver.common.by import By
        import time as _time
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            try:
                pw_fields = self._browser.driver.find_elements(
                    By.CSS_SELECTOR, 'input[type="password"]'
                )
                if pw_fields:
                    return True
            except Exception:
                pass
            _time.sleep(0.5)
        return False

    def _find_login_fields_fast(self):
        """
        Fast login field detection.
        Returns (username_el, password_el). Either may be None.

        Handles: standard HTML inputs, Angular Material / ViewEncapsulation.ShadowDom,
        iframes, hidden-but-enabled inputs, and contenteditable-based fields.
        """
        from selenium.webdriver.common.by import By

        SKIP_TYPES = {"hidden", "submit", "button", "checkbox", "radio", "file", "image"}

        def scan_inputs(driver_or_context):
            pw_el = None
            user_el = None
            try:
                all_inputs = driver_or_context.find_elements(By.TAG_NAME, "input")
                for inp in all_inputs:
                    try:
                        typ = (inp.get_attribute("type") or "text").lower()
                        if typ in SKIP_TYPES:
                            continue
                        if typ == "password" and pw_el is None:
                            pw_el = inp
                        elif typ != "password" and user_el is None:
                            user_el = inp
                        if pw_el and user_el:
                            break
                    except Exception:
                        continue
            except Exception:
                pass
            return user_el, pw_el

        # 1) Try standard Selenium find_elements on main document
        user_el, pw_el = scan_inputs(self._browser.driver)
        if pw_el:
            return user_el, pw_el

        # 2) Try JS-based search including open Shadow DOM roots
        #    Returns [username_element, password_element] or null pairs via JS
        try:
            result = self._browser.execute_script("""
                const SKIP = new Set(['hidden','submit','button','image','reset','checkbox','radio','file']);
                function findFields(root) {
                    let userEl = null, pwEl = null;
                    if (!root) return [userEl, pwEl];
                    // password first (unambiguous)
                    try { pwEl = root.querySelector('input[type="password"]'); } catch(e) {}
                    // username: try specific selectors in priority order
                    const userSelectors = [
                        'input[type="email"]',
                        'input[name*="user" i]', 'input[id*="user" i]', 'input[name*="login" i]',
                        'input[name*="email" i]', 'input[id*="email" i]',
                        'input[placeholder*="user" i]', 'input[placeholder*="email" i]',
                        'input[type="text"]',
                        'input:not([type="password"]):not([type="hidden"]):not([type="submit"])',
                    ];
                    for (const sel of userSelectors) {
                        try {
                            const el = root.querySelector(sel);
                            if (el && !el.disabled && !SKIP.has((el.type||'text').toLowerCase())) {
                                userEl = el; break;
                            }
                        } catch(e) {}
                    }
                    // Recurse into open shadow roots
                    if (!pwEl || !userEl) {
                        try {
                            for (const el of root.querySelectorAll('*')) {
                                if (el.shadowRoot) {
                                    const [su, sp] = findFields(el.shadowRoot);
                                    if (!userEl && su) userEl = su;
                                    if (!pwEl   && sp) pwEl   = sp;
                                    if (userEl && pwEl) break;
                                }
                            }
                        } catch(e) {}
                    }
                    return [userEl, pwEl];
                }
                return findFields(document);
            """)
            if result and result[1]:  # password element found
                return result[0], result[1]
        except Exception:
            pass

        # 3) Try each iframe — Angular / legacy apps often render login inside iframes
        try:
            iframes = self._browser.driver.find_elements(By.TAG_NAME, "iframe")
            for iframe in iframes[:5]:
                try:
                    self._browser.driver.switch_to.frame(iframe)
                    user_el, pw_el = scan_inputs(self._browser.driver)
                    if pw_el:
                        return user_el, pw_el
                except Exception:
                    pass
                finally:
                    try:
                        self._browser.driver.switch_to.default_content()
                    except Exception:
                        pass
        except Exception:
            pass

        return None, None

    def _fill_login_field(self, el, value: str) -> None:
        """
        Fill an input using JS native setter + framework events (Angular/React compatible).
        Falls back to Selenium .clear() + send_keys() if JS fails.
        """
        try:
            self._browser.execute_script("""
                const el = arguments[0];
                const value = arguments[1];
                try {
                    const nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLInputElement.prototype, 'value'
                    );
                    if (nativeSetter && nativeSetter.set) {
                        nativeSetter.set.call(el, value);
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

    async def _phase_discover_modules(self):
        """Phase 2: Discover main application modules from navigation."""
        await self._log("MILESTONE", "navigation", "Discovering application modules and navigation structure")

        # Guard: if browser is still on login page, login has failed silently — abort phase
        if await asyncio.to_thread(self._is_login_page):
            await self._log("WARNING", "navigation",
                "Browser is still on the login page — skipping module discovery")
            return

        # Use a deep JS scan to get ALL nav items (direct links + accordion children)
        # without clicking anything. This avoids navigation side-effects that
        # cause child detection to fail.
        all_nav_items = await asyncio.to_thread(self._scan_full_nav_structure)

        # Diagnostic: log breakdown so we can see if accordion children were found
        parents = [i for i in all_nav_items if not i.get("parent")]
        children = [i for i in all_nav_items if i.get("parent")]
        await self._log("INFO", "navigation",
            f"Nav scan: {len(parents)} top-level items, {len(children)} accordion children = {len(all_nav_items)} total")

        if not all_nav_items:
            # Fallback to extractor if JS scan found nothing
            state = self._extractor.extract_page_state()
            raw = state.get("navigation", {}).get("items", [])
            all_nav_items = [{"text": i.get("text",""), "href": i.get("href",""), "parent": None} for i in raw if i.get("text","").strip()]

        if all_nav_items:
            await self._log("INFO", "navigation",
                f"Navigation scan found {len(all_nav_items)} total items (including accordion children)")

            for item in all_nav_items:
                text = item.get("text", "").strip()
                href = item.get("href", "").strip()
                parent = item.get("parent")

                if not text or len(text) > 100:
                    continue

                # Use hierarchical name for child items
                display_name = f"{parent} / {text}" if parent else text

                module = ApplicationModule(
                    application_id=self._app.id,
                    name=display_name,
                    description="",
                    url_pattern=href,
                    icon="layout",
                    semantic_tags=[],
                    order_index=len(self._module_map),
                )
                self.db.add(module)
                await self.db.flush()
                if href:
                    self._module_map[href] = module.id

                await self._log("SUCCESS", "navigation", f"Module discovered: {display_name}")

            # Store for Phase 2b
            self._raw_nav_items = all_nav_items
            await self._log("INFO", "navigation",
                f"Complete nav item list: {len(all_nav_items)} items (parents + children)")

            await self.db.commit()
        else:
            await self._log("WARNING", "navigation", "No navigation structure detected — trying page analysis")
            await self._discover_modules_from_links()
            # If no modules from links, try extracting visible items (sidebar menu, tiles, etc.)
            modules_found = await self._count_modules(self._app.id)
            if modules_found == 0:
                await self._discover_modules_from_visible_items()

    def _scan_full_nav_structure(self) -> list[dict]:
        """
        Scan the sidebar nav DOM for ALL items including hidden accordion children.

        Strategy:
          1. Find the sidebar container by looking for the element that contains
             most of the app's <a> links (most likely candidate = sidebar).
          2. Walk every <button> in that container — if its next sibling has
             any <a> descendants (accordion pattern), collect them as children.
          3. Collect remaining direct <a> links that aren't inside accordion groups.

        Works without relying on container class names (avoids isInNav() failures).
        """
        return self._browser.execute_script("""
        (function() {
            function getText(el) {
                // Prefer direct text nodes (avoids pulling in child icon text)
                let t = '';
                for (const n of el.childNodes) {
                    if (n.nodeType === 3) t += n.textContent;
                }
                t = t.trim().replace(/\\s+/g, ' ');
                if (!t) t = (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\\s+/g, ' ');
                return t.slice(0, 80);
            }

            function isVisible(el) {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            }

            const NOISE = new Set([
                'logout','log out','sign out','notifications','help','about',
                'search','close','toggle','collapse','expand','back','next','previous'
            ]);

            // ── Step 1: Find the sidebar container ──────────────────────────
            // Pick the container that owns the most internal <a href> links.
            // Skip <header>, <footer>, <main> — those are content, not nav.
            let sidebar = null;
            let maxLinks = 0;
            const SKIP_TAGS = new Set(['header','footer','main','form','table']);

            for (const el of document.querySelectorAll('div, section, nav, aside, ul')) {
                if (SKIP_TAGS.has(el.tagName.toLowerCase())) continue;
                const r = el.getBoundingClientRect();
                if (!isVisible(el)) continue;
                const viewW = window.innerWidth || 1280;
                // Allow sidebars up to 50% viewport width; exclude full-width main content
                if (r.width < 30 || r.width > viewW * 0.5) continue;
                // Allow sidebars anywhere in the left 60% of viewport
                if (r.left > viewW * 0.6) continue;
                const linkCount = el.querySelectorAll('a[href]').length;
                if (linkCount > maxLinks) {
                    maxLinks = linkCount;
                    sidebar = el;
                }
            }

            // Fallback: no narrow sidebar found — try nav/aside anywhere
            if (!sidebar || maxLinks < 3) {
                for (const el of document.querySelectorAll('nav, aside, [role="navigation"]')) {
                    if (!isVisible(el)) continue;
                    const linkCount = el.querySelectorAll('a[href]').length;
                    if (linkCount > maxLinks) {
                        maxLinks = linkCount;
                        sidebar = el;
                    }
                }
            }

            const root = sidebar || document.body;
            const results = [];
            const seen = new Set();
            // Track which <a> elements are already claimed by an accordion parent
            const claimedAnchors = new Set();

            // ── Step 2: Accordion buttons with hidden children ───────────────
            // A button whose next sibling contains <a> links = accordion parent.
            for (const btn of root.querySelectorAll('button')) {
                const text = getText(btn);
                if (!text || text.length < 2 || NOISE.has(text.toLowerCase())) continue;
                if (seen.has(text.toLowerCase())) continue;

                // Find sibling container (next element sibling, or parent's next sibling)
                let container = btn.nextElementSibling;
                // Some frameworks wrap button+panel in a shared parent — look one level up too
                if (!container || container.querySelectorAll('a').length === 0) {
                    const parentNext = btn.parentElement && btn.parentElement.nextElementSibling;
                    if (parentNext && parentNext.querySelectorAll('a').length > 0) {
                        container = parentNext;
                    }
                }

                if (!container) continue;

                // Collect ALL <a> descendants (even hidden in collapsed grid-rows-[0fr])
                const anchors = Array.from(container.querySelectorAll('a'));
                if (anchors.length === 0) continue;

                const children = [];
                for (const a of anchors) {
                    const childText = getText(a);
                    if (!childText || childText.length < 2 || NOISE.has(childText.toLowerCase())) continue;
                    const href = a.getAttribute('href') || '';
                    children.push({ text: childText, href: href, parent: text });
                    claimedAnchors.add(a);
                }

                if (children.length > 0) {
                    seen.add(text.toLowerCase());
                    // Add parent (without href — it's an expander, not a link)
                    results.push({ text: text, href: '', parent: null, isAccordion: true });
                    // Add all children
                    for (const child of children) {
                        const key = child.text.toLowerCase();
                        if (!seen.has(key)) {
                            seen.add(key);
                            results.push(child);
                        }
                    }
                }
            }

            // ── Step 3: Direct <a> links not part of any accordion ───────────
            for (const a of root.querySelectorAll('a[href]')) {
                if (claimedAnchors.has(a)) continue;
                if (!isVisible(a)) continue;
                const text = getText(a);
                if (!text || text.length < 2 || NOISE.has(text.toLowerCase())) continue;
                const href = a.getAttribute('href') || '';
                if (!href || href === '#' || href.startsWith('javascript')) continue;
                if (seen.has(text.toLowerCase())) continue;
                seen.add(text.toLowerCase());
                results.push({ text: text, href: href, parent: null });
            }

            return results;
        })()
        """) or []

    async def _discover_modules_from_nav(self, nav_items: list[dict]):
        """Fallback: create modules directly from nav items."""
        for item in nav_items:
            text = item.get("text", "").strip()
            if text and len(text) < 50:
                module = ApplicationModule(
                    application_id=self._app.id,
                    name=text,
                    url_pattern=item.get("href", ""),
                    semantic_tags=[],
                )
                self.db.add(module)
                await self._log("INFO", "navigation", f"Module found: {text}")
        await self.db.commit()

    async def _discover_modules_from_links(self):
        """Discover modules by analyzing page links."""
        links = self._browser.execute_script("""
            return Array.from(document.querySelectorAll('a[href]'))
                .filter(a => a.href && !a.href.includes('#') && a.textContent.trim())
                .slice(0, 30)
                .map(a => ({text: a.textContent.trim(), href: a.href}));
        """)
        if links:
            await self._discover_modules_from_nav(links or [])

    async def _discover_modules_from_visible_items(self):
        """
        Last-resort module discovery: extract visible text items from the page
        (sidebar menus, tiles, navigation lists that don't use <a> tags) and
        create a module for each distinct item that looks like a module name.
        """
        items = await asyncio.to_thread(self._extract_all_visible_items)
        if not items:
            return

        # Ask AI to identify which items are navigation modules
        prompt = (
            f"Application: {self._app.description or 'Business application'}\n\n"
            f"Visible page items: {items[:40]}\n\n"
            "Which of these are navigation module names (not UI controls)? "
            "Output JSON: {\"modules\": [{\"name\": \"...\", \"description\": \"brief guess\"}]}"
        )
        try:
            response = await asyncio.wait_for(
                self.ai.complete(
                    system="You identify application modules from visible UI text. Output valid JSON only.",
                    user=prompt,
                    fast=True,
                    json_mode=True,
                ),
                timeout=90.0,
            )
            module_data = response.json()
            for mod_info in module_data.get("modules", [])[:20]:
                name = mod_info.get("name", "").strip()
                if not name or len(name) > 80:
                    continue
                module = ApplicationModule(
                    application_id=self._app.id,
                    name=name,
                    description=mod_info.get("description", ""),
                    url_pattern="",
                    icon="layout",
                    semantic_tags=[],
                    order_index=len(self._module_map),
                )
                self.db.add(module)
                await self._log("SUCCESS", "navigation", f"Module discovered from UI: {name}")
            await self.db.commit()
        except Exception as e:
            log.warning("Visible-item module discovery failed", error=str(e))
            # Fallback: create a module for each item that looks like a title
            ui_noise = self._UI_NOISE | {"home", "dashboard", "profile", "notifications", "messages"}
            for item in items[:20]:
                if item.lower() in ui_noise or len(item) > 60 or len(item) < 3:
                    continue
                # Heuristic: looks like a module name if mostly letters and spaces
                if sum(c.isalpha() or c.isspace() for c in item) / max(len(item), 1) > 0.7:
                    module = ApplicationModule(
                        application_id=self._app.id,
                        name=item,
                        description="",
                        url_pattern="",
                        icon="layout",
                        semantic_tags=[],
                        order_index=len(self._module_map),
                    )
                    self.db.add(module)
                    await self._log("INFO", "navigation", f"Module from visible item: {item}")
            await self.db.commit()

    # ─────────────────────────────────────────────────────────────────────────
    # Phase 2b: Click-based real URL capture (handles SPA routing)
    # ─────────────────────────────────────────────────────────────────────────

    async def _capture_real_module_urls(self):
        """
        Phase 2b: Click each nav item to capture real URLs (handles SPA / hash routing).
        Uses nav items stored in Phase 2 so the same selector strategy is reused.
        Updates ApplicationModule.url_pattern with actual navigated URLs.
        """
        await self._log("MILESTONE", "navigation", "Capturing real URLs via click-based navigation")

        # Guard: abort if browser is on the login page (login failed silently)
        if await asyncio.to_thread(self._is_login_page):
            await self._log("WARNING", "navigation",
                "Browser is still on the login page — skipping URL capture")
            return

        try:
            # Snapshot the current full URL (includes hash for SPA apps)
            dashboard_url = await asyncio.to_thread(self._get_full_url)
            base_url = self._app.base_url.rstrip("/")
            url_map: dict[str, str] = {}  # nav text → actual URL

            # Use nav items found in Phase 2 first; fall back to fresh JS scan
            nav_items: list[dict] = self._raw_nav_items or await asyncio.to_thread(
                self._get_nav_items_for_clicking
            )
            if not nav_items:
                await self._log("WARNING", "navigation", "No nav items found — skipping URL capture")
                return

            await self._log("INFO", "navigation",
                f"Probing {len(nav_items)} nav items for real URLs")

            for item in nav_items:
                text = item.get("text", "").strip()
                href = item.get("href", "").strip()
                if not text or len(text) < 2:
                    continue

                # Always click to discover children, even if href exists
                # (expandable nav items may have href AND child items)
                try:
                    before_url = await asyncio.to_thread(self._get_full_url)
                    before_title = await asyncio.to_thread(self._get_page_title)
                    clicked = await asyncio.to_thread(self._click_nav_item, text)
                    if not clicked:
                        # Fallback: use href if available
                        if href and href not in ("#", "/", "javascript:void(0)", "javascript:;"):
                            real_url = href if href.startswith("http") else base_url + href
                            url_map[text] = real_url
                            self._discovered_urls.add(real_url)
                            await self._log("INFO", "navigation", f"Nav href (no-click): {text!r} → {href}")
                        continue
                    await asyncio.sleep(1.5)

                    after_url = await asyncio.to_thread(self._get_full_url)
                    after_title = await asyncio.to_thread(self._get_page_title)
                    on_login = await asyncio.to_thread(self._is_login_page)

                    url_changed = after_url != before_url
                    title_changed = after_title != before_title and not on_login

                    if (url_changed or title_changed) and not on_login:
                        url_map[text] = after_url
                        self._discovered_urls.add(after_url)
                        await self._log("INFO", "navigation", f"Module URL: {text!r} → {after_url}")
                        # Some nav items navigate AND reveal sub-items in the sidebar simultaneously
                        # (common in Angular sidebars with accordion + direct-link behavior)
                        child_texts = await asyncio.to_thread(self._get_revealed_child_items, text)
                        if child_texts:
                            await self._log("INFO", "navigation",
                                f"  {text!r} also revealed {len(child_texts)} sub-items")
                            for child_text in child_texts:
                                child_url = await self._navigate_to_child_item(child_text)
                                if child_url:
                                    url_map[child_text] = child_url
                                    self._discovered_urls.add(child_url)
                                    await self._log("INFO", "navigation",
                                        f"    Sub-item: {child_text!r} → {child_url}")
                            try:
                                await asyncio.to_thread(self._browser.navigate, dashboard_url)
                                await asyncio.sleep(1.0)
                            except Exception:
                                pass
                    else:
                        # Accordion parent that didn't navigate — check for newly revealed child items
                        child_texts = await asyncio.to_thread(self._get_revealed_child_items, text)
                        if child_texts:
                            await self._log("INFO", "navigation",
                                f"Parent {text!r} expanded → {len(child_texts)} children")
                            for child_text in child_texts:
                                child_url = await self._navigate_to_child_item(child_text)
                                if child_url:
                                    url_map[child_text] = child_url
                                    self._discovered_urls.add(child_url)
                                    await self._log("INFO", "navigation",
                                        f"  Child URL: {child_text!r} → {child_url}")
                            # Return to dashboard so next top-level click works
                            try:
                                await asyncio.to_thread(self._browser.navigate, dashboard_url)
                                await asyncio.sleep(1.0)
                            except Exception:
                                pass
                except Exception as e:
                    log.debug("Nav item probe failed", text=text, error=str(e))

            await self._log("INFO", "navigation",
                f"URL capture complete — {len(url_map)} real URLs captured")

            if url_map:
                await self._update_modules_with_real_urls(url_map, base_url)

            # Return to dashboard for Phase 3
            try:
                await asyncio.to_thread(self._browser.navigate, dashboard_url)
                await asyncio.sleep(1.0)
            except Exception:
                pass

        except Exception as e:
            log.warning("capture_real_module_urls failed", error=str(e))
            await self._log("WARNING", "navigation", f"URL capture failed: {str(e)[:100]}")

    def _get_full_url(self) -> str:
        """Return full URL including hash fragment (important for SPA hash routing)."""
        try:
            return self._browser.execute_script("return window.location.href;") or ""
        except Exception:
            return self._browser.get_current_url()

    def _get_page_title(self) -> str:
        """Return current document title."""
        try:
            return self._browser.execute_script("return document.title;") or ""
        except Exception:
            return ""

    def _is_login_page(self) -> bool:
        """
        Determine if the current browser page is the login page.

        Strategy priority:
          1. URL matches the fingerprinted login URL (most reliable, SPA-safe)
          2. Page has rich application navigation → definitely NOT login
          3. DOM password-input / title / URL-keyword checks (works for non-Shadow-DOM apps)
        """
        try:
            current = self._get_full_url()

            # Strategy 1: URL fingerprint — compare stripped URLs to the known login URL
            # Also flag if the page is the base URL (redirect-to-login signal for SPA apps)
            if self._login_url:
                login_clean = self._login_url.split("?")[0].rstrip("/#")
                cur_clean = current.split("?")[0].rstrip("/#")
                if cur_clean == login_clean:
                    return True

            # Also treat app.base_url as a login-redirect signal if different from dashboard
            if self._app and self._dashboard_url:
                base_clean = self._app.base_url.split("?")[0].rstrip("/#")
                cur_clean = current.split("?")[0].rstrip("/#")
                dash_clean = self._dashboard_url.split("?")[0].rstrip("/#")
                if cur_clean == base_clean and dash_clean != base_clean:
                    return True  # redirected back to base URL = not logged in

            # Strategy 2: rich app navigation means we're inside the authenticated app
            has_nav = self._browser.execute_script("""
                // Count application nav links (sidebar, top nav, role=navigation)
                const navLinks = document.querySelectorAll(
                    'nav a, [role="navigation"] a, [role="menuitem"],'
                    + ' .sidebar a, .menu a, aside a, [class*="nav" i] a'
                );
                if (navLinks.length >= 4) return true;
                // Or a data table (authenticated modules show tables)
                if (document.querySelector('table, [role="grid"], [role="table"]')) return true;
                return false;
            """)
            if has_nav:
                return False  # authenticated app page

            # Strategy 3: DOM-level checks (fail-safes for non-Shadow-DOM forms)
            return bool(self._browser.execute_script("""
                // Password input (standard + common attribute variants)
                const pwSels = [
                    'input[type="password"]',
                    'input[name*="password" i]',
                    'input[name*="passwd" i]',
                    'input[placeholder*="password" i]',
                    'input[aria-label*="password" i]',
                ];
                if (pwSels.some(s => { try { return !!document.querySelector(s); } catch(e){return false;} }))
                    return true;

                // Title or URL keyword
                const title = (document.title || '').toLowerCase();
                const href = window.location.href.toLowerCase();
                if (['sign in','log in','login','signin'].some(w => title.includes(w))) return true;
                if (['/login','/signin','/sign-in','#/login','#login'].some(p => href.includes(p))) return true;

                // Visible "Sign In" / "Login" button with no app nav = login page
                const hasLoginBtn = Array.from(document.querySelectorAll(
                    'button, input[type="submit"], [role="button"]'
                )).some(b => {
                    if (!b.offsetParent) return false;
                    const t = (b.textContent || b.value || b.getAttribute('aria-label') || '')
                        .trim().toLowerCase();
                    return ['sign in','log in','login'].includes(t);
                });
                return hasLoginBtn;
            """))
        except Exception:
            return False

    def _get_nav_items_for_clicking(self) -> list[dict]:
        """Extract all clickable nav items with parent/child detection."""
        return self._browser.execute_script("""
        (function() {
            function isVisible(el) {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0
                    && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            }
            function getDirectText(el) {
                let t = '';
                for (const n of el.childNodes) { if (n.nodeType === 3) t += n.textContent; }
                t = t.trim().replace(/\\s+/g, ' ');
                return t || (el.getAttribute('aria-label') || el.textContent || '')
                    .trim().replace(/\\s+/g, ' ').slice(0, 80);
            }

            const NOISE = new Set(['logout','log out','sign out','profile','account',
                'notifications','help','about','home','settings']);
            const NAV_SELS = ['nav', '[role="navigation"]', 'aside', '[role="menubar"]',
                '[class*="sidebar" i]', '[class*="sider" i]', '[class*="menu-bar" i]'];

            let container = null;
            for (const sel of NAV_SELS) {
                for (const el of document.querySelectorAll(sel)) {
                    if (!isVisible(el)) continue;
                    if (el.querySelectorAll('a,li,[role="menuitem"]').length >= 3) {
                        container = el; break;
                    }
                }
                if (container) break;
            }

            const root = container || document.body || document.documentElement;
            if (!root) return [];
            const seen = new Set();
            const results = [];

            for (const el of root.querySelectorAll(
                'a, li, [role="menuitem"], [role="treeitem"], button[class*="nav" i], button[class*="menu" i]'
            )) {
                if (!isVisible(el)) continue;
                const text = getDirectText(el);
                if (!text || text.length < 2 || text.length > 80) continue;
                if (NOISE.has(text.toLowerCase())) continue;
                if (seen.has(text.toLowerCase())) continue;
                seen.add(text.toLowerCase());
                results.push({
                    text,
                    hasExpander: el.hasAttribute('aria-expanded')
                        || el.hasAttribute('aria-haspopup')
                        || !!el.querySelector('[aria-expanded]'),
                });
            }
            return results.slice(0, 40);
        })()
        """) or []

    def _click_nav_item(self, text: str) -> bool:
        """Click a nav item by its visible text. Tries JS then XPath."""
        from selenium.webdriver.common.by import By
        clicked = self._browser.execute_script("""
            const target = arguments[0].toLowerCase().trim();
            function isVisible(el) {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            }
            function getDirectText(el) {
                let t = '';
                for (const n of el.childNodes) { if (n.nodeType === 3) t += n.textContent; }
                return (t.trim() || el.textContent || '').trim().replace(/\\s+/g, ' ').toLowerCase();
            }
            // Search ALL matching containers (querySelectorAll not querySelector)
            // so apps with both header nav + sidebar are both searched.
            const NAV_SELS = [
                'nav','[role="navigation"]','aside','[role="menubar"]',
                '[class*="sidebar" i]','[class*="sidenav" i]','[class*="side-nav" i]',
                '[class*="menu" i]','header','body'
            ];
            const tried = new Set();
            for (const sel of NAV_SELS) {
                for (const container of document.querySelectorAll(sel)) {
                    if (tried.has(container)) continue;
                    tried.add(container);
                    for (const el of container.querySelectorAll(
                        'a, li, [role="menuitem"], [role="treeitem"], button'
                    )) {
                        if (!isVisible(el)) continue;
                        const t = getDirectText(el);
                        if (t === target || t.startsWith(target) || target.startsWith(t)) {
                            el.click();
                            return true;
                        }
                    }
                }
            }
            return false;
        """, text)
        if clicked:
            return True
        # XPath fallback
        for xpath in [
            f"//*[normalize-space(.)='{text}']",
            f"//*[contains(normalize-space(.),'{text}')]",
        ]:
            try:
                from selenium.webdriver.common.by import By
                for el in self._browser.driver.find_elements(By.XPATH, xpath):
                    if el.is_displayed():
                        el.click()
                        return True
            except Exception:
                pass
        return False

    def _snapshot_nav_texts(self) -> set[str]:
        """Return lowercase text of all currently visible nav items (for before/after diff)."""
        items = self._browser.execute_script("""
        (function() {
            const NOISE = new Set(['logout','log out','sign out','profile','account',
                'notifications','help','about','home','settings']);
            function isVisible(el) {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none'
                    && s.visibility !== 'hidden' && s.opacity !== '0';
            }
            function getText(el) {
                let t = '';
                for (const n of el.childNodes) if (n.nodeType === 3) t += n.textContent;
                return (t.trim() || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
            }
            const seen = new Set();
            const results = [];
            for (const el of document.querySelectorAll(
                'nav a, nav li, nav [role="menuitem"], nav [role="treeitem"], aside a, aside li, aside [role="menuitem"]'
            )) {
                if (!isVisible(el)) continue;
                const t = getText(el);
                if (!t || t.length < 2 || t.length > 80 || NOISE.has(t.toLowerCase())) continue;
                if (seen.has(t.toLowerCase())) continue;
                seen.add(t.toLowerCase());
                results.push(t);
            }
            return results;
        })()
        """) or []
        return {t.lower() for t in items}

    def _get_revealed_child_items(self, parent_text: str) -> list[str]:
        """After clicking a parent nav item, collect any newly visible child items.

        Handles collapsible grid structure:
          <button>Parent</button>
          <div class="grid grid-rows-[1fr]">  ← expanded when clicked
            <div class="overflow-hidden">
              <div class="ml-6...">
                <a>Child 1</a>
                <a>Child 2</a>
              </div>
            </div>
          </div>
        """
        return self._browser.execute_script("""
        (function() {
            const parent = arguments[0].toLowerCase().trim();
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            }
            function getDirectText(el) {
                let t = '';
                for (const n of el.childNodes) { if (n.nodeType === 3) t += n.textContent; }
                return (t.trim() || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
            }
            const NOISE = new Set(['logout','sign out','profile','help','about','home','settings','dashboard']);

            // Find the parent BUTTON element by text
            let parentBtn = null;
            for (const btn of document.querySelectorAll('button')) {
                if (!isVisible(btn)) continue;
                const t = getDirectText(btn).toLowerCase().trim();
                if (t === parent || t.startsWith(parent.slice(0, 15))) {
                    parentBtn = btn;
                    break;
                }
            }
            if (!parentBtn) return [];

            // Strategy 1: Next sibling is the grid container (collapsible menu)
            let gridContainer = parentBtn.nextElementSibling;
            if (gridContainer && (gridContainer.classList.contains('grid') || gridContainer.getAttribute('class')?.includes('grid'))) {
                // Found it! Search inside for visible child items
                const seen = new Set([parent]);
                const results = [];
                for (const el of gridContainer.querySelectorAll('a, li, [role="menuitem"], [role="treeitem"]')) {
                    if (!isVisible(el)) continue;
                    const t = getDirectText(el).toLowerCase().trim();
                    if (!t || t.length < 2 || t.length > 80) continue;
                    if (NOISE.has(t) || seen.has(t) || t === parent) continue;
                    seen.add(t);
                    results.push(getDirectText(el));  // Original case
                }
                if (results.length > 0) return results.slice(0, 50);
            }

            // Strategy 2: Check parent's parent div for children
            let searchRoot = parentBtn.parentElement;
            if (searchRoot) {
                const seen = new Set([parent]);
                const results = [];
                for (const el of searchRoot.querySelectorAll('a, li, [role="menuitem"], [role="treeitem"]')) {
                    if (!isVisible(el)) continue;
                    const t = getDirectText(el).toLowerCase().trim();
                    if (!t || t.length < 2 || t.length > 80) continue;
                    if (NOISE.has(t) || seen.has(t) || t === parent) continue;
                    seen.add(t);
                    results.push(getDirectText(el));
                }
                if (results.length > 0) return results.slice(0, 50);
            }

            return [];
        })()
        """, parent_text) or []

    async def _navigate_to_child_item(self, text: str) -> str | None:
        """Click a child nav item and return the resulting full URL (incl. hash), or None."""
        before_url = await asyncio.to_thread(self._get_full_url)
        before_title = await asyncio.to_thread(self._get_page_title)
        clicked = await asyncio.to_thread(self._click_nav_item, text)
        if not clicked:
            return None
        await asyncio.sleep(1.5)
        after_url = await asyncio.to_thread(self._get_full_url)
        after_title = await asyncio.to_thread(self._get_page_title)
        on_login = await asyncio.to_thread(self._is_login_page)
        if on_login:
            return None
        if after_url != before_url or after_title != before_title:
            return after_url
        return None

    async def _update_modules_with_real_urls(self, url_map: dict[str, str], base_url: str):
        """Update existing modules with real URLs, create new modules for unrecognised nav items."""
        mods_result = await self.db.execute(
            select(ApplicationModule).where(ApplicationModule.application_id == self._app.id)
        )
        modules = {m.name.lower(): m for m in mods_result.scalars().all()}

        for nav_text, url in url_map.items():
            nav_lower = nav_text.lower()
            # Always store as relative path so _collect_urls_to_visit can prefix base_url
            rel_url = url[len(base_url):] if url.startswith(base_url) else url
            if not rel_url.startswith("/"):
                rel_url = "/" + rel_url

            # Find best matching existing module
            matched = None
            for mod_name, mod in modules.items():
                if nav_lower == mod_name or nav_lower in mod_name or mod_name in nav_lower:
                    matched = mod
                    break

            if matched:
                matched.url_pattern = rel_url
                if matched.id:
                    self._module_map[rel_url] = matched.id
            else:
                mod = ApplicationModule(
                    application_id=self._app.id,
                    name=nav_text,
                    description="Discovered via navigation click",
                    url_pattern=rel_url,
                    icon="layout",
                    semantic_tags=[],
                    order_index=len(modules),
                )
                self.db.add(mod)
                await self.db.flush()
                modules[nav_lower] = mod
                self._module_map[rel_url] = mod.id

        # Ensure module_map is complete
        for mod in modules.values():
            if mod.url_pattern and mod.id:
                self._module_map[mod.url_pattern] = mod.id

        await self.db.commit()

    async def _phase_explore_pages(self, max_pages: int):
        """Phase 3: Navigate through all pages and build semantic maps.

        Primary strategy: click-based navigation via nav items.
        Clicking nav items uses the SPA router — no full page reload, so the in-memory JWT
        stays valid. This is critical for Angular/React SPAs (YLIMS, etc.) where a full
        page reload re-checks the stored JWT and can redirect to login if it has expired.

        Secondary strategy: direct URL navigation for any pages not reached via nav clicks
        (deep links, sub-routes discovered in Phase 2b that aren't top-level nav items).

        TOKEN OPTIMIZATION: Check budget before each page, stop gracefully if approaching limit.
        """
        await self._log("MILESTONE", "exploration", f"Starting deep page exploration (max {max_pages} pages)")
        budget_summary = await self._token_budget.summary()
        await self._log("INFO", "exploration",
            f"Token budget: {budget_summary['spent']}/{budget_summary['limit']} tokens used")

        urls_to_visit = await self._collect_urls_to_visit()
        await self._log("INFO", "exploration",
            f"URL list: {len(urls_to_visit)} URLs, {len(self._raw_nav_items)} nav items available")

        # Step 1: Click-based navigation (SPA-safe — keeps JWT alive)
        # This covers every nav item AND their accordion children.
        if self._raw_nav_items:
            await self._explore_via_nav_clicks(max_pages)

        # Step 2: After nav clicks, collect ALL discovered URLs (including
        # anything found during step 1) and explore anything not yet analyzed.
        all_urls = await self._collect_urls_to_visit()
        unvisited = [(url, mid) for url, mid in all_urls if url not in self._phase3_analyzed]

        if unvisited:
            await self._log("INFO", "exploration",
                f"Exploring {len(unvisited)} additional URLs not covered by nav clicks")
            for url, module_id in unvisited:
                if self._should_stop:
                    await self._log("INFO", "exploration", "Stop requested — halting URL-based exploration")
                    break
                if len(self._phase3_analyzed) >= max_pages:
                    break
                if url in self._phase3_analyzed:
                    continue
                try:
                    await self._explore_single_page(url, module_id)
                    self._discovered_urls.add(url)
                    await asyncio.sleep(0.3)
                except Exception as e:
                    log.warning("URL fallback exploration failed", url=url, error=str(e))

        await self._log("SUCCESS", "exploration",
            f"Page exploration complete — {len(self._phase3_analyzed)} pages analyzed")

    async def _explore_via_nav_clicks(self, max_pages: int):
        """
        Click-based page discovery: navigate by clicking nav items instead of guessed URLs.
        Used when URL list is empty/unreliable (SPA apps without detectable hrefs).
        """
        await self._log("INFO", "exploration", "Click-based exploration: clicking nav items")

        # Guard: abort if we ended up back on the login page
        if await asyncio.to_thread(self._is_login_page):
            await self._log("WARNING", "exploration",
                "Browser is on the login page — cannot perform click-based exploration")
            return

        dashboard_url = await asyncio.to_thread(self._get_full_url)
        visited = 0
        seen_titles: set[str] = set()

        # Collect clickable nav items (reuse raw nav items from Phase 2)
        items_to_click = [
            item for item in self._raw_nav_items
            if item.get("text", "").strip() and len(item.get("text", "").strip()) > 1
        ] or await asyncio.to_thread(self._get_nav_items_for_clicking)

        await self._log("INFO", "exploration", f"Nav items to click: {len(items_to_click)}")

        for item in items_to_click:
            # Check stop signal
            if self._should_stop:
                await self._log("INFO", "exploration", "Stop requested — halting click-based exploration")
                return

            text = item.get("text", "").strip()
            href = item.get("href", "").strip()
            if not text:
                continue

            try:
                await self._log("INFO", "exploration", f"Navigating to: {text}")

                # Snapshot nav items BEFORE clicking so we can detect newly revealed sub-items
                nav_before = await asyncio.to_thread(self._snapshot_nav_texts)

                before_url = await asyncio.to_thread(self._get_full_url)
                clicked = await asyncio.to_thread(self._click_nav_item, text)
                if not clicked:
                    # Fallback: navigate via href if available
                    if href and href not in ("#", "/", "javascript:void(0)", "javascript:;"):
                        base = self._app.base_url.rstrip("/")
                        nav_url = href if href.startswith("http") else base + href
                        try:
                            await asyncio.to_thread(self._browser.navigate, nav_url)
                        except Exception:
                            await self._log("WARNING", "exploration", f"Could not navigate to: {text}")
                            continue
                    else:
                        await self._log("WARNING", "exploration", f"Skipping (no clickable target): {text}")
                        continue

                await asyncio.sleep(1.0)
                after_url = await asyncio.to_thread(self._get_full_url)
                on_login = await asyncio.to_thread(self._is_login_page)

                if on_login:
                    await self._log("WARNING", "exploration", f"Login redirect after clicking {text!r}")
                    await asyncio.to_thread(self._browser.navigate, dashboard_url)
                    await asyncio.sleep(0.8)
                    continue

                page_title = await asyncio.to_thread(lambda: self._browser.driver.title)

                if after_url == before_url:
                    # Nav item opened a submenu without navigating (accordion pattern)
                    child_items = await asyncio.to_thread(self._get_revealed_child_items, text)
                    if child_items:
                        await self._log("INFO", "exploration",
                            f"{text} → expanded {len(child_items)} sub-items: {', '.join(child_items[:5])}")
                    for child_text in child_items:
                        await self._log("INFO", "exploration", f"Navigating to: {text} → {child_text}")
                        child_clicked = await asyncio.to_thread(self._click_nav_item, child_text)
                        if not child_clicked:
                            continue
                        await asyncio.sleep(1.0)
                        if not await asyncio.to_thread(self._is_login_page):
                            child_url = await asyncio.to_thread(self._get_full_url)
                            if child_url not in self._phase3_analyzed:
                                mod_id = await self._find_module_for_url(child_url)
                                await self._explore_single_page(child_url, mod_id, nav_hint=f"{text} → {child_text}", skip_navigate=True)
                                self._discovered_urls.add(child_url)
                                visited += 1
                else:
                    # Nav item navigated — explore the parent page
                    seen_titles.add(page_title)
                    if after_url not in self._phase3_analyzed:
                        mod_id = await self._find_module_for_url(after_url)
                        await self._explore_single_page(after_url, mod_id, nav_hint=text, skip_navigate=True)
                        self._discovered_urls.add(after_url)
                        visited += 1

                    # Detect sub-items that NEWLY appeared in the sidebar after navigation.
                    # Diff against the pre-click snapshot to avoid returning false positives.
                    nav_after_texts = await asyncio.to_thread(self._snapshot_nav_texts)
                    new_items_lower = nav_after_texts - nav_before
                    # Retrieve original-case labels by re-scanning (reuse nav_after list)
                    nav_after_list = await asyncio.to_thread(self._get_nav_items_for_clicking)
                    child_items = [
                        it.get("text", "") for it in nav_after_list
                        if it.get("text", "").lower() in new_items_lower
                    ]
                    if child_items:
                        await self._log("INFO", "exploration",
                            f"{text} revealed {len(child_items)} sub-items: {', '.join(child_items[:5])}")
                    for child_text in child_items:
                        await self._log("INFO", "exploration", f"Navigating to: {text} → {child_text}")
                        child_clicked = await asyncio.to_thread(self._click_nav_item, child_text)
                        if not child_clicked:
                            continue
                        await asyncio.sleep(1.0)
                        if not await asyncio.to_thread(self._is_login_page):
                            child_url = await asyncio.to_thread(self._get_full_url)
                            if child_url not in self._phase3_analyzed:
                                mod_id = await self._find_module_for_url(child_url)
                                await self._explore_single_page(child_url, mod_id, nav_hint=f"{text} → {child_text}", skip_navigate=True)
                                self._discovered_urls.add(child_url)
                                visited += 1
                        # Sub-items stay visible within the same section — no need to
                        # navigate back to parent between clicks; just continue the loop

                if visited % 5 == 0 and visited > 0:
                    await self._log("INFO", "exploration", f"Click-explored {visited} pages so far")

                # Only return to dashboard if the nav click navigated away AND
                # we need to reach the next top-level item. If the click opened
                # an accordion (URL unchanged), stay on the page so the sidebar
                # remains expanded and child clicks work.
                current_url = await asyncio.to_thread(self._get_full_url)
                if current_url != dashboard_url and not on_login:
                    await asyncio.to_thread(self._browser.navigate, dashboard_url)
                    await asyncio.sleep(0.4)

            except Exception as e:
                log.warning("Click-based exploration failed", nav_item=text, error=str(e))
                try:
                    await asyncio.to_thread(self._browser.navigate, dashboard_url)
                    await asyncio.sleep(0.5)
                except Exception:
                    pass

        await self._log("SUCCESS", "exploration",
            f"Click-based exploration complete — {visited} pages analyzed")

    async def _simulate_human_behaviors(self):
        """Simulate human interactions to reveal hidden UI elements before extraction."""
        try:
            await self._log("INFO", "exploration", "Simulating human interaction (scrolling, filters, bulk actions)...")

            # 1. Step-by-step scrolling to trigger lazy-loaded content
            await asyncio.to_thread(self._human_step_scroll)

            # 2. Look for Filter buttons to reveal filter menus
            await asyncio.to_thread(self._click_filter_buttons)

            # 3. Look for search bars and simulate typing
            await asyncio.to_thread(self._simulate_search_input)

            # 4. Look for table checkboxes to reveal bulk actions
            await asyncio.to_thread(self._click_table_checkboxes)

            await asyncio.sleep(1.0)
        except Exception as e:
            await self._log("WARNING", "exploration", f"Human simulation failed: {str(e)[:100]}")

    def _human_step_scroll(self):
        """Scroll page in increments to trigger lazy-loaded content, then check for horizontal overflow in tables."""
        try:
            height = self._browser.execute_script(
                "return Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"
            ) or 0
            viewport = self._browser.execute_script("return window.innerHeight") or 600
            if height <= viewport + 50:
                return

            # Scroll down in 4 steps, pausing at each to let lazy content load
            for step in range(1, 5):
                target = int(height * step / 4)
                self._browser.execute_script(f"window.scrollTo({{top:{target}, behavior:'smooth'}})")
                time.sleep(0.6)

            # Scroll any overflowing table containers right (reveals hidden action columns)
            self._browser.execute_script("""
                (function() {
                    const candidates = document.querySelectorAll(
                        'table, [role="grid"], [class*="table"], [class*="datagrid"], .mat-table'
                    );
                    for (const el of candidates) {
                        let p = el.parentElement;
                        while (p && p !== document.body) {
                            if (p.scrollWidth > p.clientWidth + 10) {
                                p.scrollLeft = p.scrollWidth;
                                break;
                            }
                            p = p.parentElement;
                        }
                    }
                })();
            """)
            time.sleep(0.5)

            # Scroll tables back to the left so nothing looks displaced
            self._browser.execute_script("""
                (function() {
                    const candidates = document.querySelectorAll(
                        'table, [role="grid"], [class*="table"], [class*="datagrid"], .mat-table'
                    );
                    for (const el of candidates) {
                        let p = el.parentElement;
                        while (p && p !== document.body) {
                            if (p.scrollLeft > 0) { p.scrollLeft = 0; break; }
                            p = p.parentElement;
                        }
                    }
                })();
            """)

            # Scroll back to top
            self._browser.execute_script("window.scrollTo({top:0, behavior:'smooth'})")
            time.sleep(0.5)
        except Exception:
            pass

    def _click_filter_buttons(self):
        """Find and click filter/search toggle buttons to reveal panels."""
        try:
            # Look for buttons that might toggle filters
            btns = self._browser.driver.find_elements("css selector", "button, [role='button']")
            for b in btns:
                try:
                    if not b.is_displayed():
                        continue
                    text = (b.text or "").lower()
                    aria = (b.get_attribute("aria-label") or "").lower()
                    if "filter" in text or "search" in text or "filter" in aria:
                        b.click()
                        time.sleep(0.5)
                        break # Just click the first one we find
                except Exception:
                    pass
        except Exception:
            pass

    def _simulate_search_input(self):
        """Find a search bar, type a value to trigger live search, then clear it."""
        try:
            inputs = self._browser.driver.find_elements("css selector", "input[type='text'], input[type='search']")
            for inp in inputs:
                try:
                    if not inp.is_displayed():
                        continue
                    placeholder = (inp.get_attribute("placeholder") or "").lower()
                    aria = (inp.get_attribute("aria-label") or "").lower()
                    if "search" in placeholder or "search" in aria or inp.get_attribute("type") == "search":
                        inp.clear()
                        inp.send_keys("test search")
                        time.sleep(1.0)
                        inp.clear()
                        # dispatch event for modern SPAs
                        self._browser.execute_script("arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", inp)
                        break
                except Exception:
                    pass
        except Exception:
            pass

    def _click_table_checkboxes(self):
        """Click the first row checkbox in a table to trigger bulk action bars."""
        try:
            checkboxes = self._browser.driver.find_elements("css selector", "table input[type='checkbox'], .datatable input[type='checkbox'], mat-table input[type='checkbox']")
            for cb in checkboxes:
                try:
                    if not cb.is_displayed() or cb.is_selected():
                        continue
                    cb.click()
                    time.sleep(0.5)
                    break # Click one to reveal bulk actions, then stop
                except Exception:
                    pass
        except Exception:
            pass

    async def _explore_single_page(self, url: str, module_id: str | None, nav_hint: str | None = None, skip_navigate: bool = False):
        """Explore a single page and build its semantic map with validation testing."""
        # Check token budget before exploring
        remaining = await self._token_budget.remaining()
        if remaining < 15000:
            await self._log("WARNING", "exploration",
                f"Token budget critical ({remaining} remaining) — stopping exploration")
            return None

        try:
            self._phase3_analyzed.add(url)  # mark attempted — prevents duplicate analysis
            if not skip_navigate:
                await asyncio.to_thread(self._browser.navigate, url)
                await asyncio.sleep(2.0)  # Angular SPAs need ~2s to bootstrap after a full load

            # Skip error pages — not worth analyzing
            page_title = await asyncio.to_thread(lambda: self._browser.driver.title)
            if any(code in page_title for code in ("502", "503", "504", "404", "403", "500")):
                await self._log("WARNING", "exploration", f"Skipping error page: {page_title} ({url})")
                return None

            # Also skip if the page source is tiny (proxy/server error)
            page_src_len = await asyncio.to_thread(
                lambda: len(self._browser.driver.page_source)
            )
            if page_src_len < 500:
                await self._log("WARNING", "exploration", f"Skipping near-empty page: {url}")
                return None

            # Skip login pages — SPA routing may redirect guessed URL paths to login.
            # On first redirect, try navigating via dashboard to recover the session context
            # (Angular SPAs with in-memory tokens need the app shell to be alive).
            if await asyncio.to_thread(self._is_login_page):
                recovered = False
                if self._dashboard_url:
                    try:
                        await asyncio.to_thread(self._browser.navigate, self._dashboard_url)
                        await asyncio.sleep(2.0)
                        if not await asyncio.to_thread(self._is_login_page):
                            await asyncio.to_thread(self._browser.navigate, url)
                            await asyncio.sleep(2.0)
                            recovered = not await asyncio.to_thread(self._is_login_page)
                    except Exception:
                        pass
                if not recovered:
                    await self._log("WARNING", "exploration", f"Login redirect — skipping: {url}")
                    return None

            await self._simulate_human_behaviors()
            state = self._extractor.extract_page_state()
            page_name = state.get("page", "Unknown Page")
            display_name = nav_hint or page_name

            await self._log("INFO", "exploration", f"Analyzing: {display_name}")

            # AI-powered page analysis with keepalive to prevent session expiry
            page_analysis = await self._analyze_with_keepalive(state, url)

            # Test form validations (quick, token-free)
            if page_analysis.get("forms") and self._field_validator:
                await self._test_form_validations(page_analysis, state)

            # Find or create module
            if not module_id:
                module_id = await self._find_module_for_url(url)

            # Persist page — store crud_operations and navigation_structure in semantic_map
            enriched_state = {
                **state,
                "crud_operations": page_analysis.get("crud_operations", {}),
                "navigation_structure": page_analysis.get("navigation_structure", {}),
                "key_business_objects": page_analysis.get("key_business_objects", []),
            }
            page = ApplicationPage(
                module_id=module_id or await self._get_default_module_id(),
                title=page_analysis.get("page_name", page_name),
                url=url,
                page_type=page_analysis.get("page_type", "unknown"),
                semantic_map=enriched_state,
                forms=page_analysis.get("forms", []),
                tables=page_analysis.get("tables", []),
                workflows=page_analysis.get("workflows", []),
                navigation_links=page_analysis.get("navigation_links", []),
                dynamic_behaviors=page_analysis.get("dynamic_behaviors", []),
            )
            self.db.add(page)
            await self.db.flush()

            # Persist workflows — store full step metadata, entity, preconditions, success criteria
            for wf in page_analysis.get("workflows", []):
                raw_steps = wf.get("steps", [])
                stages = []
                for i, step in enumerate(raw_steps):
                    if isinstance(step, dict):
                        stages.append(step)
                    else:
                        stages.append({"step": i + 1, "action": str(step), "expected_result": ""})

                workflow = ApplicationWorkflow(
                    module_id=module_id or page.module_id,
                    name=wf.get("name", "Unknown Workflow"),
                    description=wf.get("description", ""),
                    workflow_type=wf.get("type", "unknown"),
                    stages=stages,
                    entry_point={
                        "trigger": wf.get("entry_trigger", ""),
                        "entity": wf.get("entity", ""),
                        "preconditions": wf.get("preconditions", []),
                    },
                    success_indicators=wf.get("success_criteria", []),
                )
                self.db.add(workflow)

            await self.db.commit()

            # Log what AI identified for this page
            ai_page_name = page_analysis.get("page_name", display_name)
            page_type = page_analysis.get("page_type", "")
            forms_count = len(page_analysis.get("forms", []))
            wf_count = len(page_analysis.get("workflows", []))

            summary_parts = []
            if page_type:
                summary_parts.append(page_type)
            if forms_count:
                summary_parts.append(f"{forms_count} form{'s' if forms_count != 1 else ''}")
            if wf_count:
                summary_parts.append(f"{wf_count} workflow{'s' if wf_count != 1 else ''}")

            summary = f" ({', '.join(summary_parts)})" if summary_parts else ""
            await self._log("SUCCESS", "exploration",
                f"Mapped: {ai_page_name}{summary}")

            if page_analysis.get("forms"):
                forms_str = ", ".join(f.get("name", "form") for f in page_analysis["forms"][:4])
                await self._log("INFO", "exploration", f"  Forms: {forms_str}")

            if page_analysis.get("workflows"):
                wf_str = ", ".join(w.get("name", "workflow") for w in page_analysis["workflows"][:4])
                await self._log("INFO", "exploration", f"  Workflows: {wf_str}")

            return page

        except Exception as e:
            await self._log("WARNING", "exploration", f"Could not fully analyze page at {url}: {str(e)[:100]}")
            return None

    async def _test_form_validations(self, page_analysis: dict, state: dict):
        """Test form field validations without AI tokens (Phase 2 testing)."""
        if not self._field_validator:
            return

        try:
            # Test required fields
            required_fields = await asyncio.to_thread(
                self._field_validator.test_required_fields
            )

            if required_fields:
                await self._log("INFO", "exploration",
                    f"Detected {len(required_fields)} required fields")

                # Enrich forms with required field info
                for form in page_analysis.get("forms", []):
                    for field in form.get("fields", []):
                        field_name = field.get("label", "").lower()
                        for req_field_name, req_info in required_fields.items():
                            if field_name in req_field_name.lower() or req_field_name.lower() in field_name:
                                field["required"] = True
                                break

            # Test field dependencies (quick check without interaction)
            deps = await asyncio.to_thread(
                self._field_validator.test_field_dependencies
            )
            if deps and deps.get("visible_count", 0) > 2:
                await self._log("INFO", "exploration",
                    f"Page has {deps['visible_count']} visible form fields")

        except Exception as e:
            log.debug("Form validation testing failed", error=str(e))

    async def _analyze_with_keepalive(self, state: dict, url: str) -> dict:
        """
        Run AI page analysis while pinging the server every 25s to keep the SPA session alive.
        YLIMS and similar apps can expire the session during the 2-3 minute AI wait.
        """
        keepalive_url = self._dashboard_url or url
        stop = asyncio.Event()

        async def _keepalive():
            while not stop.is_set():
                await asyncio.sleep(45)  # Reduced pings to save bandwidth
                if stop.is_set():
                    break
                try:
                    # Lightweight no-op to keep session alive
                    await asyncio.to_thread(
                        self._browser.execute_script,
                        "void(0)"
                    )
                except Exception:
                    pass

        task = asyncio.create_task(_keepalive())
        try:
            return await self._analyze_page_with_ai(state, url)
        finally:
            stop.set()
            await asyncio.gather(task, return_exceptions=True)

    async def _analyze_page_with_ai(self, state: dict, url: str) -> dict:
        """Use AI to deeply understand a page's semantic structure (optimized for tokens)."""
        # Check token budget before analyzing
        remaining = await self._token_budget.remaining()
        if remaining < 10000:
            await self._log("WARNING", "exploration",
                f"Token budget critical ({remaining} remaining) — skipping page analysis")
            return {
                "page_name": state.get("page", "Unknown"),
                "page_type": "unknown",
                "forms": [],
                "tables": [],
                "workflows": [],
                "dynamic_behaviors": [],
                "navigation_links": [],
            }

        try:
            # Use optimized compact analyzer
            result = await asyncio.wait_for(
                analyze_page_compact(
                    self.ai,
                    state,
                    url,
                    self._app.name or "Application"
                ),
                timeout=60.0,
            )

            # Track token usage
            tokens_used = result.pop("_tokens", 0)
            error = result.pop("_error", None)
            if tokens_used > 0:
                within_budget = await self._token_budget.add(
                    int(tokens_used * 0.6),  # Estimate input
                    int(tokens_used * 0.4)   # Estimate output
                )
                if not within_budget:
                    await self._log("WARNING", "exploration", "Token budget exceeded — stopping exploration")

            if error:
                log.warning("Page AI analysis failed", error=error)

            return result
        except Exception as e:
            log.warning("Page AI analysis failed", error=str(e))
            return {
                "page_name": state.get("page", "Unknown"),
                "page_type": "unknown",
                "forms": [],
                "tables": [],
                "workflows": [],
                "dynamic_behaviors": [],
                "navigation_links": [],
            }

    async def _phase_build_knowledge_graph(
        self,
        application_id: str,
        session_id: str,
    ) -> KnowledgeGraph | None:
        """Phase 4: Build the complete knowledge graph from discovered data."""
        await self._log("MILESTONE", "knowledge", "Building application knowledge graph")

        modules_count = await self._count_modules(application_id)
        pages_count = await self._count_pages(application_id)
        workflows_count = await self._count_workflows(application_id)

        # Build graph data structure
        graph_data = await self._build_graph_data(application_id)

        kg = KnowledgeGraph(
            application_id=application_id,
            explore_session_id=session_id,
            graph_data=graph_data,
            modules_count=modules_count,
            pages_count=pages_count,
            workflows_count=workflows_count,
        )

        # Version bump — limit(1) prevents MultipleResultsFound when re-running exploration
        existing = await self.db.execute(
            select(KnowledgeGraph)
            .where(KnowledgeGraph.application_id == application_id)
            .order_by(KnowledgeGraph.version.desc())
            .limit(1)
        )
        latest = existing.scalar_one_or_none()
        if latest:
            kg.version = latest.version + 1

        self.db.add(kg)
        await self.db.commit()

        await self._log("SUCCESS", "knowledge",
            f"Knowledge graph v{kg.version} built: {modules_count} modules, {pages_count} pages")

        return kg

    async def _build_graph_data(self, application_id: str) -> dict:
        """Build a complete multi-layer knowledge graph: Application → Modules → Pages → Workflows."""
        modules_result = await self.db.execute(
            select(ApplicationModule).where(ApplicationModule.application_id == application_id)
        )
        modules = list(modules_result.scalars().all())

        pages_result = await self.db.execute(
            select(ApplicationPage)
            .join(ApplicationModule, ApplicationPage.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == application_id)
        )
        pages = list(pages_result.scalars().all())

        workflows_result = await self.db.execute(
            select(ApplicationWorkflow)
            .join(ApplicationModule, ApplicationWorkflow.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == application_id)
        )
        workflows = list(workflows_result.scalars().all())

        graph: dict = {"nodes": [], "edges": []}

        # ── Application root node ──────────────────────────────────────────────
        graph["nodes"].append({
            "id": application_id,
            "type": "application",
            "label": self._app.name or "Application",
            "url": self._app.base_url,
            "modules_count": len(modules),
            "pages_count": len(pages),
            "workflows_count": len(workflows),
        })

        # ── Module nodes ───────────────────────────────────────────────────────
        for m in modules:
            graph["nodes"].append({
                "id": m.id,
                "type": "module",
                "label": m.name,
                "description": m.description or "",
                "url_pattern": m.url_pattern or "",
                "tags": m.semantic_tags or [],
            })
            graph["edges"].append({"from": application_id, "to": m.id, "type": "has_module"})

        # ── Page nodes ─────────────────────────────────────────────────────────
        for p in pages:
            sem = p.semantic_map or {}
            crud_ops = sem.get("crud_operations", {})
            biz_objs = sem.get("key_business_objects", [])
            nav_struct = sem.get("navigation_structure", {})
            graph["nodes"].append({
                "id": p.id,
                "type": "page",
                "label": p.title or p.url,
                "url": p.url,
                "page_type": p.page_type or "unknown",
                "forms_count": len(p.forms or []),
                "tables_count": len(p.tables or []),
                "dynamic_behaviors_count": len(p.dynamic_behaviors or []),
                "business_objects": biz_objs,
                "crud_operations": crud_ops,
                "breadcrumbs": nav_struct.get("breadcrumbs", []),
                "related_pages": nav_struct.get("related_pages", []),
                # Flatten form field details for quick lookup
                "form_fields": [
                    {
                        "form": f.get("name", ""),
                        "entity": f.get("entity", ""),
                        "field": fld.get("label", ""),
                        "type": fld.get("type", "text"),
                        "required": fld.get("required", False),
                        "validation": fld.get("validation", ""),
                    }
                    for f in (p.forms or [])
                    for fld in (f.get("fields") or [])
                ][:40],
                # Table capabilities summary
                "table_capabilities": [
                    {
                        "name": t.get("name", ""),
                        "entity": t.get("entity", ""),
                        "row_actions": t.get("row_actions", []),
                        "bulk_actions": t.get("bulk_actions", []),
                        "has_search": t.get("has_search", False),
                        "has_filter": t.get("has_filter", False),
                        "has_pagination": t.get("has_pagination", False),
                        "pagination_type": t.get("pagination_type", ""),
                    }
                    for t in (p.tables or [])
                ][:10],
            })
            graph["edges"].append({"from": p.module_id, "to": p.id, "type": "has_page"})

        # ── Workflow nodes ─────────────────────────────────────────────────────
        for wf in workflows:
            ep = wf.entry_point or {}
            graph["nodes"].append({
                "id": wf.id,
                "type": "workflow",
                "label": wf.name,
                "workflow_type": wf.workflow_type or "unknown",
                "entity": ep.get("entity", ""),
                "entry_trigger": ep.get("trigger", ""),
                "preconditions": ep.get("preconditions", []),
                "stages_count": len(wf.stages or []),
                "stages": wf.stages or [],
                "success_criteria": wf.success_indicators or [],
            })
            graph["edges"].append({"from": wf.module_id, "to": wf.id, "type": "has_workflow"})

        # ── Summary indexes ────────────────────────────────────────────────────
        # Collect all business objects across pages
        all_biz_objs: set[str] = set()
        for p in pages:
            sem = p.semantic_map or {}
            for obj in sem.get("key_business_objects", []):
                if obj and isinstance(obj, str):
                    all_biz_objs.add(obj)
            for f in (p.forms or []):
                if f.get("entity"):
                    all_biz_objs.add(f["entity"])
            for t in (p.tables or []):
                if t.get("entity"):
                    all_biz_objs.add(t["entity"])

        # CRUD coverage map: entity → [create, read, update, delete]
        crud_coverage: dict[str, list[str]] = {}
        for wf in workflows:
            wtype = wf.workflow_type or ""
            entity = (wf.entry_point or {}).get("entity", "")
            if entity and "crud" in wtype:
                if entity not in crud_coverage:
                    crud_coverage[entity] = []
                op = wtype.replace("crud_", "")
                if op not in crud_coverage[entity]:
                    crud_coverage[entity].append(op)

        # Dynamic behavior catalog
        behavior_types: dict[str, int] = {}
        for p in pages:
            for beh in (p.dynamic_behaviors or []):
                btype = beh.get("behavior", "") if isinstance(beh, dict) else str(beh)
                behavior_types[btype] = behavior_types.get(btype, 0) + 1

        # ── Interaction pattern intelligence — pulled from stored guides ──────
        # Attach the pattern summary (action icons, status tabs, bulk delete,
        # approve workflow, search no-data state) for each module so the KG
        # reflects the full discovered interaction capability.
        pattern_summary: dict[str, dict] = {}
        try:
            guides_q = await self.db.execute(
                select(AIMemoryChunk).where(
                    AIMemoryChunk.application_id == application_id,
                    AIMemoryChunk.kind == MemoryKind.WORKFLOW,
                )
            )
            for chunk in guides_q.scalars().all():
                extra = chunk.extra or {}
                if extra.get("guide_type") != "interaction":
                    continue
                mid = extra.get("module_id", "")
                if not mid:
                    continue
                text = chunk.content or ""
                pat: dict = {}
                # Action icons section
                if "ACTION COLUMN ICONS" in text:
                    icons = {}
                    in_icons = False
                    for ln in text.splitlines():
                        ln = ln.strip()
                        if ln.startswith("ACTION COLUMN ICONS"):
                            in_icons = True; continue
                        if in_icons:
                            if ln.startswith(("STATUS WORKFLOW", "BULK DELETE", "APPROVAL", "SEARCH", "[")):
                                break
                            import re as _re
                            m = _re.match(r'^(EDIT|DELETE|APPROVE|VIEW|REJECT):\s+"([^"]+)"', ln, _re.IGNORECASE)
                            if m:
                                icons[m.group(1).lower()] = m.group(2)
                    if icons:
                        pat["action_icons"] = icons
                # Status tabs
                if "STATUS WORKFLOW TABS" in text:
                    tabs = []
                    in_tabs = False
                    for ln in text.splitlines():
                        ln = ln.strip()
                        if ln.startswith("STATUS WORKFLOW TABS"):
                            in_tabs = True; continue
                        if in_tabs:
                            if ln.startswith(("BULK DELETE", "APPROVAL", "SEARCH", "[")):
                                break
                            import re as _re2
                            m = _re2.match(r'^Tab:\s+"([^"]+)"', ln, _re2.IGNORECASE)
                            if m:
                                tabs.append(m.group(1))
                    if tabs:
                        pat["status_tabs"] = tabs
                # Bulk delete
                pat["has_bulk_delete"] = "BULK DELETE PATTERN" in text and "click_checkbox" in text
                # Approval workflow
                if "APPROVAL WORKFLOW" in text:
                    import re as _re3
                    apm = _re3.search(r'pattern:\s*(\w+)', text[text.find("APPROVAL WORKFLOW"):])
                    pat["approval_pattern"] = apm.group(1) if apm else "detected"
                # Search no-data
                pat["has_search_no_data"] = "SEARCH NO-RESULTS STATE" in text
                pattern_summary[mid] = pat
        except Exception:
            pass

        # Embed pattern summary into the corresponding module nodes
        for node in graph["nodes"]:
            if node.get("type") == "module" and node.get("id") in pattern_summary:
                node["interaction_patterns"] = pattern_summary[node["id"]]

        graph["summary"] = {
            "application": self._app.name or "Application",
            "modules_count": len(modules),
            "pages_count": len(pages),
            "workflows_count": len(workflows),
            "business_objects": sorted(all_biz_objs),
            "crud_coverage": crud_coverage,
            "dynamic_behavior_catalog": behavior_types,
            "forms_total": sum(len(p.forms or []) for p in pages),
            "tables_total": sum(len(p.tables or []) for p in pages),
            "module_names": [m.name for m in modules],
            "modules_with_bulk_delete": [
                mid for mid, p in pattern_summary.items() if p.get("has_bulk_delete")
            ],
            "modules_with_approval_workflow": [
                mid for mid, p in pattern_summary.items() if p.get("approval_pattern")
            ],
            "modules_with_status_tabs": [
                mid for mid, p in pattern_summary.items() if p.get("status_tabs")
            ],
        }

        return graph

    async def _collect_urls_to_visit(self) -> list[tuple[str, str | None]]:
        """Collect all URLs to visit during exploration."""
        urls = []
        seen_urls: set[str] = set()

        def _add(url: str, module_id: str | None = None):
            if url and url not in seen_urls:
                seen_urls.add(url)
                urls.append((url, module_id))

        # Always include current post-login page first
        try:
            current = self._browser.get_current_url()
            if current and not current.startswith("data:") and current != "about:blank":
                _add(current)
        except Exception:
            pass

        # Module URL patterns — only add AI-guessed paths if we have < 3 reliable URLs so far
        # (Phase 2b replaces these with real URLs; if still AI-guessed they likely redirect to login)
        if len(urls) < 3:
            modules_result = await self.db.execute(
                select(ApplicationModule).where(ApplicationModule.application_id == self._app.id)
            )
            modules = modules_result.scalars().all()
            base = self._app.base_url.rstrip("/")
            for module in modules:
                pat = module.url_pattern or ""
                if not pat:
                    continue
                if pat.startswith("http"):
                    _add(pat, module.id)
                elif pat.startswith("/"):
                    _add(base + pat, module.id)

        # URLs captured by clicking nav items (real URLs for SPA apps)
        for url in self._discovered_urls:
            if url and not url.startswith("data:") and url != "about:blank":
                _add(url)

        # Nav hrefs from Phase 2 (includes hash-based SPA routes)
        base = self._app.base_url.rstrip("/")
        for item in self._raw_nav_items:
            href = item.get("href", "").strip()
            text = item.get("text", "").strip()
            if not href or href in ("#", "javascript:void(0)", "javascript:;", "/"):
                continue
            real = href if href.startswith("http") else base + href
            # Find matching module id by nav text
            mod_id = None
            for pattern, mid in self._module_map.items():
                if text and pattern and (text.lower() in pattern.lower() or pattern.lower() in text.lower()):
                    mod_id = mid
                    break
            _add(real, mod_id)

        # Links on current page (<a href> — also catches hash routes)
        try:
            links = self._browser.execute_script("""
                const origin = window.location.origin;
                return Array.from(document.querySelectorAll('a[href]'))
                    .filter(a => {
                        const h = a.href || '';
                        return (h.startsWith(origin) || h.startsWith('#')) && a.textContent.trim();
                    })
                    .map(a => a.href)
                    .filter((v, i, arr) => arr.indexOf(v) === i)
                    .slice(0, 40);
            """) or []
            for url in links:
                _add(url)
        except Exception:
            pass

        # If very few URLs collected, add current URL as the only page to analyze deeply
        if not urls:
            try:
                current = self._browser.get_current_url()
                if current and not current.startswith("data:"):
                    _add(current)
            except Exception:
                pass

        return urls

    async def _find_module_for_url(self, url: str) -> str | None:
        # Sort patterns by length descending so more specific paths match first
        for pattern, module_id in sorted(self._module_map.items(), key=lambda x: len(x[0]), reverse=True):
            if pattern and pattern in url:
                return module_id
        return None

    async def _get_default_module_id(self) -> str | None:
        result = await self.db.execute(
            select(ApplicationModule.id)
            .where(ApplicationModule.application_id == self._app.id)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _count_modules(self, app_id: str) -> int:
        from sqlalchemy import func
        result = await self.db.execute(
            select(func.count(ApplicationModule.id)).where(ApplicationModule.application_id == app_id)
        )
        return result.scalar() or 0

    async def _count_pages(self, app_id: str) -> int:
        from sqlalchemy import func
        result = await self.db.execute(
            select(func.count(ApplicationPage.id))
            .join(ApplicationModule, ApplicationPage.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == app_id)
        )
        return result.scalar() or 0

    async def _count_workflows(self, app_id: str) -> int:
        from sqlalchemy import func
        result = await self.db.execute(
            select(func.count(ApplicationWorkflow.id))
            .join(ApplicationModule, ApplicationWorkflow.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == app_id)
        )
        return result.scalar() or 0

    async def _wait_for_decision(self, decision_id: str, timeout: int = 300) -> HumanDecision | None:
        """Poll for human decision resolution. Uses populate_existing to bypass session cache."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(3)
            result = await self.db.execute(
                select(HumanDecision).where(HumanDecision.id == decision_id)
                .execution_options(populate_existing=True)
            )
            decision = result.scalar_one_or_none()
            if decision and decision.selected_option:
                return decision
        return None

    async def _fail_session(self, session: ExploreSession, reason: str):
        # Roll back any aborted transaction before writing the failure status —
        # a FK violation or other DB error leaves the connection in an aborted
        # state; committing on top of it raises InFailedSQLTransactionError.
        try:
            await self.db.rollback()
        except Exception:
            pass
        session.status = ExploreStatus.FAILED
        session.error_message = reason
        session.completed_at = datetime.utcnow()
        try:
            await self.db.commit()
        except Exception:
            pass
        await self._log("WARNING", "system", f"Exploration failed: {reason}")
        await self._emit_event("explore_failed", {"session_id": self._session_id, "reason": reason})

    async def _cleanup_old_exploration_data(self, application_id: str) -> None:
        """Wipe stale exploration data from prior runs so each run starts clean."""
        mod_count_result = await self.db.execute(
            select(func.count(ApplicationModule.id))
            .where(ApplicationModule.application_id == application_id)
        )
        module_count = mod_count_result.scalar() or 0

        page_count_result = await self.db.execute(
            select(func.count(ApplicationPage.id))
            .join(ApplicationModule, ApplicationPage.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == application_id)
        )
        page_count = page_count_result.scalar() or 0

        if module_count == 0 and page_count == 0:
            await self._log("INFO", "system", "No previous exploration data to clean up")
            return

        await self._log("INFO", "system",
            f"Cleaning up {module_count} modules and {page_count} pages from previous run(s)...")

        # 1. Delete AI-generated scenarios (stale — will be regenerated from fresh data)
        await self.db.execute(
            sa_delete(Scenario).where(
                Scenario.application_id == application_id,
                Scenario.source == "ai_generated",
            )
        )
        # 2. Null out module references on user-created scenarios so they survive module deletion
        await self.db.execute(
            sa_update(Scenario)
            .where(
                Scenario.application_id == application_id,
                Scenario.module_id.is_not(None),
            )
            .values(module_id=None)
        )
        # 3. Delete modules — DB ON DELETE CASCADE removes pages, semantic elements, workflows
        await self.db.execute(
            sa_delete(ApplicationModule).where(ApplicationModule.application_id == application_id)
        )
        # 4. Clear knowledge graphs
        await self.db.execute(
            sa_delete(KnowledgeGraph).where(KnowledgeGraph.application_id == application_id)
        )
        # 5. Clear AI memory chunks (will be rebuilt from fresh exploration)
        await self.db.execute(
            sa_delete(AIMemoryChunk).where(AIMemoryChunk.application_id == application_id)
        )

        await self.db.commit()
        await self._log("INFO", "system",
            f"Cleanup done — cleared {module_count} modules, {page_count} pages, and related data")

    async def _cleanup_module_exploration_data(self, module_ids: list[str], application_id: str) -> None:
        """
        Refresh exploration data for specific modules only.
        Deletes pages, workflows, child modules, and AI scenarios for the given module IDs.
        The module records themselves are kept so IDs and user selections remain valid.
        All other modules' data is untouched.
        """
        if not module_ids:
            return

        # Include child modules created during previous accordion expansion
        child_result = await self.db.execute(
            select(ApplicationModule.id).where(
                ApplicationModule.parent_id.in_(module_ids),
                ApplicationModule.application_id == application_id,
            )
        )
        child_ids = [row[0] for row in child_result.all()]
        all_ids = list(module_ids) + child_ids

        # Count what we're refreshing for the log
        page_count = (await self.db.execute(
            select(func.count(ApplicationPage.id)).where(ApplicationPage.module_id.in_(all_ids))
        )).scalar() or 0
        wf_count = (await self.db.execute(
            select(func.count(ApplicationWorkflow.id)).where(ApplicationWorkflow.module_id.in_(all_ids))
        )).scalar() or 0

        await self._log("INFO", "system",
            f"Refreshing {len(module_ids)} module(s): removing {page_count} page(s), "
            f"{wf_count} workflow(s), {len(child_ids)} child module(s) — other modules untouched")

        # Remove AI-generated scenarios for these modules.
        # Scenarios that already have execution_runs can't be hard-deleted (FK constraint
        # on execution_runs.scenario_id has no CASCADE). Detach those instead so history
        # is preserved; delete the rest cleanly.
        ai_ids_result = await self.db.execute(
            select(Scenario.id).where(
                Scenario.module_id.in_(all_ids),
                Scenario.source == "ai_generated",
            )
        )
        ai_ids = [row[0] for row in ai_ids_result.all()]
        if ai_ids:
            has_runs_result = await self.db.execute(
                select(ExecutionRun.scenario_id).where(
                    ExecutionRun.scenario_id.in_(ai_ids)
                ).distinct()
            )
            has_runs_ids = {row[0] for row in has_runs_result.all()}
            safe_to_delete = [sid for sid in ai_ids if sid not in has_runs_ids]
            must_detach    = [sid for sid in ai_ids if sid in has_runs_ids]
            if safe_to_delete:
                await self.db.execute(
                    sa_delete(Scenario).where(Scenario.id.in_(safe_to_delete))
                )
            if must_detach:
                await self.db.execute(
                    sa_update(Scenario)
                    .where(Scenario.id.in_(must_detach))
                    .values(module_id=None)
                )
        # Detach user-created scenarios from module so they survive re-exploration
        await self.db.execute(
            sa_update(Scenario)
            .where(
                Scenario.module_id.in_(all_ids),
                Scenario.source != "ai_generated",
            )
            .values(module_id=None)
        )
        # Delete child modules — DB cascade removes their pages, workflows, semantic elements
        if child_ids:
            await self.db.execute(
                sa_delete(ApplicationModule).where(ApplicationModule.id.in_(child_ids))
            )
        # Delete workflows on the selected modules
        await self.db.execute(
            sa_delete(ApplicationWorkflow).where(ApplicationWorkflow.module_id.in_(module_ids))
        )
        # Delete pages on the selected modules — DB cascade removes semantic elements
        await self.db.execute(
            sa_delete(ApplicationPage).where(ApplicationPage.module_id.in_(module_ids))
        )
        # Reset url_pattern so it gets re-discovered during this exploration pass
        await self.db.execute(
            sa_update(ApplicationModule)
            .where(ApplicationModule.id.in_(module_ids))
            .values(url_pattern=None)
        )
        # Delete stale interaction guides for these modules
        existing_guides = await self.db.execute(
            select(AIMemoryChunk).where(
                AIMemoryChunk.application_id == application_id,
                AIMemoryChunk.kind == MemoryKind.WORKFLOW,
            )
        )
        for chunk in existing_guides.scalars().all():
            if (chunk.extra or {}).get("guide_type") == "interaction" and \
               (chunk.extra or {}).get("module_id") in all_ids:
                await self.db.delete(chunk)

        await self.db.commit()
        await self._log("INFO", "system",
            f"Refresh complete — {len(module_ids)} module(s) ready for re-exploration")

    async def _log(self, level: str, category: str, message: str, metadata: dict | None = None):
        """Emit semantic log — not technical logs."""
        from datetime import timezone
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

        # Pre-generate the id so WS and DB share the same key — frontend can
        # deduplicate polling results against already-displayed WS events.
        log_id = str(uuid.uuid4())

        # Emit to WebSocket FIRST so the user sees it immediately (before DB round-trip).
        await self._emit_event("explore_log", {
            "id": log_id,
            "session_id": self._session_id,
            "level": level,
            "category": category,
            "message": message,
            "timestamp": ts,
        })

        # Persist for page-refresh / polling recovery.
        entry = ExploreLog(
            id=log_id,
            session_id=self._session_id,
            level=level,
            category=category,
            message=message,
            extra=metadata or {},
        )
        self.db.add(entry)
        await self.db.commit()

    async def _emit_event(self, event: str, data: dict):
        await connection_manager.broadcast_json({"event": event, **data})

    async def _load_session(self, session_id: str) -> ExploreSession | None:
        result = await self.db.execute(select(ExploreSession).where(ExploreSession.id == session_id))
        return result.scalar_one_or_none()

    async def _load_application(self, application_id: str) -> Application | None:
        result = await self.db.execute(select(Application).where(Application.id == application_id))
        return result.scalar_one_or_none()

    def _discover_nav_from_page_links(self) -> list[dict]:
        """
        Fallback nav discovery: collect unique internal <a href> links from the page.
        Groups them by distinct URL path to avoid duplicates, and returns them as
        synthetic nav items so _hierarchical_explore can click/visit each one.
        """
        return self._browser.execute_script("""
        (function() {
            const origin = window.location.origin;
            const currentPath = window.location.pathname;
            const seen = new Set();
            const results = [];
            const NOISE_TEXT = new Set(['logout','log out','sign out','skip','close','cancel',
                                        'back','next','previous','submit','save','delete']);

            for (const a of document.querySelectorAll('a[href]')) {
                const href = a.getAttribute('href') || '';
                if (!href || href.startsWith('javascript') || href === '#' || href === '') continue;

                let full;
                try { full = new URL(href, window.location.href).href; } catch(e) { continue; }
                if (!full.startsWith(origin)) continue;

                const path = new URL(full).pathname;
                if (path === currentPath || path === '/' || path === '') continue;

                const key = path.toLowerCase().replace(/\\/$/, '');
                if (seen.has(key)) continue;
                seen.add(key);

                // Robust text extraction for icon-only sidebars
                let text = '';
                // 1. aria-label (most reliable for icon buttons)
                text = (a.getAttribute('aria-label') || '').trim();
                // 2. title attribute
                if (!text) text = (a.getAttribute('title') || '').trim();
                // 3. data-tooltip variants
                if (!text) text = (a.getAttribute('data-tooltip') || a.getAttribute('data-tip') || a.getAttribute('data-content') || '').trim();
                // 4. sr-only / visually-hidden spans (shadcn/ui collapsed sidebar pattern)
                if (!text) {
                    for (const span of a.querySelectorAll('span, p')) {
                        const cls = (span.className || '').toLowerCase();
                        if (cls.includes('sr-only') || cls.includes('screen-reader') ||
                            cls.includes('visually-hidden') || cls.includes('sr-text')) {
                            const t = (span.textContent || '').trim();
                            if (t && t.length >= 2 && t.length < 80) { text = t; break; }
                        }
                    }
                }
                // 5. textContent minus SVG nodes (catches hidden-but-present text spans)
                if (!text) {
                    const clone = a.cloneNode(true);
                    for (const s of clone.querySelectorAll('svg, path, circle, rect, line, polyline, polygon')) s.remove();
                    text = clone.textContent.trim().replace(/\\s+/g, ' ');
                    if (text.length > 80) text = '';
                }
                // 6. Derive a readable name from the URL path segment (icon-only with no text)
                if (!text || text.length < 2) {
                    const seg = path.split('/').filter(Boolean).pop() || '';
                    if (seg) text = seg.replace(/[-_]/g, ' ').replace(/\\b\\w/g, c => c.toUpperCase());
                }
                if (!text || text.length < 2) continue;
                if (NOISE_TEXT.has(text.toLowerCase())) continue;

                results.push({ text: text, href: href, is_accordion: false, tag: 'a' });
            }
            // Sort alphabetically so the order is deterministic
            results.sort((a, b) => a.text.localeCompare(b.text));
            return results.slice(0, 60);
        })()
        """) or []

    def _scan_parent_navs(self) -> list[dict]:
        """Scan the sidebar/navigation DOM for parent/top-level nav items."""
        return self._browser.execute_script("""
        return (function() {
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0
                    && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            }
            function getDirectText(el) {
                // Priority 1: aria-label (most reliable for icon-only nav items)
                let t = (el.getAttribute('aria-label') || '').trim();
                if (t && t.length >= 2 && t.length < 80) return t;
                // Priority 2: title attribute
                t = (el.getAttribute('title') || '').trim();
                if (t && t.length >= 2 && t.length < 80) return t;
                // Priority 3: data-tooltip variants
                t = (el.getAttribute('data-tooltip') || el.getAttribute('data-tip') || el.getAttribute('data-content') || '').trim();
                if (t && t.length >= 2 && t.length < 80) return t;
                // Priority 4: sr-only / visually-hidden child spans (shadcn/ui collapsed sidebar)
                for (const span of el.querySelectorAll('span, p')) {
                    const cls = (span.className || '').toLowerCase();
                    if (cls.includes('sr-only') || cls.includes('screen-reader') ||
                        cls.includes('visually-hidden') || cls.includes('sr-text')) {
                        t = (span.textContent || '').trim();
                        if (t && t.length >= 2 && t.length < 80) return t;
                    }
                }
                // Priority 5: direct text nodes (traditional nav items)
                t = '';
                for (const n of el.childNodes) { if (n.nodeType === 3) t += n.textContent; }
                t = t.trim().replace(/\\s+/g, ' ');
                if (t && t.length >= 2 && t.length < 80) return t;
                // Priority 6: textContent minus SVG (catches hidden-but-present text spans)
                const clone = el.cloneNode(true);
                for (const s of clone.querySelectorAll('svg, path, circle, rect, line, polyline, polygon')) s.remove();
                t = clone.textContent.trim().replace(/\\s+/g, ' ');
                if (t && t.length >= 2 && t.length < 80) return t;
                // Priority 7: URL path segment for <a href> (pure icon-only with NO text at all)
                if (el.tagName === 'A') {
                    const href = el.getAttribute('href') || '';
                    const seg = href.split('/').filter(Boolean).pop() || '';
                    if (seg) return seg.replace(/[-_]/g, ' ').replace(/\\b\\w/g, c => c.toUpperCase());
                }
                return '';
            }
            // Only hard-block structural noise — profile/account/settings are valid modules
            const NOISE = new Set(['logout','log out','sign out']);
            const NAV_SELS = [
                'nav', '[role="navigation"]', 'aside', '[role="menubar"]', '[role="tree"]',
                '[class*="sidebar" i]', '[class*="sider" i]', '[class*="sidenav" i]',
                '[class*="side-nav" i]', '[class*="menu-bar" i]', '[class*="left-nav" i]',
                '[class*="leftnav" i]', '[class*="left-menu" i]', '[class*="leftmenu" i]',
                '[class*="nav-wrapper" i]', '[class*="navigation" i]',
                '[class*="app-menu" i]', '[class*="main-menu" i]', '[class*="vertical-nav" i]',
                'header nav', 'header [role="menubar"]'
            ];
            let bestRoot = null;
            let maxItems = 0;
            for (const sel of NAV_SELS) {
                for (const el of document.querySelectorAll(sel)) {
                    if (isVisible(el)) {
                        const items = el.querySelectorAll('a, button, li, [role="menuitem"], mat-list-item, .nav-item, .menu-item').length;
                        if (items > maxItems && items >= 3) {
                            maxItems = items;
                            bestRoot = el;
                        }
                    }
                }
            }
            let root = bestRoot || document.body;

            const results = [];
            const seen = new Set();

            function isSubMenuItem(el) {
                // Only exclude items explicitly inside sub-menu containers by class/id name.
                // Do NOT use role='menu' or role='group' — those are legitimately used on
                // top-level nav lists by Ant Design, MUI, Chakra, etc., and falsely exclude
                // every real nav item when the nav ul has role="menu".
                let p = el.parentElement;
                while (p && p !== root) {
                    const cls = (p.className || '').toLowerCase();
                    const id = (p.id || '').toLowerCase();
                    if (cls.includes('submenu') || cls.includes('sub-menu') || cls.includes('nested') ||
                        cls.includes('dropdown-menu') || cls.includes('accordion-body') ||
                        cls.includes('accordion-content') || id.includes('submenu')) {
                        return true;
                    }
                    p = p.parentElement;
                }
                return false;
            }

            for (const el of root.querySelectorAll('button, a, [role="button"], [role="menuitem"], [role="link"], [role="tab"], mat-list-item, .nav-item, .menu-item, div.text-sm')) {
                if (!isVisible(el)) continue;
                const text = getDirectText(el);
                if (!text || text.length < 2 || NOISE.has(text.toLowerCase())) continue;
                if (isSubMenuItem(el)) continue;
                if (seen.has(text.toLowerCase())) continue;
                seen.add(text.toLowerCase());

                const hasExpander = el.hasAttribute('aria-expanded') ||
                                    el.hasAttribute('aria-haspopup') ||
                                    el.classList.contains('accordion-toggle') ||
                                    !!el.querySelector('[aria-expanded]') ||
                                    (el.nextElementSibling && el.nextElementSibling.querySelectorAll('a, button, li, [role="menuitem"], mat-list-item, .nav-item, .menu-item, div.text-sm').length > 0) ||
                                    (el.parentElement && el.parentElement.nextElementSibling && el.parentElement.nextElementSibling.querySelectorAll('a, button, li, [role="menuitem"], mat-list-item, .nav-item, .menu-item, div.text-sm').length > 0);

                results.push({
                    text: text,
                    is_accordion: !!hasExpander,
                    tag: el.tagName.toLowerCase(),
                    href: el.getAttribute('href') || ''
                });
            }
            return results;
        })()
        """) or []

    def _scan_child_navs(self, parent_text: str) -> list[dict]:
        """Scan for sub-menu child navigation items revealed under the parent nav."""
        return self._browser.execute_script("""
        return (function(arg0) {
            function isVisible(el) {
                if (!el) return false;
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0
                    && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
            }
            function getDirectText(el) {
                let t = '';
                for (const n of el.childNodes) { if (n.nodeType === 3) t += n.textContent; }
                t = t.trim().replace(/\\s+/g, ' ');
                if (!t) t = (el.getAttribute('aria-label') || el.textContent || '').trim().replace(/\\s+/g, ' ');
                return t.slice(0, 80);
            }
            const NOISE = new Set(['logout','log out','sign out','notifications','help','about','profile','account','settings','home','dashboard']);
            const target = arg0.toLowerCase().trim();
            const seen = new Set([target]);
            const results = [];

            let parentEl = null;
            for (const el of document.querySelectorAll('button, a, [role="button"], [role="menuitem"], [role="link"], [role="tab"], mat-list-item, .nav-item, .menu-item, div.text-sm')) {
                if (!isVisible(el)) continue;
                const txt = getDirectText(el).toLowerCase().trim();
                if (txt === target || txt.startsWith(target) || target.startsWith(txt)) {
                    parentEl = el;
                    break;
                }
            }
            if (!parentEl) return [];

            let sibling = parentEl.nextElementSibling;
            if (!sibling && parentEl.parentElement) {
                sibling = parentEl.parentElement.nextElementSibling;
            }

            for (let i = 0; i < 3 && sibling; i++) {
                if (isVisible(sibling)) {
                    for (const a of sibling.querySelectorAll('a, button, li, [role="menuitem"], [role="button"], [role="link"], [role="tab"], mat-list-item, .nav-item, .menu-item, div.text-sm')) {
                        if (!isVisible(a)) continue;
                        const txt = getDirectText(a);
                        if (!txt || txt.length < 2 || NOISE.has(txt.toLowerCase())) continue;
                        const key = txt.toLowerCase().trim();
                        if (key !== target && !seen.has(key)) {
                            seen.add(key);
                            results.push({ text: txt, href: a.getAttribute('href') || '' });
                        }
                    }
                }
                sibling = sibling.nextElementSibling;
            }

            return results;
        })(arguments[0])
        """, parent_text) or []

    async def _explore_selected_modules(self, module_ids: list[str]):
        """Explore only user-selected modules by navigating to them via nav clicks."""
        await self._log("MILESTONE", "exploration", f"Starting deep exploration for {len(module_ids)} selected module(s)")

        result = await self.db.execute(select(ApplicationModule).where(ApplicationModule.id.in_(module_ids)))
        modules = result.scalars().all()
        base_url = self._app.base_url.rstrip("/")

        for m_idx, module in enumerate(modules):
            if self._should_stop:
                return

            await self._log("INFO", "exploration",
                f"[{m_idx + 1}/{len(modules)}] Navigating to: {module.name}")

            # Return to a known good state before each module
            await asyncio.to_thread(self._browser.navigate, self._dashboard_url)
            await asyncio.sleep(0.8)

            # Try to navigate by clicking the nav item by name; fall back to url_pattern
            clicked = await asyncio.to_thread(self._click_nav_item, module.name)
            if not clicked:
                url_pat = (module.url_pattern or "").strip()
                if url_pat and url_pat not in ("#", "/", "javascript:void(0)", "javascript:;"):
                    nav_url = url_pat if url_pat.startswith("http") else base_url + url_pat
                    await self._log("INFO", "exploration",
                        f"Text-click failed for '{module.name}' — navigating directly to {nav_url}")
                    await asyncio.to_thread(self._browser.navigate, nav_url)
                else:
                    await self._log("WARNING", "exploration",
                        f"Could not navigate to '{module.name}' (no url_pattern, click failed) — skipping")
                    continue
            await asyncio.sleep(1.0)

            actual_url = await asyncio.to_thread(self._get_full_url)

            # If URL hasn't changed from dashboard, try direct URL navigation before
            # concluding this is an accordion — covers icon-only sidebars and apps
            # where click-by-text doesn't trigger navigation.
            url_unchanged = actual_url.rstrip("/") == self._dashboard_url.rstrip("/")
            if url_unchanged:
                url_pat = (module.url_pattern or "").strip()
                if url_pat and url_pat not in ("#", "/", "javascript:void(0)", "javascript:;"):
                    direct_url = url_pat if url_pat.startswith("http") else base_url + url_pat
                    # Only try if it's actually a different URL from the dashboard
                    if direct_url.rstrip("/") != self._dashboard_url.rstrip("/"):
                        await self._log("INFO", "exploration",
                            f"URL unchanged after click — navigating directly to {direct_url}")
                        await asyncio.to_thread(self._browser.navigate, direct_url)
                        await asyncio.sleep(1.5)
                        actual_url = await asyncio.to_thread(self._get_full_url)
                        url_unchanged = actual_url.rstrip("/") == self._dashboard_url.rstrip("/")

            if url_unchanged:
                # Still on dashboard — check if it's a real accordion with sub-items
                children = await asyncio.to_thread(self._scan_child_navs, module.name)
                if children:
                    await self._log("INFO", "exploration",
                        f"'{module.name}' has {len(children)} sub-item(s) — exploring each")
                    for c_idx, child in enumerate(children):
                        if self._should_stop:
                            return
                        child_text = child["text"]
                        child_href = child.get("href", "").strip()
                        await self._log("INFO", "exploration",
                            f"  [{c_idx + 1}/{len(children)}] Sub-item: {module.name} → {child_text}")

                        # Navigate to child: prefer direct href, fall back to click sequence
                        navigated = False
                        if child_href and child_href not in ("#", "/", "javascript:void(0)", "javascript:;"):
                            child_nav_url = child_href if child_href.startswith("http") else base_url + child_href
                            await asyncio.to_thread(self._browser.navigate, child_nav_url)
                            await asyncio.sleep(1.0)
                            navigated = True
                        else:
                            await asyncio.to_thread(self._browser.navigate, self._dashboard_url)
                            await asyncio.sleep(0.7)
                            await asyncio.to_thread(self._click_nav_item, module.name)
                            await asyncio.sleep(0.6)
                            await asyncio.to_thread(self._click_nav_item, child_text)
                            await asyncio.sleep(1.0)
                            navigated = True

                        child_url = await asyncio.to_thread(self._get_full_url)
                        if await asyncio.to_thread(self._is_login_page):
                            continue
                        if child_url.rstrip("/") == self._dashboard_url.rstrip("/"):
                            await self._log("WARNING", "exploration",
                                f"  Sub-item '{child_text}' stayed on dashboard — skipping")
                            continue

                        rel_url = child_url[len(base_url):] if child_url.startswith(base_url) else child_url
                        if not rel_url.startswith("/"): rel_url = "/" + rel_url
                        child_module = ApplicationModule(
                            application_id=self._app.id,
                            name=f"{module.name} - {child_text}",
                            description=f"Sub-module: {child_text}",
                            url_pattern=rel_url,
                            icon="layout",
                            parent_id=module.id,
                            order_index=c_idx,
                        )
                        self.db.add(child_module)
                        await self.db.flush()
                        await self._explore_and_scan_module_page(
                            child_url, child_module.id, nav_hint=f"{module.name} - {child_text}"
                        )
                    await self.db.commit()
                else:
                    # No sub-items found AND no URL change — explore the current page anyway.
                    # The module might be the dashboard itself or a page we can still scan.
                    await self._log("INFO", "exploration",
                        f"'{module.name}' appears to be the current page — scanning it")
                    if not await asyncio.to_thread(self._is_login_page):
                        module.url_pattern = module.url_pattern or actual_url[len(base_url):]
                        await self.db.commit()
                        await self._explore_and_scan_module_page(
                            actual_url, module.id, nav_hint=module.name
                        )
            else:
                # URL changed — standalone page, explore it
                if await asyncio.to_thread(self._is_login_page):
                    await self._log("WARNING", "exploration",
                        f"Login redirect for '{module.name}' — skipping")
                    continue
                rel_url = actual_url[len(base_url):] if actual_url.startswith(base_url) else actual_url
                if not rel_url.startswith("/"): rel_url = "/" + rel_url
                module.url_pattern = rel_url
                await self.db.commit()
                await self._explore_and_scan_module_page(actual_url, module.id, nav_hint=module.name)

    async def _wait_for_module_selection(self, session_id: str, timeout: int = 600) -> list[str] | None:
        """
        Poll the DB until the user sets selected_module_ids via the /continue endpoint.
        Returns the list of IDs, or None if timed out / stop requested.
        Browser stays alive during this wait.
        """
        import time
        deadline = time.time() + timeout
        await self._log("INFO", "system",
            "Waiting for module selection (browser staying alive — already logged in)…")
        while time.time() < deadline:
            if self._should_stop:
                return None
            await asyncio.sleep(1)
            # Query only the column we care about — scalar queries bypass the SQLAlchemy
            # identity map, which would otherwise return the stale cached object even
            # though the /continue endpoint (a different DB session) has since updated it.
            result = await self.db.execute(
                select(ExploreSession.selected_module_ids).where(ExploreSession.id == session_id)
            )
            selected = result.scalar_one_or_none()
            if selected:
                return list(selected)
        return None

    async def _explore_and_scan_module_page(self, url: str, module_id: str, nav_hint: str):
        """
        Full human-like page exploration:
          1. AI page analysis (forms, tables, workflows)
          2. Step-scroll + interactive element extraction
          3. Click every button to capture dialogs/forms
          4. Click table rows — detect detail views, inline dialogs, hidden action columns
          5. Click page tabs — capture alternate content areas
          6. Build and persist a structured interaction guide
        """
        page = await self._explore_single_page(url, module_id, nav_hint=nav_hint, skip_navigate=False)
        if not page:
            return

        # Deep element scan (scrolls page, tests CRUD + action buttons)
        await self._log("INFO", "exploration", f"Deep-scanning interactive elements on '{nav_hint}'...")
        enriched_elements = await self._deep_scan_page_elements(page)

        # Table row interaction discovery
        await self._log("INFO", "exploration", f"Probing table rows on '{nav_hint}'...")
        row_discoveries = await self._explore_table_rows(page)

        # Tab content discovery
        tab_discoveries = await self._explore_page_tabs(page)

        # ── Pattern Intelligence Layer ─────────────────────────────────────────
        # Discover icon-based action buttons (edit/delete/approve/view)
        await self._log("INFO", "exploration", f"Scanning action icons on '{nav_hint}'...")
        action_icons = await asyncio.to_thread(self._discover_action_icons)

        # Detect status workflow tabs (Pending / Active / Approved / Rejected …)
        status_tabs = await asyncio.to_thread(self._detect_status_tabs)
        if status_tabs:
            status_tab_labels = [t["label"] for t in status_tabs if t.get("is_status_tab")]
            if status_tab_labels:
                await self._log("INFO", "exploration",
                    f"Status workflow tabs found: {', '.join(status_tab_labels)}")

        # Detect bulk-delete pattern (checkbox → Actions → Delete)
        bulk_delete_pattern = await self._discover_bulk_delete_pattern()

        # Detect approval workflow (needs status_tabs for tab navigation context)
        approve_pattern = await self._discover_approve_pattern(status_tabs)

        # Probe search no-data state
        search_no_data = await self._probe_search_no_data_state()
        # ── End Pattern Intelligence ───────────────────────────────────────────

        # Build and persist the structured interaction guide
        await self._store_interaction_guide(
            module_id, nav_hint, page,
            enriched_elements or [],
            row_discoveries=row_discoveries,
            tab_discoveries=tab_discoveries,
            action_icons=action_icons,
            status_tabs=status_tabs,
            bulk_delete_pattern=bulk_delete_pattern,
            approve_pattern=approve_pattern,
            search_no_data=search_no_data,
        )

    async def _hierarchical_explore(self, discover_only: bool = False):
        """Perform exploration by clicking through navigation to discover all URLs."""
        await self._log("MILESTONE", "exploration", "Starting UI-based URL discovery")
        
        # Reset to dashboard URL
        await asyncio.to_thread(self._browser.navigate, self._dashboard_url)
        
        # Wait for Angular SPA to render the DOM (up to 45 seconds)
        await self._log("INFO", "system", "Waiting for lazy-loaded sidebar to render...")
        for _ in range(15):
            has_sidebar = await asyncio.to_thread(self._browser.execute_script, """
            return (function() {
                function isVisible(el) {
                    if (!el) return false;
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none';
                }
                const NAV_SELS = ['nav', '[role="navigation"]', 'aside', '[role="menubar"]',
                                  '[class*="sidebar" i]', '[class*="sider" i]', '[class*="menu-bar" i]'];
                for (const sel of NAV_SELS) {
                    for (const el of document.querySelectorAll(sel)) {
                        if (isVisible(el)) {
                            const items = el.querySelectorAll('a, button, li, [role="menuitem"], mat-list-item, .nav-item, .menu-item, div.text-sm').length;
                            if (items >= 3) return true;
                        }
                    }
                }
                return false;
            })();
            """)
            if has_sidebar:
                break
            await asyncio.sleep(3.0)

        # 1. Discover all parent nav items
        parents = await asyncio.to_thread(self._scan_parent_navs)
        if not parents:
            await self._log("WARNING", "navigation",
                "Nav scan found 0 items — falling back to page-link discovery")
            parents = await asyncio.to_thread(self._discover_nav_from_page_links)
            if parents:
                await self._log("INFO", "navigation",
                    f"Link-based fallback found {len(parents)} candidate module(s)")
            else:
                await self._log("WARNING", "navigation",
                    "No navigation items found via any method — check that login succeeded and the dashboard has a sidebar/nav")

        await self._log("INFO", "navigation", f"Navigation scan: {len(parents)} parent navigation item(s) found")

        # ── Fast discovery path ────────────────────────────────────────────────
        # In discover_only mode we just save the nav item names immediately —
        # no clicking or page navigation required. The user selects modules and
        # then _explore_selected_modules handles the actual navigation + AI scan.
        if discover_only:
            # Load existing top-level modules for this app so we can upsert by name
            existing_result = await self.db.execute(
                select(ApplicationModule).where(
                    ApplicationModule.application_id == self._app.id,
                    ApplicationModule.parent_id.is_(None),
                )
            )
            existing_by_name: dict[str, ApplicationModule] = {
                m.name: m for m in existing_result.scalars().all()
            }
            created, updated = 0, 0
            for i, item in enumerate(parents):
                name = item["text"]
                if name in existing_by_name:
                    # Update metadata but NEVER wipe pages/workflows — those belong to prior explorations
                    m = existing_by_name[name]
                    m.is_accordion = bool(item.get("is_accordion"))
                    m.order_index = i
                    if item.get("href") and not m.url_pattern:
                        m.url_pattern = item.get("href")
                    updated += 1
                else:
                    module = ApplicationModule(
                        application_id=self._app.id,
                        name=name,
                        description=f"Navigation module: {name}",
                        url_pattern=item.get("href") or None,
                        icon="layout",
                        is_accordion=bool(item.get("is_accordion")),
                        parent_id=None,
                        order_index=i,
                    )
                    self.db.add(module)
                    created += 1
            await self.db.commit()
            await self._log("SUCCESS", "navigation",
                f"Discovery complete — {len(parents)} navigation module(s) found "
                f"({created} new, {updated} updated). Select which to explore deeply.")
            return

        # ── Full exploration path ─────────────────────────────────────────────
        # Cap at 80 — anything above is almost certainly picking up non-nav elements
        MAX_PARENTS = 80
        if len(parents) > MAX_PARENTS:
            await self._log("WARNING", "navigation",
                f"Found {len(parents)} nav items — capping at {MAX_PARENTS} to avoid non-navigation elements")
            parents = parents[:MAX_PARENTS]

        order_idx = 0
        discovered_urls = set()

        for p_idx, p_item in enumerate(parents):
            if self._should_stop:
                return

            parent_text = p_item["text"]
            is_accordion = p_item["is_accordion"]
            await self._log("INFO", "navigation",
                f"[{p_idx + 1}/{len(parents)}] Exploring: {parent_text}")

            # Reset to dashboard to ensure stable UI context
            await asyncio.to_thread(self._browser.navigate, self._dashboard_url)
            await asyncio.sleep(1.5)

            # Click the parent nav item by text; fall back to direct URL navigation
            # (needed for icon-only sidebars where there is no visible text to click by)
            clicked = await asyncio.to_thread(self._click_nav_item, parent_text)
            if not clicked:
                href = p_item.get("href", "").strip()
                if href and href not in ("#", "/", "javascript:void(0)", "javascript:;"):
                    base_url = self._app.base_url.rstrip("/")
                    nav_url = href if href.startswith("http") else base_url + href
                    await self._log("INFO", "navigation",
                        f"  Text-click failed for '{parent_text}' — navigating directly to {nav_url}")
                    await asyncio.to_thread(self._browser.navigate, nav_url)
                else:
                    await self._log("WARNING", "navigation",
                        f"  Could not navigate to '{parent_text}' (no href, click failed) — skipping")
                    continue
            await asyncio.sleep(1.5)

            # Check if URL actually changed — if not, try direct href navigation first
            current_url_after_click = await asyncio.to_thread(self._get_full_url)
            base_url = self._app.base_url.rstrip("/")
            url_unchanged = current_url_after_click.rstrip("/") == self._dashboard_url.rstrip("/")

            if url_unchanged and is_accordion:
                # Genuine accordion: try to find children that reveal on expand
                children = await asyncio.to_thread(self._scan_child_navs, parent_text)
            else:
                children = []

            if url_unchanged and not children:
                # URL didn't change and no accordion children — try direct href navigation
                href = p_item.get("href", "").strip()
                if href and href not in ("#", "/", "javascript:void(0)", "javascript:;"):
                    direct_url = href if href.startswith("http") else base_url + href
                    if direct_url.rstrip("/") != self._dashboard_url.rstrip("/"):
                        await self._log("INFO", "navigation",
                            f"  URL unchanged after click — navigating directly to {direct_url}")
                        await asyncio.to_thread(self._browser.navigate, direct_url)
                        await asyncio.sleep(1.5)
                        current_url_after_click = await asyncio.to_thread(self._get_full_url)
                        url_unchanged = current_url_after_click.rstrip("/") == self._dashboard_url.rstrip("/")

            if children:
                for c_idx, child in enumerate(children):
                    if self._should_stop: return
                    child_text = child["text"]
                    child_href = child.get("href", "").strip()
                    await self._log("INFO", "navigation",
                        f"  [{c_idx + 1}/{len(children)}] Sub-item: {parent_text} → {child_text}")

                    # Prefer direct navigation via child href
                    if child_href and child_href not in ("#", "/", "javascript:void(0)", "javascript:;"):
                        child_nav_url = child_href if child_href.startswith("http") else base_url + child_href
                        await asyncio.to_thread(self._browser.navigate, child_nav_url)
                        await asyncio.sleep(1.5)
                    else:
                        await asyncio.to_thread(self._browser.navigate, self._dashboard_url)
                        await asyncio.sleep(1.5)
                        await asyncio.to_thread(self._click_nav_item, parent_text)
                        await asyncio.sleep(1.0)
                        await asyncio.to_thread(self._click_nav_item, child_text)
                        await asyncio.sleep(1.5)

                    child_url = await asyncio.to_thread(self._get_full_url)
                    if await asyncio.to_thread(self._is_login_page) or child_url in discovered_urls:
                        continue
                    if child_url.rstrip("/") == self._dashboard_url.rstrip("/"):
                        continue

                    discovered_urls.add(child_url)
                    rel_url = child_url[len(base_url):] if child_url.startswith(base_url) else child_url
                    if not rel_url.startswith("/"): rel_url = "/" + rel_url

                    module = ApplicationModule(
                        application_id=self._app.id,
                        name=f"{parent_text} - {child_text}",
                        description=f"Module for {child_text}",
                        url_pattern=rel_url,
                        icon="layout",
                        parent_id=None,
                        order_index=order_idx,
                    )
                    self.db.add(module)
                    await self.db.flush()
                    self._module_map[rel_url] = module.id
                    order_idx += 1
                    await self._log("SUCCESS", "module",
                        f"Module saved: {parent_text} - {child_text} ({rel_url})")
                    await self._explore_and_scan_module_page(child_url, module.id, nav_hint=f"{parent_text} - {child_text}")
                await self.db.commit()

            else:
                # Standalone page (URL changed or direct nav worked)
                parent_url = current_url_after_click
                if await asyncio.to_thread(self._is_login_page) or parent_url in discovered_urls:
                    continue

                discovered_urls.add(parent_url)
                rel_url = parent_url[len(base_url):] if parent_url.startswith(base_url) else parent_url
                if not rel_url.startswith("/"): rel_url = "/" + rel_url

                module = ApplicationModule(
                    application_id=self._app.id,
                    name=parent_text,
                    description=f"Module for {parent_text}",
                    url_pattern=rel_url,
                    icon="layout",
                    parent_id=None,
                    order_index=order_idx,
                )
                self.db.add(module)
                await self.db.flush()
                self._module_map[rel_url] = module.id
                order_idx += 1
                await self._log("SUCCESS", "module", f"Module saved: {parent_text} ({rel_url})")
                await self._explore_and_scan_module_page(parent_url, module.id, nav_hint=parent_text)
                await self.db.commit()
