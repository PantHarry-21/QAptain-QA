"""
Browser Manager — Selenium + Chrome DevTools Protocol
Selenium = hands (actions)
CDP = intelligence (DOM snapshots, network, mutations, accessibility)
"""
from __future__ import annotations
import time
from typing import Any

import structlog
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait

from config import settings

log = structlog.get_logger()


class BrowserManager:
    """
    Lifecycle-managed browser instance with integrated CDP.
    Create via BrowserManager.create() for async usage.
    """

    def __init__(self, driver: webdriver.Chrome):
        self.driver = driver
        self._cdp_enabled = False
        self._network_events: list[dict[str, Any]] = []
        self._console_events: list[dict[str, Any]] = []
        self._mutation_observers: list[dict[str, Any]] = []

    @classmethod
    def create(
        cls,
        headless: bool | None = None,
        window_size: tuple[int, int] | None = None,
    ) -> "BrowserManager":
        opts = Options()

        is_headless = headless if headless is not None else settings.SELENIUM_HEADLESS
        w, h = window_size or (settings.SELENIUM_WINDOW_WIDTH, settings.SELENIUM_WINDOW_HEIGHT)

        if is_headless:
            opts.add_argument("--headless=new")

        opts.add_argument(f"--window-size={w},{h}")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        opts.add_argument("--disable-extensions")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--disable-software-rasterizer")
        opts.add_argument("--disable-setuid-sandbox")
        # UAT environments often use self-signed or corporate CA certs
        opts.add_argument("--ignore-certificate-errors")
        opts.add_argument("--allow-insecure-localhost")
        # Realistic user-agent prevents bot-detection blocks in headless mode
        opts.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        # Enable performance logging for CDP
        opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

        # none: driver.get() returns immediately after Chrome starts navigation.
        # This prevents blocking for 60s on heavy SPAs (YLIMS, Angular). Callers are
        # responsible for waiting (explore uses _wait_for_any_input, executor uses
        # implicit waits via _wait_for_stability + explicit element waits).
        opts.page_load_strategy = "none"

        # Selenium Manager (built into Selenium 4.6+) auto-downloads the matching ChromeDriver
        driver = webdriver.Chrome(options=opts)
        driver.set_page_load_timeout(settings.SELENIUM_PAGE_LOAD_TIMEOUT)
        driver.implicitly_wait(0)  # We do explicit waits

        # Remove automation indicator
        driver.execute_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )

        mgr = cls(driver)
        mgr._setup_cdp()
        mgr.inject_network_monitor()
        return mgr

    def _setup_cdp(self):
        """Enable CDP domains for intelligence gathering."""
        try:
            # Enable network monitoring
            self.driver.execute_cdp_cmd("Network.enable", {})
            # Enable DOM monitoring
            self.driver.execute_cdp_cmd("DOM.enable", {})
            # Enable performance monitoring
            self.driver.execute_cdp_cmd("Performance.enable", {})
            self._cdp_enabled = True
            log.debug("CDP enabled")
        except Exception as e:
            log.warning("CDP setup failed — running without CDP intelligence", error=str(e))

    def navigate(self, url: str):
        """
        Navigate and wait for DOM stability.
        Uses page_load_strategy='none' so driver.get() returns immediately.
        _wait_for_stability() then polls until DOM mutations settle (≤5s), which
        is sufficient for fast pages. For slow SPAs, the caller waits explicitly.
        """
        from selenium.common.exceptions import TimeoutException, WebDriverException
        try:
            self.driver.get(url)
        except TimeoutException:
            log.warning("Page load timed out — continuing with partial load", url=url)
        except WebDriverException as e:
            msg = str(e).lower()
            if "timeout" in msg or "renderer" in msg:
                log.warning("Renderer timeout — continuing with partial load", url=url)
            else:
                raise
        try:
            self._wait_for_stability()
        except Exception:
            # Stability check can fail mid-navigation (execute_script on an unloaded
            # frame). Safe to ignore — caller has its own explicit waits.
            pass

    def get_dom_snapshot(self) -> dict[str, Any]:
        """Get lightweight DOM snapshot via CDP."""
        if not self._cdp_enabled:
            return {"html_length": len(self.driver.page_source)}
        try:
            snapshot = self.driver.execute_cdp_cmd(
                "DOMSnapshot.captureSnapshot",
                {"computedStyles": [], "includeDOMRects": False, "includePaintOrder": False},
            )
            return {
                "documents_count": len(snapshot.get("documents", [])),
                "strings_count": len(snapshot.get("strings", [])),
            }
        except Exception:
            return {}

    def get_accessibility_tree(self) -> list[dict[str, Any]]:
        """Get simplified accessibility tree for semantic understanding."""
        try:
            tree = self.driver.execute_cdp_cmd(
                "Accessibility.getFullAXTree",
                {"fetchRelatives": False},
            )
            nodes = tree.get("nodes", [])
            # Filter to meaningful nodes
            meaningful = [
                {
                    "role": n.get("role", {}).get("value"),
                    "name": n.get("name", {}).get("value"),
                    "description": n.get("description", {}).get("value"),
                }
                for n in nodes
                if n.get("role", {}).get("value") not in ("none", "generic", "group", "presentation", "ignored")
                and n.get("name", {}).get("value")
            ]
            return meaningful[:100]
        except Exception:
            return []

    def get_network_events(self) -> list[dict[str, Any]]:
        """Get recent network activity from performance logs."""
        events = []
        try:
            logs = self.driver.get_log("performance")
            for entry in logs:
                import json
                msg = json.loads(entry.get("message", "{}"))
                method = msg.get("message", {}).get("method", "")
                if method in ("Network.responseReceived", "Network.requestWillBeSent"):
                    params = msg.get("message", {}).get("params", {})
                    req = params.get("request") or params.get("response", {})
                    url = req.get("url", "")
                    if url and not any(x in url for x in ["chrome-extension://", "data:", "blob:"]):
                        events.append({
                            "method": method,
                            "url": url,
                            "status": params.get("response", {}).get("status"),
                        })
        except Exception:
            pass
        return events[-50:]

    def execute_script(self, script: str, *args) -> Any:
        return self.driver.execute_script(script, *args)

    def take_screenshot(self, path: str) -> bool:
        """Save screenshot to path."""
        try:
            self.driver.save_screenshot(path)
            return True
        except Exception as e:
            log.warning("Screenshot failed", error=str(e))
            return False

    def get_current_url(self) -> str:
        return self.driver.current_url

    def get_page_title(self) -> str:
        return self.driver.title

    def wait_for_element_visible(self, css_selector: str, timeout: float = 10) -> bool:
        """Wait until element is visible on page."""
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.common.by import By
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.visibility_of_element_located((By.CSS_SELECTOR, css_selector))
            )
            return True
        except Exception:
            return False

    def wait_for_url_change(self, current_url: str, timeout: float = 10) -> bool:
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.current_url != current_url
            )
            return True
        except Exception:
            return False

    def _wait_for_stability(self, timeout: float = 5.0, poll: float = 0.3):
        """Wait for DOM to settle — no rapid mutations for 300ms."""
        self.execute_script("""
            window.__qaptain_mutations = 0;
            if (!window.__qaptain_observer) {
                window.__qaptain_observer = new MutationObserver(() => {
                    window.__qaptain_mutations++;
                });
                window.__qaptain_observer.observe(document.body || document.documentElement, {
                    childList: true, subtree: true, attributes: true
                });
            }
        """)
        last_count = -1
        stable_since = None
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            count = self.execute_script("return window.__qaptain_mutations || 0;") or 0
            if count == last_count:
                if stable_since is None:
                    stable_since = time.monotonic()
                elif time.monotonic() - stable_since >= poll:
                    break
            else:
                stable_since = None
            last_count = count
            time.sleep(0.1)

    def inject_mutation_observer(self) -> None:
        """Inject a persistent mutation observer for dynamic UI tracking."""
        self.execute_script("""
            window.__qaptain_changes = [];
            if (window.__qaptain_dom_observer) window.__qaptain_dom_observer.disconnect();
            window.__qaptain_dom_observer = new MutationObserver((mutations) => {
                for (const m of mutations) {
                    if (m.addedNodes.length > 0 || m.removedNodes.length > 0) {
                        window.__qaptain_changes.push({
                            type: 'dom',
                            added: m.addedNodes.length,
                            removed: m.removedNodes.length,
                            target: m.target.tagName || 'unknown',
                            timestamp: Date.now()
                        });
                        if (window.__qaptain_changes.length > 50) {
                            window.__qaptain_changes.shift();
                        }
                    }
                }
            });
            window.__qaptain_dom_observer.observe(document.body || document.documentElement, {
                childList: true, subtree: true
            });
        """)

    def get_dom_changes(self) -> list[dict[str, Any]]:
        """Collect accumulated DOM changes since last check."""
        try:
            changes = self.execute_script("""
                const changes = window.__qaptain_changes || [];
                window.__qaptain_changes = [];
                return changes;
            """)
            return changes or []
        except Exception:
            return []

    def inject_network_monitor(self) -> None:
        """
        Inject a lightweight JS shim that counts in-flight XHR + fetch requests.
        After injection, window.__qa_pending_requests holds the live count.
        Safe to call multiple times (idempotent guard via __qa_nm_injected).
        """
        try:
            self.execute_script("""
                if (window.__qa_nm_injected) return;
                window.__qa_nm_injected = true;
                window.__qa_pending_requests = 0;

                // Intercept fetch
                const _origFetch = window.fetch;
                window.fetch = function(...args) {
                    window.__qa_pending_requests++;
                    return _origFetch.apply(this, args).finally(function() {
                        window.__qa_pending_requests = Math.max(0, window.__qa_pending_requests - 1);
                    });
                };

                // Intercept XHR
                const _origOpen = XMLHttpRequest.prototype.open;
                const _origSend = XMLHttpRequest.prototype.send;
                XMLHttpRequest.prototype.send = function(...args) {
                    window.__qa_pending_requests++;
                    const dec = () => {
                        window.__qa_pending_requests = Math.max(0, window.__qa_pending_requests - 1);
                    };
                    this.addEventListener('load', dec);
                    this.addEventListener('error', dec);
                    this.addEventListener('abort', dec);
                    this.addEventListener('timeout', dec);
                    return _origSend.apply(this, args);
                };
            """)
        except Exception:
            pass

    def wait_network_idle(self, timeout: float = 6.0, max_pending: int = 0) -> bool:
        """
        Block until in-flight XHR/fetch requests reach <= max_pending or timeout.
        Returns True if idle was reached, False on timeout.
        Gracefully degrades if the network monitor was not injected (returns True).
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                pending = self.execute_script("return window.__qa_pending_requests || 0;") or 0
                if pending <= max_pending:
                    return True
            except Exception:
                return True  # driver may have navigated — treat as idle
            time.sleep(0.25)
        return False

    def get_console_errors(self) -> list[dict]:
        """Collect browser console errors from the current page session."""
        errors = []
        try:
            logs = self.driver.get_log("browser")
            for entry in logs:
                level = entry.get("level", "")
                if level in ("SEVERE", "ERROR"):
                    errors.append({
                        "level": level,
                        "message": entry.get("message", "")[:300],
                        "timestamp": entry.get("timestamp"),
                    })
        except Exception:
            pass
        return errors[-20:]

    def capture_failure_context(self) -> dict:
        """
        Capture a rich snapshot of the current browser state for failure diagnosis.
        Returns: url, title, dom_summary, console_errors, pending_requests, dialog_open.
        """
        ctx: dict = {}
        try:
            ctx["url"] = self.driver.current_url
        except Exception:
            ctx["url"] = "unknown"
        try:
            ctx["title"] = self.driver.title
        except Exception:
            ctx["title"] = ""
        try:
            ctx["dom_summary"] = self.execute_script("""
                return {
                    input_count: document.querySelectorAll('input,textarea,select').length,
                    button_count: document.querySelectorAll('button,[role="button"]').length,
                    dialog_open: !!document.querySelector('[role="dialog"],[aria-modal="true"]'),
                    visible_errors: Array.from(document.querySelectorAll(
                        '[class*="error"],[role="alert"],[class*="alert-danger"]'
                    )).filter(e => {
                        const r = e.getBoundingClientRect();
                        return r.width > 0 && r.height > 0;
                    }).map(e => e.textContent.trim().slice(0,150)).filter(Boolean).slice(0,5),
                    page_text_preview: (document.body && document.body.innerText || '').slice(0,300),
                };
            """) or {}
        except Exception:
            ctx["dom_summary"] = {}
        ctx["console_errors"] = self.get_console_errors()
        try:
            ctx["pending_requests"] = self.execute_script(
                "return window.__qa_pending_requests || 0;"
            ) or 0
        except Exception:
            ctx["pending_requests"] = -1
        return ctx

    def quit(self):
        """Clean up browser resources."""
        try:
            self.driver.quit()
        except Exception:
            pass
