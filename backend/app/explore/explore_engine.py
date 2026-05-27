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
import time
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
)
from app.execution.browser_manager import BrowserManager
from app.execution.self_healing import SelfHealingEngine
from app.intelligence.semantic_extractor import SemanticUIExtractor
from app.intelligence.ai_client import get_ai_client
from app.core.security import decrypt_credential
from app.realtime.manager import connection_manager
from config import settings

log = structlog.get_logger()


SYSTEM_PROMPT_EXPLORE = """You are QAptain's Application Intelligence Engine. Extract comprehensive structured knowledge from a page for QA test generation.

RESPOND WITH VALID JSON ONLY. No markdown, no explanation.

{
  "page_name": "Human-readable name",
  "page_type": "dashboard|list|form|detail|modal|wizard|login|settings|report|calendar|upload",
  "module": "Which application module this page belongs to",
  "key_business_objects": ["Entity types this page manages, e.g. User, Sample, Order, Invoice"],

  "forms": [
    {
      "name": "Form name",
      "purpose": "Business action this form performs",
      "entity": "Entity being created or edited, e.g. Sample, User",
      "fields": [
        {
          "label": "Field label",
          "type": "text|email|password|number|date|datetime|dropdown|multiselect|checkbox|radio|textarea|file|search|autocomplete",
          "required": true,
          "validation": "Specific rules: min/max length, format, uniqueness constraint, allowed range",
          "options": ["Option 1", "Option 2"],
          "depends_on": "Label of field this depends on, or null"
        }
      ],
      "submit_action": "What happens on form submission",
      "success_message": "Expected success indicator after submit",
      "cancel_action": "What cancel or close does"
    }
  ],

  "tables": [
    {
      "name": "Table name",
      "entity": "Entity rows represent, e.g. Users, Samples",
      "purpose": "What data this table shows",
      "columns": [
        {"name": "Column header", "type": "text|number|date|status|boolean|link|badge|action", "sortable": true}
      ],
      "row_actions": ["Edit", "Delete", "View", "Approve", "Export"],
      "bulk_actions": ["Delete", "Export", "Assign"],
      "has_search": true,
      "has_filter": true,
      "has_pagination": true,
      "pagination_type": "page-numbers|load-more|infinite-scroll|none"
    }
  ],

  "workflows": [
    {
      "name": "Workflow name",
      "type": "crud_create|crud_read|crud_update|crud_delete|approval|search|export|import|navigation|login|upload",
      "entity": "Entity this workflow operates on",
      "entry_trigger": "Button, link or event that starts this workflow",
      "preconditions": ["User must be logged in", "Record must exist", "Location must be selected"],
      "steps": [
        {"step": 1, "action": "User clicks Add button", "expected_result": "Create form opens"},
        {"step": 2, "action": "User fills required fields", "expected_result": "Fields validate in real time"},
        {"step": 3, "action": "User clicks Submit", "expected_result": "Record saved, success message shown"}
      ],
      "success_criteria": ["Record appears in list", "Confirmation toast shown", "Count increments"],
      "error_paths": ["Required field missing shows inline error", "Duplicate entry rejected with message"]
    }
  ],

  "crud_operations": {
    "entity": "Primary entity managed on this page",
    "can_create": true,
    "can_read": true,
    "can_update": true,
    "can_delete": true,
    "create_trigger": "Add / New button label or null",
    "update_trigger": "Edit button label or null",
    "delete_trigger": "Delete button label or null",
    "requires_confirmation": true,
    "soft_delete": false
  },

  "navigation_structure": {
    "breadcrumbs": ["Home", "Module", "Page"],
    "parent_module": "Module this page belongs to",
    "child_pages": ["Sub-pages accessible from here"],
    "related_pages": ["Functionally related pages a tester should also test"]
  },

  "dynamic_behaviors": [
    {
      "trigger": "button_click|field_change|page_load|hover|scroll",
      "element": "Element label or description",
      "behavior": "modal_opens|section_expands|field_appears|field_hides|data_loads|redirect|toast_appears|dialog_opens",
      "description": "Specific observable change"
    }
  ],

  "navigation_links": ["Link text that navigates to another page or module"]
}"""


class ExploreEngine:
    """
    Semantic exploration engine that learns an application.
    Emits live semantic logs (not technical logs) throughout.
    """

    MAX_PAGES = 200   # hard cap — use percentage logic in run()

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

    async def run(self, session_id: str, application_id: str) -> None:
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

        await self._log("MILESTONE", "system", "Starting application exploration [v2-click-nav]")
        await self._emit_event("explore_started", {"session_id": session_id})

        # Clean up stale data from previous runs before starting fresh
        await self._cleanup_old_exploration_data(application_id)

        try:
            # Launch browser — 90-second hard timeout prevents hung ChromeDriver from blocking forever
            try:
                self._browser = await asyncio.wait_for(
                    asyncio.to_thread(BrowserManager.create, settings.SELENIUM_HEADLESS),
                    timeout=90.0,
                )
            except asyncio.TimeoutError:
                await self._fail_session(session,
                    "Browser failed to start within 90 seconds — "
                    "check Chrome / ChromeDriver installation and that no zombie Chrome processes are running")
                return
            self._extractor = SemanticUIExtractor(self._browser.driver)
            self._healer = SelfHealingEngine(self._browser.driver)

            # Phase 1: Login
            login_ok = await self._phase_login(app)
            if not login_ok:
                await self._fail_session(session, "Login failed during exploration")
                return

            # Phase 2: Discover modules from navigation
            await self._phase_discover_modules()

            # Phase 2b: Click each nav item to capture REAL URLs (handles SPA routing)
            await self._capture_real_module_urls()

            # Phase 3: Deep exploration — AI analysis + element extraction
            if session.mode != ExploreMode.SKIP:
                await self._log("INFO", "exploration",
                    "Exploration mode: SMART — exploring all discovered URLs")
                await self._phase_explore_pages(self.MAX_PAGES)
                # Deep element scan — extracts detailed selectors, CRUD forms, and interactive elements
                await self._phase_deep_scan_elements()

            # Phase 4: Build knowledge graph
            kg = await self._phase_build_knowledge_graph(application_id, session_id)

            # Phase 5: Update application knowledge reference
            app.knowledge_graph_id = kg.id if kg else None
            await self.db.commit()

            # Phase 6: Generate AI test scenarios from exploration data
            scenarios_count = await self._generate_test_scenarios(application_id, session_id)

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
        # Angular SPAs with heavy scripts (YLIMS UAT) can take 60-90s to bootstrap,
        # especially when the Selenium page load timeout fires first at 60s.
        await self._log("INFO", "login", "Waiting for login form to render (up to 90s)")
        page_ready = await asyncio.to_thread(self._wait_for_any_input, timeout=90)
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

        # Click login button
        login_button = (None, None)
        for label in ("Sign In", "Login", "Log In", "Submit", "SIGN IN"):
            login_button = self._healer.find_element(label)
            if login_button[0]:
                break

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
        for lbl in ("Submit", "Continue", "Proceed", "Sign In", "Login", "OK", "Confirm", "Next", "Go"):
            result = self._healer.find_element(lbl)
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
        """
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

        for i, page in enumerate(pages[:self.MAX_PAGES]):
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

    async def _deep_scan_page_elements(self, page: ApplicationPage):
        """Extract and persist all interactive elements for one page."""
        # Extract all interactive elements via JS
        raw_elements: list[dict] = await asyncio.to_thread(self._extract_page_elements_js)
        if not raw_elements:
            return

        # Test CRUD buttons: click → capture dialog → close
        enriched: list[dict] = []
        for el in raw_elements:
            category = el.get("category", "")
            enriched_el = dict(el)

            if category in ("add", "edit", "delete") and el.get("selectors"):
                dialog_data = await self._test_crud_operation(el, page.id)
                if dialog_data:
                    enriched_el["dialog"] = dialog_data
                    if dialog_data.get("fields"):
                        form_key = f"{category}_form"
                        enriched_el["dynamic_reveals"] = [{
                            "trigger": "click",
                            "type": form_key,
                            "title": dialog_data.get("title", ""),
                            "fields": dialog_data["fields"],
                        }]

            enriched.append(enriched_el)

        # Update page.forms with any discovered dialog forms
        await self._merge_dialog_forms_into_page(page, enriched)

        # Persist SemanticElement records
        await self._save_semantic_elements(enriched, page.id)

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
                return r.width > 0 && r.height > 0
                    && s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0';
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

    async def _test_crud_operation(self, el_info: dict, page_id: str) -> dict | None:
        """
        Click an add/edit/delete button, capture the resulting dialog/form, then close it.
        Returns the dialog structure or None if nothing appeared.
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
                fields.push({
                    label: label.slice(0,100),
                    type: inp.tagName.toLowerCase() === 'select' ? 'dropdown'
                          : (inp.getAttribute('type')||'text'),
                    name: inp.getAttribute('name')||'',
                    required: inp.required || inp.getAttribute('aria-required')==='true',
                });
            }

            const titleEl = dialog.querySelector(
                'h1,h2,h3,h4,[class*="title"],[class*="header"] h1,[class*="header"] h2'
            );
            const title = titleEl ? titleEl.textContent.trim().slice(0,120) : 'Dialog';
            return {type:'dialog', title, fields};
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

    async def _generate_test_scenarios(self, application_id: str, session_id: str) -> int:
        """
        Phase 6: Generate AI test scenarios from exploration data.
        Uses batched generation (5 modules per call) to avoid token-limit truncation
        and content-filter issues with large single-shot prompts.
        """
        await self._log("MILESTONE", "scenarios", "Generating test scenarios from exploration data")

        # Delete old AI-generated scenarios so we regenerate fresh ones
        existing_result = await self.db.execute(
            select(Scenario).where(
                Scenario.application_id == application_id,
                Scenario.source == "ai_generated",
            )
        )
        for old in existing_result.scalars().all():
            await self.db.delete(old)
        await self.db.commit()

        # Load modules, pages, workflows
        mods_result = await self.db.execute(
            select(ApplicationModule).where(ApplicationModule.application_id == application_id)
        )
        modules = list(mods_result.scalars().all())

        pages_result = await self.db.execute(
            select(ApplicationPage)
            .join(ApplicationModule, ApplicationPage.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == application_id)
            .limit(30)
        )
        pages = list(pages_result.scalars().all())

        wf_result = await self.db.execute(
            select(ApplicationWorkflow)
            .join(ApplicationModule, ApplicationWorkflow.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == application_id)
            .limit(20)
        )
        workflows = list(wf_result.scalars().all())

        if not modules:
            await self._log("WARNING", "scenarios", "No modules found — skipping scenario generation")
            return 0

        # Build per-module detail context (forms, tables, workflows)
        def _module_ctx(m) -> dict:
            m_pages = [p for p in pages if p.module_id == m.id]
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
            m_wfs = [w.name for w in workflows if w.module_id == m.id][:6]

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

        # ── Batch: 3 modules per AI call (smaller batches = more scenarios without truncation) ──
        BATCH_SIZE = 3
        all_scenario_infos: list[dict] = []
        batches = [modules[i:i+BATCH_SIZE] for i in range(0, len(modules), BATCH_SIZE)]

        for batch_idx, batch in enumerate(batches):
            batch_ctx = [_module_ctx(m) for m in batch]
            module_names_str = ", ".join(m.name for m in batch)

            prompt = (
                f"{app_header}"
                f"MODULES TO COVER: {module_names_str}\n\n"
                f"MODULE DETAILS:\n{json.dumps(batch_ctx, indent=1)}\n\n"
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
                            max_tokens=6000,
                        ),
                        timeout=90.0,
                    )
                    content = response.content.strip()
                    if not content:
                        log.warning("Scenario batch returned empty", batch=batch_idx, attempt=attempt)
                        continue
                    data = response.json()
                    batch_scenarios = data.get("scenarios") or []
                    if batch_scenarios:
                        break
                except Exception as e:
                    log.warning("Scenario batch failed", batch=batch_idx, attempt=attempt, error=str(e)[:80])

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
            metadata={"session_id": self._session_id, "source": "exploration"},
            confidence=0.9,
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
        for label in ("Sign In", "Login", "Log In", "Submit", "SIGN IN", "LOG IN", "LOGIN", "Continue"):
            result = self._healer.find_element(label)
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

    def _wait_for_any_input(self, timeout: int = 30) -> bool:
        """
        Block until at least one <input> element appears in the DOM, iframes, or Shadow DOM.
        Returns True as soon as one is found; False if timeout expires.
        """
        from selenium.webdriver.common.by import By
        import time as _time
        deadline = _time.time() + timeout
        while _time.time() < deadline:
            try:
                inputs = self._browser.driver.find_elements(By.TAG_NAME, "input")
                if inputs:
                    return True
            except Exception:
                pass

            # Shadow DOM piercing (Angular Material, web components)
            try:
                shadow_count = self._browser.execute_script("""
                    function countShadowInputs(root) {
                        let n = 0;
                        try {
                            if (root.tagName === 'INPUT') n++;
                            if (root.shadowRoot) n += countShadowInputs(root.shadowRoot);
                            for (const c of (root.children || [])) n += countShadowInputs(c);
                        } catch(e) {}
                        return n;
                    }
                    return countShadowInputs(document.body);
                """)
                if shadow_count and int(shadow_count) > 0:
                    return True
            except Exception:
                pass

            # Iframe scan every ~2s
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
                if self._browser.driver.find_elements(By.TAG_NAME, "input"):
                    return True
            except Exception:
                pass

        return False

    def _count_page_inputs(self) -> int:
        """Count all <input> elements on the page (including inside iframes)."""
        from selenium.webdriver.common.by import By
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
        for label in ("Next", "Continue", "Proceed", "Sign In", "Login"):
            result = self._healer.find_element(label)
            if result[0]:
                try:
                    result[0].click()
                    clicked_next = True
                    await self._log("INFO", "login", f"Two-step login: clicked '{label}' button")
                    break
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

        # Submit
        login_button = (None, None)
        for label in ("Sign In", "Login", "Log In", "Submit", "SIGN IN", "Next"):
            login_button = self._healer.find_element(label)
            if login_button[0]:
                break
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
        Fast login field detection using direct find_elements (no per-strategy waits).
        Returns (username_el, password_el). Either may be None.

        Handles:
        - Standard HTML inputs
        - Angular Material (inputs may have is_displayed()=False due to CSS)
        - Inputs inside iframes
        - Hidden-but-enabled inputs (skips type=hidden/submit/button only)
        """
        from selenium.webdriver.common.by import By

        SKIP_TYPES = {"hidden", "submit", "button", "checkbox", "radio", "file", "image"}

        def scan_inputs(driver_or_context):
            try:
                all_inputs = driver_or_context.find_elements(By.TAG_NAME, "input")
            except Exception:
                return None, None

            pw_el = None
            user_el = None

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

            return user_el, pw_el

        # Try main document first
        user_el, pw_el = scan_inputs(self._browser.driver)
        if pw_el:
            return user_el, pw_el

        # Try each iframe — Angular / legacy apps often render login inside iframes
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

        state = self._extractor.extract_page_state()
        nav_items = state.get("navigation", {}).get("items", [])
        # Store for Phase 2b so we don't re-detect with different selectors
        self._raw_nav_items = nav_items or []

        if nav_items:
            await self._log("INFO", "navigation", f"Navigation detected with {len(nav_items)} items")

            # Use AI to categorize navigation items into modules
            nav_text = "\n".join(f"- {item['text']} ({item.get('href', '')})" for item in nav_items)

            response = await asyncio.wait_for(
                self.ai.complete(
                    system="""Analyze navigation items and group them into logical application modules.
Output JSON: {"modules": [{"name": "Module Name", "description": "what it does", "url_pattern": "/path", "icon": "lucide_icon_name", "tags": ["crud", "table"]}]}""",
                    user=f"""Application description: {self._app.description or 'Business application'}

Navigation items:
{nav_text}

Group these into logical modules.""",
                    fast=True,
                    json_mode=True,
                ),
                timeout=30.0,
            )

            try:
                module_data = response.json()
                for mod_info in module_data.get("modules", []):
                    module = ApplicationModule(
                        application_id=self._app.id,
                        name=mod_info.get("name", "Unknown"),
                        description=mod_info.get("description", ""),
                        url_pattern=mod_info.get("url_pattern", ""),
                        icon=mod_info.get("icon", "layout"),
                        semantic_tags=mod_info.get("tags", []),
                        order_index=len(self._module_map),
                    )
                    self.db.add(module)
                    await self.db.flush()
                    if mod_info.get("url_pattern"):
                        self._module_map[mod_info["url_pattern"]] = module.id

                    await self._log("SUCCESS", "navigation", f"Module discovered: {mod_info.get('name')}")

                await self.db.commit()
            except Exception as e:
                log.warning("Module categorization failed", error=str(e))
                await self._discover_modules_from_nav(nav_items)
        else:
            await self._log("WARNING", "navigation", "No navigation structure detected — trying page analysis")
            await self._discover_modules_from_links()
            # If no modules from links, try extracting visible items (sidebar menu, tiles, etc.)
            modules_found = await self._count_modules(self._app.id)
            if modules_found == 0:
                await self._discover_modules_from_visible_items()

    async def _discover_modules_from_nav(self, nav_items: list[dict]):
        """Fallback: create modules directly from nav items."""
        for item in nav_items[:15]:
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
                timeout=30.0,
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

                # If the nav item already has a usable href, record it directly
                if href and href not in ("#", "/", "javascript:void(0)", "javascript:;"):
                    real_url = href if href.startswith("http") else base_url + href
                    url_map[text] = real_url
                    self._discovered_urls.add(real_url)
                    await self._log("INFO", "navigation", f"Nav href: {text!r} → {href}")
                    continue

                # Otherwise click and observe URL / title change
                try:
                    before_url = await asyncio.to_thread(self._get_full_url)
                    before_title = await asyncio.to_thread(self._get_page_title)
                    clicked = await asyncio.to_thread(self._click_nav_item, text)
                    if not clicked:
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
            const NAV_SELS = ['nav','[role="navigation"]','aside','[class*="sidebar" i]',
                              '[class*="menu" i]','body'];
            for (const sel of NAV_SELS) {
                const container = document.querySelector(sel);
                if (!container) continue;
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

    def _get_revealed_child_items(self, parent_text: str) -> list[str]:
        """After clicking a parent nav item, collect any newly visible child items."""
        return self._browser.execute_script("""
        (function() {
            const parent = arguments[0].toLowerCase();
            function isVisible(el) {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden';
            }
            function getDirectText(el) {
                let t = '';
                for (const n of el.childNodes) { if (n.nodeType === 3) t += n.textContent; }
                return (t.trim() || el.textContent || '').trim().replace(/\\s+/g, ' ').slice(0, 80);
            }
            const NOISE = new Set(['logout','sign out','profile','help','about','home','settings']);

            // Find the parent element
            let parentEl = null;
            for (const el of document.querySelectorAll('*')) {
                if (!isVisible(el)) continue;
                const t = getDirectText(el).toLowerCase();
                if (t === parent || t.startsWith(parent.slice(0,15))) {
                    parentEl = el; break;
                }
            }
            if (!parentEl) return [];

            // Submenu is often the next sibling ul/div, or a child with aria-expanded
            const expandedEl = parentEl.querySelector('[aria-expanded="true"]')
                || (parentEl.hasAttribute('aria-expanded') ? parentEl : null)
                || parentEl;
            const submenu = expandedEl.nextElementSibling
                || expandedEl.querySelector('ul, ol, [role="group"], [role="menu"]');

            const searchRoot = submenu || expandedEl.parentElement || parentEl.parentElement;
            if (!searchRoot) return [];

            const seen = new Set([parent]);
            const results = [];
            for (const el of searchRoot.querySelectorAll(
                'a, li, [role="menuitem"], [role="treeitem"]'
            )) {
                if (!isVisible(el)) continue;
                const t = getDirectText(el);
                if (!t || t.length < 2 || t.length > 80) continue;
                if (NOISE.has(t.toLowerCase()) || seen.has(t.toLowerCase())) continue;
                seen.add(t.toLowerCase());
                results.push(t);
            }
            return results.slice(0, 20);
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
        """
        await self._log("MILESTONE", "exploration", f"Starting deep page exploration (max {max_pages} pages)")

        urls_to_visit = await self._collect_urls_to_visit()
        await self._log("INFO", "exploration",
            f"URL list: {len(urls_to_visit)} URLs, {len(self._raw_nav_items)} nav items available")

        # Primary: click-based navigation when nav items are present.
        # This is the only session-safe approach for SPAs with short-lived JWTs.
        if self._raw_nav_items:
            await self._explore_via_nav_clicks(max_pages)

            # Secondary: visit any discovered URLs not yet reached via nav clicks
            # (Phase 2b child URLs, deep links, etc.)
            remaining = max_pages - len(self._phase3_analyzed)
            if remaining > 0 and urls_to_visit:
                await self._log("INFO", "exploration",
                    f"Visiting up to {remaining} additional URLs not covered by nav clicks")
                for url, module_id in urls_to_visit:
                    if remaining <= 0:
                        break
                    if url in self._phase3_analyzed:
                        continue
                    try:
                        await self._explore_single_page(url, module_id)
                        self._discovered_urls.add(url)
                        remaining -= 1
                        await asyncio.sleep(0.5)
                    except Exception as e:
                        log.warning("URL fallback exploration failed", url=url, error=str(e))

            await self._log("SUCCESS", "exploration",
                f"Page exploration complete — {len(self._phase3_analyzed)} pages analyzed")
            return

        # Fallback: URL-based navigation for non-SPA apps (no nav items detected)
        if not urls_to_visit:
            await self._explore_via_nav_clicks(max_pages)
            return

        for url, module_id in urls_to_visit:
            if len(self._phase3_analyzed) >= max_pages:
                break
            if url in self._phase3_analyzed:
                continue
            try:
                await self._explore_single_page(url, module_id)
                self._discovered_urls.add(url)
                if len(self._phase3_analyzed) % 5 == 0:
                    await self._log("INFO", "exploration",
                        f"Explored {len(self._phase3_analyzed)} pages so far")
                await asyncio.sleep(0.5)
            except Exception as e:
                log.warning("Page exploration failed", url=url, error=str(e))

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

        for item in items_to_click[:max_pages]:
            if visited >= max_pages:
                break
            text = item.get("text", "").strip()
            href = item.get("href", "").strip()
            if not text:
                continue

            try:
                await self._log("INFO", "exploration", f"Navigating to: {text}")

                # Return to dashboard before each top-level nav click
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

                if page_title in seen_titles and after_url == before_url:
                    # Parent item that didn't navigate — try expanding children
                    child_items = await asyncio.to_thread(self._get_revealed_child_items, text)
                    if child_items:
                        await self._log("INFO", "exploration",
                            f"{text} → expanded {len(child_items)} sub-items: {', '.join(child_items[:5])}")
                    for child_text in child_items:
                        if visited >= max_pages:
                            break
                        await self._log("INFO", "exploration", f"Navigating to: {text} → {child_text}")
                        child_clicked = await asyncio.to_thread(self._click_nav_item, child_text)
                        if not child_clicked:
                            continue
                        await asyncio.sleep(1.0)
                        if not await asyncio.to_thread(self._is_login_page):
                            child_url = await asyncio.to_thread(self._get_full_url)
                            mod_id = await self._find_module_for_url(child_url)
                            await self._explore_single_page(child_url, mod_id, nav_hint=f"{text} → {child_text}", skip_navigate=True)
                            self._discovered_urls.add(child_url)
                            visited += 1
                else:
                    seen_titles.add(page_title)
                    mod_id = await self._find_module_for_url(after_url)
                    await self._explore_single_page(after_url, mod_id, nav_hint=text, skip_navigate=True)
                    self._discovered_urls.add(after_url)
                    visited += 1

                if visited % 5 == 0:
                    await self._log("INFO", "exploration", f"Click-explored {visited} pages so far")

                # Return to dashboard for next nav click
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

    async def _explore_single_page(self, url: str, module_id: str | None, nav_hint: str | None = None, skip_navigate: bool = False):
        """Explore a single page and build its semantic map."""
        try:
            self._phase3_analyzed.add(url)  # mark attempted — prevents duplicate analysis
            if not skip_navigate:
                await asyncio.to_thread(self._browser.navigate, url)
                await asyncio.sleep(2.0)  # Angular SPAs need ~2s to bootstrap after a full load

            # Skip error pages — not worth analyzing
            page_title = await asyncio.to_thread(lambda: self._browser.driver.title)
            if any(code in page_title for code in ("502", "503", "504", "404", "403", "500")):
                await self._log("WARNING", "exploration", f"Skipping error page: {page_title} ({url})")
                return

            # Also skip if the page source is tiny (proxy/server error)
            page_src_len = await asyncio.to_thread(
                lambda: len(self._browser.driver.page_source)
            )
            if page_src_len < 500:
                await self._log("WARNING", "exploration", f"Skipping near-empty page: {url}")
                return

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
                    return

            state = self._extractor.extract_page_state()
            page_name = state.get("page", "Unknown Page")
            display_name = nav_hint or page_name

            await self._log("INFO", "exploration", f"Analyzing: {display_name}")

            # AI-powered page analysis with keepalive to prevent session expiry
            page_analysis = await self._analyze_with_keepalive(state, url)

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

        except Exception as e:
            await self._log("WARNING", "exploration", f"Could not fully analyze page at {url}: {str(e)[:100]}")

    async def _analyze_with_keepalive(self, state: dict, url: str) -> dict:
        """
        Run AI page analysis while pinging the server every 25s to keep the SPA session alive.
        YLIMS and similar apps can expire the session during the 2-3 minute AI wait.
        """
        keepalive_url = self._dashboard_url or url
        stop = asyncio.Event()

        async def _keepalive():
            while not stop.is_set():
                await asyncio.sleep(25)
                if stop.is_set():
                    break
                try:
                    await asyncio.to_thread(
                        self._browser.execute_script,
                        f"fetch('{keepalive_url}', "
                        f"{{method:'HEAD',credentials:'include',cache:'no-store'}}).catch(()=>{{}})"
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
        """Use AI to deeply understand a page's semantic structure."""
        # Build compact representation — NOT raw HTML
        compact_state = {
            "url": url,
            "page": state.get("page"),
            "workflow_stage": state.get("workflow_stage"),
            "visible_elements": state.get("visible_elements", [])[:30],
            "page_text": state.get("page_text_summary", ""),
            "navigation": state.get("navigation", {}),
        }

        app_context = (
            f"Application: {self._app.name or 'Business application'}\n"
            f"Description: {self._app.description or 'Web application'}\n"
            f"Base URL: {self._app.base_url}"
        )

        try:
            response = await asyncio.wait_for(
                self.ai.complete(
                    system=SYSTEM_PROMPT_EXPLORE,
                    user=f"{app_context}\n\nPage semantic state:\n{compact_state}",
                    fast=True,
                    json_mode=True,
                    max_tokens=3000,
                ),
                timeout=60.0,
            )
            return response.json()
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
        for pattern, module_id in self._module_map.items():
            if pattern in url:
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
        session.status = ExploreStatus.FAILED
        session.error_message = reason
        session.completed_at = datetime.utcnow()
        await self.db.commit()
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

    async def _log(self, level: str, category: str, message: str, metadata: dict | None = None):
        """Emit semantic log — not technical logs."""
        from datetime import timezone
        now = datetime.now(timezone.utc)
        entry = ExploreLog(
            session_id=self._session_id,
            level=level,
            category=category,
            message=message,
            extra=metadata or {},
        )
        self.db.add(entry)
        await self.db.commit()

        # Include explicit UTC timestamp (ISO 8601 with Z suffix) so the frontend
        # can correctly convert to local time regardless of server timezone.
        await self._emit_event("explore_log", {
            "session_id": self._session_id,
            "level": level,
            "category": category,
            "message": message,
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        })

    async def _emit_event(self, event: str, data: dict):
        await connection_manager.broadcast_json({"event": event, **data})

    async def _load_session(self, session_id: str) -> ExploreSession | None:
        result = await self.db.execute(select(ExploreSession).where(ExploreSession.id == session_id))
        return result.scalar_one_or_none()

    async def _load_application(self, application_id: str) -> Application | None:
        result = await self.db.execute(select(Application).where(Application.id == application_id))
        return result.scalar_one_or_none()
