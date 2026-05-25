"""
Semantic action engine — translates intent-based actions into browser interactions.
No raw selectors. No AI calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog

from app.execution.browser_manager import BrowserManager
from app.execution.self_healing import SelfHealingEngine

log = structlog.get_logger()

_INTENT_TARGETS: dict[str, list[str]] = {
    "submit_form": ["Submit", "Save", "Create", "Add", "OK", "Confirm", "Apply"],
    "submit_auth": ["Sign In", "Login", "Log In", "Submit", "SIGN IN", "Continue"],
    "open_create_form": ["Add", "New", "Create", "Add New", "+", "Create New"],
    "open_edit_form": ["Edit", "Modify", "Update", "Change"],
    "confirm_delete": ["Delete", "Remove", "Yes", "Confirm", "OK"],
    "cancel_action": ["Cancel", "Close", "Dismiss", "No", "Back"],
    "next_step": ["Next", "Continue", "Proceed", "Forward"],
    "save_changes": ["Save", "Update", "Apply", "Save Changes"],
    "search_action": ["Search", "Find", "Filter", "Go"],
    "export_data": ["Export", "Download", "Excel", "CSV", "PDF"],
}

_INTENT_KEYWORDS: dict[str, str] = {
    "submit": "submit_form",
    "save": "save_changes",
    "create": "open_create_form",
    "add": "open_create_form",
    "edit": "open_edit_form",
    "delete": "confirm_delete",
    "cancel": "cancel_action",
    "next": "next_step",
    "login": "submit_auth",
    "sign": "submit_auth",
    "auth": "submit_auth",
    "search": "search_action",
    "export": "export_data",
}

# JS to fill React/Angular controlled inputs properly
_JS_NATIVE_FILL = """
(function(el, val) {
  var nativeInputValueSetter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype, 'value'
  );
  if (nativeInputValueSetter) {
    nativeInputValueSetter.set.call(el, val);
  } else {
    el.value = val;
  }
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
})(arguments[0], arguments[1])
"""


@dataclass
class ActionResult:
    success: bool
    message: str = ""
    strategy_used: str = ""
    element_label: str = ""
    healing_used: bool = False


class SemanticActionEngine:
    """Performs browser actions via semantic intent — not CSS/XPath selectors."""

    def __init__(self, browser: BrowserManager, healer: SelfHealingEngine) -> None:
        self.browser = browser
        self.healer = healer

    def perform_intent(
        self,
        intent: str,
        target_hint: str = "",
        value: str = "",
    ) -> ActionResult:
        intent_lower = intent.lower()
        canonical = self._classify_intent(intent_lower)
        canonical_targets = _INTENT_TARGETS.get(canonical, [])

        # Intent words themselves can be useful as fallback labels
        intent_words = [w.title() for w in intent_lower.split() if len(w) > 2]

        candidates: list[str] = []
        if target_hint:
            candidates.append(target_hint)
        candidates.extend(canonical_targets)
        # Avoid duplicate intent words already in canonical targets
        canonical_lower = {t.lower() for t in canonical_targets}
        for w in intent_words:
            if w.lower() not in canonical_lower:
                candidates.append(w)

        for label in candidates:
            result = self.healer.find_element(label)
            if result is None:
                continue

            element, strategy, _attempts = result
            if element is None:
                continue

            healing_used = strategy not in ("aria_label", "label_for", "placeholder")

            try:
                if value:
                    self.browser.driver.execute_script(_JS_NATIVE_FILL, element, value)
                    log.debug("Filled element", label=label, strategy=strategy)
                else:
                    success, msg = self.healer.click_with_healing(element)
                    if not success:
                        log.debug("Click failed, trying next candidate", label=label, reason=msg)
                        continue
                    log.debug("Clicked element", label=label, strategy=strategy)

                return ActionResult(
                    success=True,
                    message=f"Action performed on '{label}' via {strategy}",
                    strategy_used=strategy or "",
                    element_label=label,
                    healing_used=healing_used,
                )
            except Exception as exc:
                log.debug("Action error on candidate", label=label, error=str(exc))
                continue

        return ActionResult(
            success=False,
            message=f"No element found for intent '{intent}' — tried {len(candidates)} candidates",
        )

    def _classify_intent(self, intent_lower: str) -> str:
        for keyword, canonical in _INTENT_KEYWORDS.items():
            if keyword in intent_lower:
                return canonical
        return "submit_form"

    def resolve_target(
        self,
        target: str,
        element_type: str = "",
    ) -> Any | None:
        result = self.healer.find_element(target, element_type or None)
        if result is None:
            return None
        element, _strategy, _attempts = result
        return element
