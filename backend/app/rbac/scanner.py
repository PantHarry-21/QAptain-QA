"""
RBAC Permission Scanner — Intelligent multi-role permission testing.

Strategy per role:
  1. Launch headless browser
  2. Login using the EXACT same flow as ExecutionOrchestrator._execute_login
     (90-second Angular SPA wait, JS native setter fill, two-step login, post-login
      portal/location selector auto-handled via FieldInspector + WorkspacePreference)
  3. Wait 3s for navigation to render fully
  4. Snapshot visible nav items (broad Angular-Material-aware JS query)
  5. Probe every discovered module URL: navigate → check if accessible or blocked
  6. Quit browser
Results stored incrementally so frontend progress bar updates in real time.
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select

from app.db.models import (
    Application, Credential,
    ApplicationModule, ApplicationPage,
    RBACScan, WorkspacePreference,
)
from app.db.session import AsyncSessionFactory
from app.execution.browser_manager import BrowserManager
from app.core.security import decrypt_credential

log = structlog.get_logger()


# ─── Entry point (background task) ────────────────────────────────────────────

async def run_rbac_scan(scan_id: str, application_id: str) -> None:
    """Background task: scan every role credential and persist results."""
    async with AsyncSessionFactory() as db:
        scan_res = await db.execute(select(RBACScan).where(RBACScan.id == scan_id))
        scan = scan_res.scalar_one_or_none()
        if not scan:
            return

        scan.status = "running"
        scan.started_at = datetime.utcnow()
        await db.commit()

        try:
            app_res = await db.execute(
                select(Application).where(Application.id == application_id)
            )
            app = app_res.scalar_one_or_none()
            if not app:
                raise ValueError("Application not found")

            # ── Role credentials ──────────────────────────────────────────────
            cred_res = await db.execute(
                select(Credential)
                .where(Credential.application_id == application_id)
                .where(Credential.label.isnot(None))
                .where(Credential.label != "")
                .order_by(Credential.label)
            )
            role_creds = cred_res.scalars().all()

            # ── ALL modules (parent + children) ───────────────────────────────
            mod_res = await db.execute(
                select(ApplicationModule)
                .where(ApplicationModule.application_id == application_id)
                .order_by(ApplicationModule.order_index)
            )
            all_modules = mod_res.scalars().all()

            # ── Best URL per module: ApplicationPage > url_pattern ────────────
            page_res = await db.execute(
                select(ApplicationPage)
                .where(ApplicationPage.module_id.in_([m.id for m in all_modules]))
                .order_by(ApplicationPage.discovered_at)
            )
            pages_by_module: dict[str, str] = {}
            for pg in page_res.scalars().all():
                if pg.module_id not in pages_by_module:
                    pages_by_module[pg.module_id] = pg.url

            base_url = app.base_url.rstrip("/")
            module_info: list[dict] = []
            for m in all_modules:
                best_url = (
                    pages_by_module.get(m.id)
                    or _resolve_url(base_url, m.url_pattern or "")
                    or ""
                )
                module_info.append({
                    "id": m.id,
                    "name": m.name,
                    "url": best_url,
                    "parent_id": m.parent_id,
                })

            # ── Load login preference once (shared by all roles) ──────────────
            pref_res = await db.execute(
                select(WorkspacePreference).where(
                    WorkspacePreference.application_id == application_id,
                    WorkspacePreference.preference_key == "login.location",
                )
            )
            pref = pref_res.scalar_one_or_none()
            preferred_location = (
                pref.preference_value.get("value") if pref else None
            )

            # ── Initial results skeleton ──────────────────────────────────────
            results: dict[str, Any] = {
                "modules": [m["name"] for m in module_info],
                "roles": [],
                "scanned_at": datetime.utcnow().isoformat(),
                "progress": {"completed": 0, "total": len(role_creds)},
            }
            scan.results = dict(results)
            await db.commit()

            # ── Scan each role ─────────────────────────────────────────────────
            for idx, cred in enumerate(role_creds):
                results["progress"]["current_role"] = cred.label
                scan.results = dict(results)
                await db.commit()

                log.info("RBAC scan: role", role=cred.label, idx=idx + 1,
                         total=len(role_creds))

                role_result = await _scan_role(
                    cred, app, module_info, preferred_location
                )
                results["roles"].append(role_result)
                results["progress"]["completed"] = idx + 1
                scan.results = dict(results)
                await db.commit()

            results.pop("progress", None)
            scan.status = "completed"
            scan.completed_at = datetime.utcnow()
            scan.results = results
            await db.commit()
            log.info("RBAC scan complete", scan_id=scan_id, roles=len(results["roles"]))

        except Exception as exc:
            log.exception("RBAC scan failed", scan_id=scan_id, error=str(exc))
            scan.status = "failed"
            scan.error_message = str(exc)[:500]
            scan.completed_at = datetime.utcnow()
            await db.commit()


# ─── Per-role scan ─────────────────────────────────────────────────────────────

async def _scan_role(
    cred: Credential,
    app: Application,
    modules: list[dict],
    preferred_location: str | None,
) -> dict:
    role_name = cred.label
    username = cred.username

    try:
        password = decrypt_credential(cred.password_encrypted)
    except Exception as exc:
        return _err(role_name, username, f"Credential decryption failed: {exc}")

    browser: BrowserManager | None = None
    try:
        browser = await asyncio.to_thread(BrowserManager.create, True, (1920, 1080))

        # Login — full executor-style flow in a single thread
        login_ok = await asyncio.to_thread(
            _login_sync, browser, app.base_url, username, password, preferred_location
        )

        if not login_ok:
            return _err(role_name, username, "Login failed — invalid credentials or unsupported login flow")

        # Wait for Angular SPA nav to fully render (poll up to 20s)
        nav_items = await asyncio.to_thread(_wait_for_nav, browser, 20)
        log.info("RBAC nav snapshot", role=role_name, nav_count=len(nav_items))

        # Probe each module URL
        module_access: dict[str, str] = {}
        for mod in modules:
            if not mod["url"]:
                module_access[mod["name"]] = "no_url"
                continue
            accessible = await asyncio.to_thread(
                _probe_accessible, browser, mod["url"], app.base_url
            )
            module_access[mod["name"]] = "accessible" if accessible else "blocked"

        return {
            "role_name": role_name,
            "username": username,
            "login_success": True,
            "nav_items": nav_items,
            "module_access": module_access,
        }

    except Exception as exc:
        log.error("Role scan error", role=role_name, error=str(exc))
        return _err(role_name, username, str(exc)[:200])
    finally:
        if browser:
            try:
                await asyncio.to_thread(browser.quit)
            except Exception:
                pass


def _err(role_name: str, username: str, error: str) -> dict:
    return {
        "role_name": role_name,
        "username": username,
        "login_success": False,
        "error": error,
        "nav_items": [],
        "module_access": {},
    }


# ─── Login (sync — runs in asyncio.to_thread) ─────────────────────────────────

def _login_sync(
    browser: BrowserManager,
    base_url: str,
    username: str,
    password: str,
    preferred_location: str | None,
) -> bool:
    """
    Complete login flow using ExecutionOrchestrator's tested static helpers.
    All Selenium work runs synchronously in a thread pool (called via asyncio.to_thread).

    Steps:
      1. Navigate to base_url
      2. Wait up to 90s for login form (Angular SPA bootstrap)
      3. Find username + password fields
      4. Fill username (JS native setter for Angular Material)
      5. If two-step: click Next → wait for password field
      6. Fill password and submit
      7. Handle post-login portal/location selector (FieldInspector)
      8. Verify we left the login page
    """
    from selenium.webdriver.common.keys import Keys
    from app.intelligence.field_inspector import FieldInspector
    from app.execution.executor import ExecutionOrchestrator
    from app.execution.self_healing import SelfHealingEngine

    # ── 1. Navigate ────────────────────────────────────────────────────────────
    try:
        browser.navigate(base_url)
    except Exception:
        pass

    # ── 2. Wait for login form (90s — Angular SPAs can take this long) ─────────
    page_ready = ExecutionOrchestrator._wait_for_any_input(browser, timeout=90)
    if not page_ready:
        log.warning("Login: no input within 90s", url=base_url)
        return False

    # ── 3. Find fields ─────────────────────────────────────────────────────────
    username_el, password_el = ExecutionOrchestrator._find_login_fields_fast(browser)
    if username_el is None:
        return False

    # ── 4. Fill username ───────────────────────────────────────────────────────
    ExecutionOrchestrator._fill_field(browser, username_el, username)

    # ── 5. Two-step login (username → Next → password) ─────────────────────────
    if password_el is None:
        two_step_result = _do_two_step(browser, username_el, username, password)
        if two_step_result is not None:
            # two_step_result: True = submitted, False = failed, None = fall through
            if two_step_result:
                time.sleep(2.5)
                _handle_context_sync(browser, preferred_location)
                return not ExecutionOrchestrator._is_on_login_page(browser, base_url)
            return False

        # Re-check after two-step attempt in case password now appeared
        _, password_el = ExecutionOrchestrator._find_login_fields_fast(browser)

    if password_el is None:
        return False

    # ── 6. Fill password and submit ────────────────────────────────────────────
    ExecutionOrchestrator._fill_field(browser, password_el, password)
    time.sleep(0.3)

    healer = SelfHealingEngine(browser.driver)
    submitted = False
    for btn_label in ("Sign In", "Login", "Log In", "Submit", "SIGN IN"):
        result = healer.find_element(btn_label)
        if result[0]:
            healer.click_with_healing(result[0])
            submitted = True
            break
    if not submitted:
        try:
            password_el.send_keys(Keys.RETURN)
        except Exception:
            pass

    time.sleep(2.5)

    # ── 7. Post-login portal / location selector ────────────────────────────────
    _handle_context_sync(browser, preferred_location)

    # ── 8. Verify login ────────────────────────────────────────────────────────
    return not ExecutionOrchestrator._is_on_login_page(browser, base_url)


def _do_two_step(
    browser: BrowserManager,
    username_el,
    username: str,
    password: str,
) -> bool | None:
    """
    Two-step login: fill username → click Next → wait for password → fill + submit.
    Returns True (login submitted), False (explicit fail), None (not two-step, fall through).
    """
    from selenium.webdriver.common.keys import Keys
    from app.execution.executor import ExecutionOrchestrator
    from app.execution.self_healing import SelfHealingEngine

    healer = SelfHealingEngine(browser.driver)

    # Click Next / Continue
    clicked = False
    for btn_label in ("Next", "Continue", "Proceed", "Sign In", "Login"):
        result = healer.find_element(btn_label)
        if result[0]:
            healer.click_with_healing(result[0])
            clicked = True
            break
    if not clicked:
        try:
            username_el.send_keys(Keys.RETURN)
        except Exception:
            pass

    # Wait up to 8s for password field
    deadline = time.time() + 8
    password_el = None
    while time.time() < deadline:
        _, pw = ExecutionOrchestrator._find_login_fields_fast(browser)
        if pw is not None:
            password_el = pw
            break
        time.sleep(0.5)

    if password_el is None:
        return None  # Not two-step — caller should fall through

    ExecutionOrchestrator._fill_field(browser, password_el, password)
    time.sleep(0.3)

    for btn_label in ("Sign In", "Login", "Log In", "Submit", "SIGN IN"):
        result = healer.find_element(btn_label)
        if result[0]:
            healer.click_with_healing(result[0])
            return True

    try:
        password_el.send_keys(Keys.RETURN)
        return True
    except Exception:
        return False


def _handle_context_sync(
    browser: BrowserManager,
    preferred_location: str | None,
) -> None:
    """
    Handle post-login portal/location selectors synchronously.
    Mirrors ExecutionOrchestrator._handle_post_login_context exactly:
      - Detect selector type via _inspect_dom_for_selectors
      - trigger_button: open it and pick first option (or preferred)
      - select/list/radio: pick preferred or first option
      - Click Sign In after selection, loop up to 3 times
    """
    from app.intelligence.field_inspector import FieldInspector
    from app.execution.executor import ExecutionOrchestrator
    from app.execution.self_healing import SelfHealingEngine

    for step in range(3):
        # Retry detection (overlay loads asynchronously after login submit)
        selector_info: dict = {"type": "unknown"}
        for attempt in range(4):
            selector_info = ExecutionOrchestrator._inspect_dom_for_selectors(browser)
            if selector_info.get("type") not in ("unknown", None):
                break
            if attempt < 3:
                time.sleep(2)

        sel_type = selector_info.get("type", "unknown")
        if sel_type == "unknown":
            break

        label = selector_info.get("label", "")
        options = selector_info.get("options", [])
        inspector = FieldInspector(browser.driver)
        healer = SelfHealingEngine(browser.driver)
        selected = False

        if sel_type == "trigger_button":
            # Try with saved preference first
            if preferred_location:
                ok = inspector.select_by_label_text(label, preferred_location)
                if ok:
                    selected = True

            # Fall back: click the trigger, discover options, pick first
            if not selected:
                result = healer.find_element(label)
                if result[0]:
                    discovered = inspector.get_options(result[0])
                    if discovered:
                        first_label = discovered[0].label
                        ok = inspector.select_option(result[0], first_label)
                        if ok:
                            selected = True

        elif sel_type in ("select", "list", "radio", "button_group"):
            target = preferred_location
            if not target and options:
                first = options[0]
                target = first.get("label") if isinstance(first, dict) else str(first)
            if target and label:
                ok = inspector.select_by_label_text(label, target)
                if ok:
                    selected = True

        if not selected:
            break

        # Click submit after selection
        time.sleep(0.8)
        for btn_label in ("Sign In", "Login", "Continue", "Submit", "Proceed", "OK", "Next"):
            result = healer.find_element(btn_label)
            if result[0]:
                try:
                    result[0].click()
                    break
                except Exception:
                    pass

        time.sleep(2)

        # Exit if we've navigated away from login
        if not ExecutionOrchestrator._is_on_login_page(browser, ""):
            break


# ─── Nav polling helper ────────────────────────────────────────────────────────

def _wait_for_nav(browser: BrowserManager, timeout: int = 20) -> list[str]:
    """Poll until Angular SPA nav elements appear or timeout expires."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        items = _snapshot_nav(browser)
        if items:
            log.info("RBAC nav appeared", nav_count=len(items),
                     elapsed=round(timeout - (deadline - time.time()), 1))
            return items
        time.sleep(1.5)
    log.warning("RBAC nav never appeared within timeout", timeout=timeout)
    return []


# ─── Nav snapshot ─────────────────────────────────────────────────────────────

def _snapshot_nav(browser: BrowserManager) -> list[str]:
    """
    Capture all visible navigation labels.
    Uses a comprehensive Angular-Material-aware JS query that covers:
      - Standard nav/aside elements
      - mat-nav-list, mat-list-item, mdc-list-item (Angular Material v15+)
      - ARIA role="navigation" and role="menuitem"
      - Common sidebar class patterns
    """
    try:
        items = browser.execute_script(r"""
            (function() {
                var NOISE = new Set([
                    'logout','log out','sign out','profile','account',
                    'notifications','help','about','settings','home',
                    'search','menu','more','expand','collapse',
                    'notification','dashboard'
                ]);

                function isVisible(el) {
                    var r = el.getBoundingClientRect();
                    var s = window.getComputedStyle(el);
                    return r.width > 0 && r.height > 0 &&
                           s.display !== 'none' &&
                           s.visibility !== 'hidden' &&
                           parseFloat(s.opacity) > 0;
                }

                function directText(el) {
                    var t = '';
                    for (var i = 0; i < el.childNodes.length; i++) {
                        if (el.childNodes[i].nodeType === 3)
                            t += el.childNodes[i].textContent;
                    }
                    return t.trim().replace(/\s+/g, ' ');
                }

                function getText(el) {
                    var t = directText(el);
                    if (!t) t = (el.textContent || el.innerText || '').trim().replace(/\s+/g, ' ');
                    return t.slice(0, 100);
                }

                var CSS = [
                    'nav a', 'nav li', 'nav button',
                    'nav [role="menuitem"]', 'nav [role="treeitem"]',
                    'aside a', 'aside li', 'aside button',
                    'aside [role="menuitem"]', 'aside [role="treeitem"]',
                    '[role="navigation"] a', '[role="navigation"] li',
                    '[role="navigation"] [role="menuitem"]',
                    '[role="navigation"] [role="treeitem"]',
                    'mat-nav-list a', 'mat-nav-list mat-list-item',
                    'mat-nav-list [mat-list-item]',
                    'mat-list-item[routerlink]', 'mat-list-item[ng-reflect-router-link]',
                    '.mat-mdc-nav-list a', '.mat-mdc-nav-list .mdc-list-item',
                    '.mdc-list-item[href]', '.mdc-list-item[routerlink]',
                    '.sidebar a', '.sidebar li',
                    '.side-nav a', '.side-menu a',
                    '.menu-item a', '.nav-item a',
                    '[class*="sidebar"] a', '[class*="side-nav"] a',
                    '[class*="nav-menu"] a', '[class*="menu-item"]'
                ].join(',');

                var seen = new Set(), out = [];
                try {
                    var els = document.querySelectorAll(CSS);
                    for (var i = 0; i < els.length; i++) {
                        var el = els[i];
                        if (!isVisible(el)) continue;
                        var t = getText(el);
                        if (!t || t.length < 2 || t.length > 80) continue;
                        var tl = t.toLowerCase();
                        if (NOISE.has(tl)) continue;
                        if (seen.has(tl)) continue;
                        seen.add(tl);
                        out.push(t);
                    }
                } catch(e) {}
                return out;
            })()
        """) or []
        return list(items)
    except Exception:
        return []


# ─── URL access probe ──────────────────────────────────────────────────────────

def _probe_accessible(browser: BrowserManager, url: str, base_url: str) -> bool:
    """
    Navigate to url; return True if the role can access it.
    Detection:
      - Is login page showing after navigation? → blocked
      - URL redirected to root / dashboard? → blocked (if target was specific)
      - Page body contains access-denied text? → blocked
    """
    from app.execution.executor import ExecutionOrchestrator
    try:
        browser.navigate(url)
        time.sleep(2)

        # DOM-based login check (password field present or few nav links)
        if ExecutionOrchestrator._is_on_login_page(browser, base_url):
            return False

        # URL-based: redirected to root or login path
        try:
            from urllib.parse import urlparse
            expected = urlparse(url).path.rstrip("/") or "/"
            actual   = urlparse(browser.driver.current_url).path.rstrip("/") or "/"
            # Only flag as blocked if we navigated somewhere specific but ended at root/home
            if expected not in ("/", "") and actual in ("/", "/home", "/dashboard", "/index"):
                return False
        except Exception:
            pass

        # Body text check for permission errors
        try:
            body = browser.execute_script(
                "return (document.body && document.body.innerText) || '';"
            ) or ""
            bl = body.lower()
            if any(k in bl for k in (
                "403 forbidden", "401 unauthorized",
                "access denied", "not authorized",
                "permission denied", "you do not have access",
                "you don't have permission",
            )):
                return False
        except Exception:
            pass

        return True
    except Exception:
        return False


# ─── URL resolver ──────────────────────────────────────────────────────────────

def _resolve_url(base_url: str, pattern: str) -> str | None:
    """Convert a module url_pattern (possibly regex) to a navigable absolute URL."""
    if not pattern:
        return None
    if pattern.startswith("http"):
        return pattern
    cleaned = (
        pattern
        .replace("^", "")
        .replace("$", "")
        .split("(")[0]
        .replace(".*", "")
        .replace(".+", "")
        .rstrip("/")
    )
    if not cleaned or cleaned == "/":
        return None
    sep = "" if cleaned.startswith("/") else "/"
    return base_url.rstrip("/") + sep + cleaned
