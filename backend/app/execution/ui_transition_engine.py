"""
UI transition detector — lightweight JS fingerprinting, no AI calls.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from app.execution.browser_manager import BrowserManager

log = structlog.get_logger()

_FINGERPRINT_JS = """
(function() {
  var _t = function(s) { try { return document.querySelector(s); } catch(e) { return null; } };
  var _ta = function(s) { try { return document.querySelectorAll(s); } catch(e) { return []; } };
  var _txt = function(el) { return el ? (el.textContent || '').trim().substring(0, 200) : ''; };

  var h1El = _t('h1') || _t('h2');
  var toastEl = _t('[class*="toast"],[class*="alert"],[class*="snack"],[role="alert"]');
  var errorEls = _ta('[class*="error"],[class*="invalid"],[aria-invalid="true"]');
  var successEls = _ta('[class*="success"],[class*="complete"]');
  var loaderEls = _ta('[class*="spinner"],[class*="loading"],[class*="skeleton"],[aria-busy="true"]');
  var overlayEl = _t('[class*="overlay"],[class*="backdrop"],[class*="mask"]');
  var modalEls = _ta('[role="dialog"],[class*="modal"],[class*="dialog"]');
  var visibleModal = false;
  for (var i = 0; i < modalEls.length; i++) {
    var s = window.getComputedStyle(modalEls[i]);
    if (s.display !== 'none' && s.visibility !== 'hidden' && s.opacity !== '0') {
      visibleModal = true; break;
    }
  }
  var rows = _ta('tr,tbody tr,[class*="ag-row"],[class*="mat-row"]').length;
  var buttons = 0;
  var btnEls = _ta('button:not([disabled]),[type="button"]:not([disabled]),[type="submit"]:not([disabled])');
  buttons = btnEls.length;
  var errorTexts = []; for (var j = 0; j < Math.min(errorEls.length, 3); j++) errorTexts.push(_txt(errorEls[j]));
  var successTexts = []; for (var k = 0; k < Math.min(successEls.length, 3); k++) successTexts.push(_txt(successEls[k]));

  return {
    url: window.location.href,
    title: document.title,
    h1: _txt(h1El),
    forms: _ta('form,dialog').length,
    modals: modalEls.length,
    visible_modal: visibleModal,
    toasts: _ta('[class*="toast"],[class*="alert"],[class*="snack"]').length,
    toast_text: _txt(toastEl),
    rows: rows,
    buttons: buttons,
    loaders: loaderEls.length,
    overlay: !!(overlayEl && window.getComputedStyle(overlayEl).display !== 'none'),
    error_msgs: errorTexts.join(' | '),
    success_msgs: successTexts.join(' | ')
  };
})()
"""


@dataclass
class UISnapshot:
    url: str = ""
    title: str = ""
    h1: str = ""
    forms: int = 0
    modals: int = 0
    visible_modal: bool = False
    toasts: int = 0
    toast_text: str = ""
    rows: int = 0
    buttons: int = 0
    loaders: int = 0
    overlay: bool = False
    error_msgs: str = ""
    success_msgs: str = ""
    captured_at: float = field(default_factory=time.monotonic)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UISnapshot:
        return cls(
            url=d.get("url", ""),
            title=d.get("title", ""),
            h1=d.get("h1", ""),
            forms=int(d.get("forms", 0)),
            modals=int(d.get("modals", 0)),
            visible_modal=bool(d.get("visible_modal", False)),
            toasts=int(d.get("toasts", 0)),
            toast_text=d.get("toast_text", ""),
            rows=int(d.get("rows", 0)),
            buttons=int(d.get("buttons", 0)),
            loaders=int(d.get("loaders", 0)),
            overlay=bool(d.get("overlay", False)),
            error_msgs=d.get("error_msgs", ""),
            success_msgs=d.get("success_msgs", ""),
        )


class UITransitionEngine:
    """Detects DOM state changes via JS fingerprinting between two snapshots."""

    def __init__(self, browser: BrowserManager) -> None:
        self.browser = browser

    def capture(self) -> UISnapshot:
        try:
            result = self.browser.driver.execute_script(_FINGERPRINT_JS)
            if isinstance(result, dict):
                return UISnapshot.from_dict(result)
        except Exception as exc:
            log.debug("UI fingerprint failed", error=str(exc))
        return UISnapshot()

    async def capture_async(self) -> UISnapshot:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.capture)

    def detect_transitions(self, before: UISnapshot, after: UISnapshot) -> list[str]:
        events: list[str] = []

        if before.url != after.url:
            events.append("navigation")

        if not before.visible_modal and after.visible_modal:
            events.append("modal_opened")
        elif before.visible_modal and not after.visible_modal:
            events.append("modal_closed")

        if after.forms > before.forms:
            events.append("form_appeared")

        if after.toasts > before.toasts or (not before.toast_text and after.toast_text):
            events.append("toast_shown")
            toast_lower = after.toast_text.lower()
            if any(w in toast_lower for w in ("success", "saved", "created", "updated", "deleted", "complete")):
                events.append("success_toast")
            elif any(w in toast_lower for w in ("error", "fail", "invalid", "unable", "could not")):
                events.append("error_toast")

        if after.rows > before.rows:
            events.append("rows_added")
        elif after.rows < before.rows and before.rows > 0:
            events.append("rows_removed")

        if not before.overlay and after.overlay:
            events.append("overlay_appeared")
        elif before.overlay and not after.overlay:
            events.append("overlay_closed")

        if after.h1 and before.h1 != after.h1:
            events.append("content_changed")

        # Page went from loading to stable
        if before.loaders > 0 and after.loaders == 0 and not after.overlay:
            events.append("content_loaded")

        return events

    def wait_for_stable(self, timeout_ms: int = 8000) -> bool:
        deadline = time.monotonic() + timeout_ms / 1000.0
        stable_since: float | None = None
        last_source_len = -1

        while time.monotonic() < deadline:
            snap = self.capture()
            if snap.loaders > 0 or snap.overlay:
                stable_since = None
                time.sleep(0.3)
                continue

            try:
                source_len = len(self.browser.driver.page_source)
            except Exception:
                source_len = last_source_len

            if source_len != last_source_len:
                last_source_len = source_len
                stable_since = None
                time.sleep(0.3)
                continue

            if stable_since is None:
                stable_since = time.monotonic()

            if time.monotonic() - stable_since >= 0.8:
                return True

            time.sleep(0.3)

        log.warning("wait_for_stable timed out", timeout_ms=timeout_ms)
        return False

    def is_loading(self) -> bool:
        snap = self.capture()
        return snap.loaders > 0 or snap.overlay
