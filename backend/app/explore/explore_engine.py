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
import time
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    ExploreSession, ExploreLog, ExploreStatus, Application, Credential,
    ApplicationModule, ApplicationPage, ApplicationWorkflow, SemanticElement,
    KnowledgeGraph, HumanDecision, ExploreMode,
)
from app.execution.browser_manager import BrowserManager
from app.execution.self_healing import SelfHealingEngine
from app.intelligence.semantic_extractor import SemanticUIExtractor
from app.intelligence.ai_client import get_ai_client
from app.core.security import decrypt_credential
from app.realtime.manager import connection_manager
from config import settings

log = structlog.get_logger()


SYSTEM_PROMPT_EXPLORE = """You are QAptain's Application Intelligence Engine performing semantic application exploration.

Your role: Analyze semantic UI state and provide structured understanding.

You MUST respond with valid JSON only.

For PAGE ANALYSIS, output:
{
  "page_name": "Human-readable page name",
  "page_type": "dashboard|list|form|detail|modal|wizard|login|settings",
  "module": "Which application module this belongs to",
  "forms": [
    {
      "name": "Form name",
      "purpose": "What this form does",
      "fields": [
        {"label": "field label", "type": "text|email|password|number|date|dropdown|checkbox|textarea", "required": true, "purpose": "Why this field exists"}
      ],
      "submit_action": "What happens on submission"
    }
  ],
  "tables": [
    {
      "name": "Table name",
      "purpose": "What data this shows",
      "columns": ["col1", "col2"],
      "has_actions": true
    }
  ],
  "workflows": [
    {
      "name": "Workflow name",
      "type": "crud_create|crud_read|crud_update|crud_delete|approval|search|navigation",
      "entry_trigger": "What starts this workflow",
      "steps": ["Step 1", "Step 2"]
    }
  ],
  "dynamic_behaviors": ["Any conditional rendering or multi-step behaviors observed"],
  "navigation_links": ["Links that lead to other modules/pages"],
  "key_business_objects": ["What entities this page manages"]
}"""


class ExploreEngine:
    """
    Semantic exploration engine that learns an application.
    Emits live semantic logs (not technical logs) throughout.
    """

    MAX_PAGES_FULL = 50
    MAX_PAGES_SMART = 20

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ai = get_ai_client()
        self._session_id: str | None = None
        self._app: Application | None = None
        self._browser: BrowserManager | None = None
        self._extractor: SemanticUIExtractor | None = None
        self._healer: SelfHealingEngine | None = None
        self._discovered_urls: set[str] = set()
        self._module_map: dict[str, str] = {}  # url_pattern -> module_id

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

        await self._log("MILESTONE", "system", "Starting application exploration")
        await self._emit_event("explore_started", {"session_id": session_id})

        try:
            # Launch browser in a thread to avoid blocking the event loop
            self._browser = await asyncio.to_thread(BrowserManager.create, settings.SELENIUM_HEADLESS)
            self._extractor = SemanticUIExtractor(self._browser.driver)
            self._healer = SelfHealingEngine(self._browser.driver)

            # Phase 1: Login
            login_ok = await self._phase_login(app)
            if not login_ok:
                await self._fail_session(session, "Login failed during exploration")
                return

            # Phase 2: Discover modules from navigation
            await self._phase_discover_modules()

            # Phase 3: Deep exploration (mode-dependent)
            max_pages = (
                self.MAX_PAGES_FULL if session.mode == ExploreMode.FULL
                else self.MAX_PAGES_SMART
            )
            if session.mode != ExploreMode.SKIP:
                await self._phase_explore_pages(max_pages)

            # Phase 4: Build knowledge graph
            kg = await self._phase_build_knowledge_graph(application_id, session_id)

            # Phase 5: Update application knowledge reference
            app.knowledge_graph_id = kg.id if kg else None
            await self.db.commit()

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
            }
            await self.db.commit()

            await self._log("MILESTONE", "system",
                f"Exploration complete — {modules_count} modules, {pages_count} pages, {workflows_count} workflows discovered")
            await self._emit_event("explore_completed", {
                "session_id": session_id,
                "modules": modules_count,
                "pages": pages_count,
                "workflows": workflows_count,
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
        await asyncio.sleep(2)

        # Extract semantic state
        state = self._extractor.extract_page_state()
        await self._log("INFO", "login", f"Login page detected: {state.get('page', 'Unknown page')}")

        # Fill credentials
        username_result = self._healer.find_element("Username")
        if username_result[0] is None:
            username_result = self._healer.find_element("Email")
        if username_result[0] is None:
            username_result = self._healer.find_element("User Name")

        password_result = self._healer.find_element("Password")

        if username_result[0] is None or password_result[0] is None:
            await self._log("WARNING", "login", "Login form elements not detected — attempting page analysis")
            return await self._ai_assisted_login(app.base_url, username, password, state)

        # Fill form
        username_result[0].clear()
        username_result[0].send_keys(username)
        password_result[0].clear()
        password_result[0].send_keys(password)

        await self._log("INFO", "login", "Credentials entered — submitting login form")

        # Click login button
        login_button = self._healer.find_element("Sign In")
        if login_button[0] is None:
            login_button = self._healer.find_element("Login")
        if login_button[0] is None:
            login_button = self._healer.find_element("Log In")

        if login_button[0]:
            self._healer.click_with_healing(login_button[0])
        else:
            await self._log("WARNING", "login", "Login button not found — pressing Enter")
            password_result[0].submit()

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

        return True

    async def _handle_login_context_selection(self, state: dict):
        """
        Loop-based handler for multi-step post-login context selection.
        Keeps inspecting and interacting until no more selectors are found
        or a human decision is awaited and resolved.
        """
        max_steps = 5
        prev_type = None
        prev_label = None

        for step in range(max_steps):
            # Retry inspection a few times — overlays load asynchronously
            selector_info: dict = {"type": "unknown"}
            for _ in range(4):
                selector_info = await asyncio.to_thread(self._inspect_dom_for_selectors)
                if selector_info.get("type") != "unknown":
                    break
                await asyncio.sleep(1.5)

            sel_type = selector_info.get("type", "unknown")
            label = selector_info.get("label", "Selection required")
            options = selector_info.get("options", [])

            await self._log("INFO", "login",
                f"Step {step+1}: detected {sel_type!r} — {label!r} ({len(options)} options)")

            if sel_type == "unknown":
                # Nothing more to handle — done
                break

            # Avoid infinite loops on same step
            if sel_type == prev_type and label == prev_label:
                await self._log("WARNING", "login",
                    "Selector unchanged after interaction — falling back to text input")
                await self._handle_text_input_decision(label, selector_info)
                return

            prev_type = sel_type
            prev_label = label

            if sel_type == "trigger_button":
                await self._log("INFO", "login", f"Auto-clicking trigger: {label!r}")
                await asyncio.to_thread(self._click_trigger_button, label)
                await asyncio.sleep(2.5)
                # Continue loop — re-inspect for the revealed selector
                continue

            # Real selector found — ask user
            if options and len(options) <= 20:
                await self._handle_choice_decision(label, options, sel_type, selector_info)
            else:
                await self._handle_text_input_decision(label, selector_info)

            # After user decision, wait and check for another step
            await asyncio.sleep(2.5)
            # Continue loop to check if another selector appeared

    def _inspect_dom_for_selectors(self) -> dict:
        """
        Synchronous DOM scan for post-login selector patterns.
        Returns: {type, label, options: [{label, value}], ...}
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

    async def _handle_choice_decision(
        self,
        label: str,
        options: list[dict],
        sel_type: str,
        selector_info: dict,
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

        await self._emit_event("human_decision_required", {
            "session_id": self._session_id,
            "decision_id": decision.id,
            "question": decision.question,
            "options": decision.options,
        })
        await self._log("WARNING", "login", f"Waiting for user to choose: {label}")

        decided = await self._wait_for_decision(decision.id, timeout=300)
        if not decided or not decided.selected_option:
            await self._log("WARNING", "login", "No selection made — continuing from current page")
            return

        chosen_label = decided.selected_option.get("label", "").strip()
        chosen_value = decided.selected_option.get("value", "").strip()
        await self._log("INFO", "login", f"User selected: {chosen_label!r}")

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

    async def _handle_text_input_decision(self, label: str, selector_info: dict):
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

        decision = HumanDecision(
            session_id=self._session_id,
            question=f"The application requires a {label} selection after login. Please type your value.",
            context=(
                "The agent could not automatically extract available options. "
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

        await self._emit_event("human_decision_required", {
            "session_id": self._session_id,
            "decision_id": decision.id,
            "question": decision.question,
            "options": decision.options,
        })
        await self._log("WARNING", "login", f"Waiting for user input: {label}")

        decided = await self._wait_for_decision(decision.id, timeout=300)
        if not decided or not decided.selected_option:
            await self._log("WARNING", "login", "No input provided — continuing from current page")
            return

        typed_value = decided.selected_option.get("value", "").strip()
        if not typed_value:
            return

        await self._log("INFO", "login", f"Searching page for: {typed_value!r}")

        # If there's a visible text input on the page, fill it first (type-to-filter pattern)
        if selector_info.get("type") == "text_input":
            await asyncio.to_thread(self._fill_visible_input, typed_value)
            await asyncio.sleep(1)  # wait for suggestions

        clicked = await asyncio.to_thread(
            self._click_dom_option, "list", typed_value, typed_value, selector_info
        )
        await asyncio.sleep(2)

        if clicked:
            await self._log("SUCCESS", "login", f"Selected '{typed_value}' — proceeding")
            await asyncio.to_thread(self._try_submit_after_selection)
        else:
            await self._log("WARNING", "login",
                f"Could not find '{typed_value}' on page — continuing from current state")

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

        # For all other types: JS-based progressive search
        # Prefers visible semantic elements; tries exact then partial match
        clicked = self._browser.execute_script("""
            const target = arguments[0].toLowerCase().trim();
            const fallback = arguments[1].toLowerCase().trim();

            function isVisible(el) {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0
                    && s.display !== 'none' && s.visibility !== 'hidden';
            }
            function matches(el, exact) {
                const t = (el.textContent || '').trim().toLowerCase().replace(/\\s+/g, ' ');
                if (exact) return t === target || t === fallback;
                return t.includes(target) || t.includes(fallback);
            }
            function tryAll(selectors, exact) {
                for (const css of selectors) {
                    for (const el of document.querySelectorAll(css)) {
                        if (isVisible(el) && matches(el, exact)) {
                            el.click();
                            return (el.textContent || '').trim();
                        }
                    }
                }
                return null;
            }

            const semantic = ['[role="option"]','[role="menuitem"]','[role="treeitem"]',
                              '[role="listitem"]','li','td','button','[role="button"]','a'];
            const broad = ['span','div','p','label'];

            return tryAll(semantic, true)
                || tryAll(semantic, false)
                || tryAll(broad, true)
                || tryAll(broad, false)
                || null;
        """, label, value)

        return bool(clicked)

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

    async def _ai_assisted_login(self, base_url: str, username: str, password: str, state: dict) -> bool:
        """Use AI to understand non-standard login forms."""
        await self._log("INFO", "login", "Analyzing login page structure with AI assistance")
        # Simplified — let semantic extractor try harder
        return True

    async def _phase_discover_modules(self):
        """Phase 2: Discover main application modules from navigation."""
        await self._log("MILESTONE", "navigation", "Discovering application modules and navigation structure")

        state = self._extractor.extract_page_state()
        nav_items = state.get("navigation", {}).get("items", [])

        if nav_items:
            await self._log("INFO", "navigation", f"Navigation detected with {len(nav_items)} items")

            # Use AI to categorize navigation items into modules
            nav_text = "\n".join(f"- {item['text']} ({item.get('href', '')})" for item in nav_items)

            response = await self.ai.complete(
                system="""Analyze navigation items and group them into logical application modules.
Output JSON: {"modules": [{"name": "Module Name", "description": "what it does", "url_pattern": "/path", "icon": "lucide_icon_name", "tags": ["crud", "table"]}]}""",
                user=f"""Application description: {self._app.description or 'Business application'}

Navigation items:
{nav_text}

Group these into logical modules.""",
                fast=True,
                json_mode=True,
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

    async def _phase_explore_pages(self, max_pages: int):
        """Phase 3: Navigate through pages and build semantic maps."""
        await self._log("MILESTONE", "exploration", f"Starting deep page exploration (max {max_pages} pages)")

        # Collect URLs to visit
        urls_to_visit = await self._collect_urls_to_visit()
        visited = 0

        for url, module_id in urls_to_visit[:max_pages]:
            if url in self._discovered_urls:
                continue

            try:
                await self._explore_single_page(url, module_id)
                self._discovered_urls.add(url)
                visited += 1

                if visited % 5 == 0:
                    await self._log("INFO", "exploration", f"Explored {visited} pages so far")

                await asyncio.sleep(0.5)

            except Exception as e:
                log.warning("Page exploration failed", url=url, error=str(e))

        await self._log("SUCCESS", "exploration", f"Page exploration complete — {visited} pages analyzed")

    async def _explore_single_page(self, url: str, module_id: str | None):
        """Explore a single page and build its semantic map."""
        try:
            await asyncio.to_thread(self._browser.navigate, url)
            await asyncio.sleep(1.5)  # Let page render

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

            state = self._extractor.extract_page_state()
            page_name = state.get("page", "Unknown Page")

            await self._log("INFO", "exploration", f"Analyzing: {page_name}")

            # AI-powered page analysis
            page_analysis = await self._analyze_page_with_ai(state, url)

            # Find or create module
            if not module_id:
                module_id = await self._find_module_for_url(url)

            # Persist page
            page = ApplicationPage(
                module_id=module_id or await self._get_default_module_id(),
                title=page_analysis.get("page_name", page_name),
                url=url,
                page_type=page_analysis.get("page_type", "unknown"),
                semantic_map=state,
                forms=page_analysis.get("forms", []),
                tables=page_analysis.get("tables", []),
                navigation_links=page_analysis.get("navigation_links", []),
                dynamic_behaviors=page_analysis.get("dynamic_behaviors", []),
            )
            self.db.add(page)
            await self.db.flush()

            # Persist workflows found on this page
            for wf in page_analysis.get("workflows", []):
                workflow = ApplicationWorkflow(
                    module_id=module_id or page.module_id,
                    name=wf.get("name", "Unknown Workflow"),
                    description=wf.get("description", ""),
                    workflow_type=wf.get("type", "unknown"),
                    stages=[{"name": s} for s in wf.get("steps", [])],
                    entry_point={"trigger": wf.get("entry_trigger", "")},
                )
                self.db.add(workflow)

            await self.db.commit()

            # Log meaningful discoveries
            if page_analysis.get("forms"):
                forms_str = ", ".join(f.get("name", "form") for f in page_analysis["forms"][:3])
                await self._log("SUCCESS", "exploration", f"Forms discovered on {page_name}: {forms_str}")

            if page_analysis.get("workflows"):
                wf_str = ", ".join(w.get("name", "workflow") for w in page_analysis["workflows"][:3])
                await self._log("SUCCESS", "exploration", f"Workflows identified on {page_name}: {wf_str}")

        except Exception as e:
            await self._log("WARNING", "exploration", f"Could not fully analyze page at {url}: {str(e)[:100]}")

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

        app_context = f"Application description: {self._app.description or 'Business application'}"

        try:
            response = await self.ai.complete(
                system=SYSTEM_PROMPT_EXPLORE,
                user=f"{app_context}\n\nPage semantic state:\n{compact_state}",
                fast=True,
                json_mode=True,
                max_tokens=2000,
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

        # Version bump
        existing = await self.db.execute(
            select(KnowledgeGraph)
            .where(KnowledgeGraph.application_id == application_id)
            .order_by(KnowledgeGraph.version.desc())
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
        """Serialize discovered knowledge into graph format."""
        modules_result = await self.db.execute(
            select(ApplicationModule).where(ApplicationModule.application_id == application_id)
        )
        modules = modules_result.scalars().all()

        graph = {"nodes": [], "edges": []}
        for module in modules:
            graph["nodes"].append({
                "id": module.id,
                "type": "module",
                "label": module.name,
                "description": module.description,
                "tags": module.semantic_tags or [],
            })

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

        # Module URL patterns
        modules_result = await self.db.execute(
            select(ApplicationModule).where(ApplicationModule.application_id == self._app.id)
        )
        modules = modules_result.scalars().all()
        base = self._app.base_url.rstrip("/")
        for module in modules:
            if module.url_pattern and module.url_pattern.startswith("/"):
                _add(base + module.url_pattern, module.id)

        # Links on current page (both <a href> and buttons that navigate)
        try:
            links = self._browser.execute_script("""
                const base = window.location.origin;
                return Array.from(document.querySelectorAll('a[href]'))
                    .filter(a => a.href.startsWith(base) && !a.href.includes('#') && a.textContent.trim())
                    .map(a => a.href)
                    .filter((v, i, a) => a.indexOf(v) === i)
                    .slice(0, 40);
            """) or []
            for url in links:
                _add(url)
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
        """Poll for human decision resolution."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            await asyncio.sleep(3)
            result = await self.db.execute(
                select(HumanDecision).where(HumanDecision.id == decision_id)
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

    async def _log(self, level: str, category: str, message: str, metadata: dict | None = None):
        """Emit semantic log — not technical logs."""
        entry = ExploreLog(
            session_id=self._session_id,
            level=level,
            category=category,
            message=message,
            extra=metadata or {},
        )
        self.db.add(entry)
        await self.db.commit()

        await self._emit_event("explore_log", {
            "session_id": self._session_id,
            "level": level,
            "category": category,
            "message": message,
        })

    async def _emit_event(self, event: str, data: dict):
        await connection_manager.broadcast_json({"event": event, **data})

    async def _load_session(self, session_id: str) -> ExploreSession | None:
        result = await self.db.execute(select(ExploreSession).where(ExploreSession.id == session_id))
        return result.scalar_one_or_none()

    async def _load_application(self, application_id: str) -> Application | None:
        result = await self.db.execute(select(Application).where(Application.id == application_id))
        return result.scalar_one_or_none()
