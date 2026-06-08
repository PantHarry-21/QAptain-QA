"""
Recovery Engine — Intelligent per-workflow-type recovery strategies.
Called by PlanRunner when a step fails to provide targeted recovery actions.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from app.capabilities.contracts import RecoveryAction, RecoveryStep


@dataclass
class RecoveryPlan:
    """Ordered list of recovery actions to attempt for a failed step."""
    failed_action: str
    workflow_type: str
    steps: list[RecoveryStep]
    rationale: str = ""


# ── Recovery strategy library ─────────────────────────────────────────────────
# Maps (workflow_type, failed_action) → ordered recovery steps

_RECOVERY_LIBRARY: dict[str, dict[str, list[RecoveryStep]]] = {
    "CRUD": {
        "click": [
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for UI animation to settle", ["click"], 1),
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll target element into viewport", ["click"], 2),
            RecoveryStep(RecoveryAction.CLOSE_OVERLAY, "Close any overlaying modal/toast", ["click"], 3),
            RecoveryStep(RecoveryAction.KEYBOARD_ESCAPE, "Press Escape to dismiss dialogs", ["click"], 4),
        ],
        "fill": [
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll input field into view", ["fill"], 1),
            RecoveryStep(RecoveryAction.CLEAR_AND_RETYPE, "Clear field completely before typing", ["fill"], 2),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for form to finish rendering", ["fill"], 3),
        ],
        "assert_visible": [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for async data to load", ["assert_visible"], 1),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for animations", ["assert_visible"], 2),
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll to reveal element", ["assert_visible"], 3),
        ],
        "select": [
            RecoveryStep(RecoveryAction.REOPEN_DROPDOWN, "Close and reopen dropdown", ["select"], 1),
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll dropdown into view", ["select"], 2),
            RecoveryStep(RecoveryAction.KEYBOARD_ESCAPE, "Dismiss any overlay before selecting", ["select"], 3),
        ],
    },
    "SEARCH_FILTER": {
        "fill": [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for debounce before retrying", ["fill"], 1),
            RecoveryStep(RecoveryAction.CLEAR_AND_RETYPE, "Clear and retype search term", ["fill"], 2),
        ],
        "assert_visible": [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for search results to load", ["assert_visible"], 1),
        ],
    },
    "PAGINATION": {
        "click": [
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll pagination controls into view", ["click"], 1),
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for current page to fully load", ["click"], 2),
        ],
    },
    "SORTING": {
        "click": [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for current sort to stabilize", ["click"], 1),
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll column header into view", ["click"], 2),
        ],
    },
    "FORM_VALIDATION": {
        "fill": [
            RecoveryStep(RecoveryAction.CLEAR_AND_RETYPE, "Clear and retype value", ["fill"], 1),
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll field into view", ["fill"], 2),
        ],
        "click": [
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for form animation", ["click"], 1),
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll button into view", ["click"], 2),
        ],
    },
    "AUTH": {
        "fill": [
            RecoveryStep(RecoveryAction.CLEAR_AND_RETYPE, "Clear credential field and retype", ["fill"], 1),
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll login field into view", ["fill"], 2),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for login form to finish rendering", ["fill"], 3),
        ],
        "click": [
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for login button to become active", ["click"], 1),
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll login button into view", ["click"], 2),
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for previous auth request to finish", ["click"], 3),
        ],
        "assert_visible": [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for auth response to load UI", ["assert_visible"], 1),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for redirect animation", ["assert_visible"], 2),
        ],
        "navigate": [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for login page to load", ["navigate"], 1),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for SPA route to resolve", ["navigate"], 2),
        ],
    },
    "ROLE_ACCESS": {
        "navigate": [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for page to load after navigation", ["navigate"], 1),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for redirect animation to complete", ["navigate"], 2),
        ],
        "assert_visible": [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for access-denied response", ["assert_visible"], 1),
            RecoveryStep(RecoveryAction.NAVIGATE_BACK, "Navigate back from restricted page", ["assert_visible"], 2),
        ],
        "click": [
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll navigation element into view", ["click"], 1),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for nav menu to render", ["click"], 2),
        ],
    },
    "FILE_UPLOAD": {
        "upload": [
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll file input into view", ["upload"], 1),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for upload dialog to stabilize", ["upload"], 2),
        ],
        "click": [
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll upload button into view", ["click"], 1),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for upload area to render", ["click"], 2),
        ],
        "assert_visible": [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for upload to complete", ["assert_visible"], 1),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for success notification", ["assert_visible"], 2),
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll to see upload result", ["assert_visible"], 3),
        ],
    },
    "EXPORT": {
        "click": [
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll export button into view", ["click"], 1),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for export menu to open", ["click"], 2),
            RecoveryStep(RecoveryAction.CLOSE_OVERLAY, "Close any overlapping dialog first", ["click"], 3),
        ],
        "assert_visible": [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for export to generate", ["assert_visible"], 1),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for download notification", ["assert_visible"], 2),
        ],
    },
}

# Generic fallback recovery for any workflow type
_GENERIC_RECOVERY: dict[str, list[RecoveryStep]] = {
    "click": [
        RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for animations to complete", ["click"], 1),
        RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll element into view", ["click"], 2),
        RecoveryStep(RecoveryAction.CLOSE_OVERLAY, "Close covering overlay", ["click"], 3),
        RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for network operations", ["click"], 4),
    ],
    "fill": [
        RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll field into view", ["fill"], 1),
        RecoveryStep(RecoveryAction.CLEAR_AND_RETYPE, "Clear then retype", ["fill"], 2),
    ],
    "assert_visible": [
        RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for data to load", ["assert_visible"], 1),
        RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for transitions", ["assert_visible"], 2),
        RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll to element", ["assert_visible"], 3),
    ],
    "navigate": [
        RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for page to load", ["navigate"], 1),
        RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for SPA routing", ["navigate"], 2),
    ],
    "select": [
        RecoveryStep(RecoveryAction.REOPEN_DROPDOWN, "Reopen dropdown", ["select"], 1),
        RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll into view", ["select"], 2),
    ],
    "wait_element": [
        RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for network", ["wait_element"], 1),
    ],
}


class RecoveryEngine:
    """
    Provides intelligent, workflow-context-aware recovery strategies.
    Called by PlanRunner when a step fails to determine what to try next.
    """

    def get_recovery_plan(
        self,
        failed_action: str,
        workflow_type: str,
        error_message: str = "",
        step_context: dict | None = None,
    ) -> RecoveryPlan:
        """
        Get ordered recovery steps for a failed action given the workflow context.
        Returns workflow-specific recovery if available, otherwise generic.
        """
        action_key = failed_action.lower().split("_")[0]  # "assert_visible" → "assert"
        full_action = failed_action.lower()

        # Try workflow-specific first
        workflow_strategies = _RECOVERY_LIBRARY.get(workflow_type, {})
        steps = (
            workflow_strategies.get(full_action) or
            workflow_strategies.get(action_key) or
            _GENERIC_RECOVERY.get(full_action) or
            _GENERIC_RECOVERY.get(action_key) or
            [RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait and retry", [], 1)]
        )

        # Context-aware adjustments
        if "timeout" in error_message.lower() or "stale" in error_message.lower():
            steps = [RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for network after timeout", [], 0)] + steps

        if "intercepted" in error_message.lower() or "overlay" in error_message.lower():
            steps = [RecoveryStep(RecoveryAction.CLOSE_OVERLAY, "Close intercepting overlay", [], 0)] + steps

        rationale = (
            f"Step '{failed_action}' failed in '{workflow_type}' workflow. "
            f"Applying {len(steps)} recovery strategies in priority order."
        )

        return RecoveryPlan(
            failed_action=failed_action,
            workflow_type=workflow_type,
            steps=sorted(steps, key=lambda s: s.priority),
            rationale=rationale,
        )

    def get_recovery_actions_for_plan_runner(
        self,
        failed_action: str,
        workflow_type: str,
        error_message: str = "",
    ) -> list[str]:
        """
        Returns a list of recovery action strings suitable for the PlanRunner
        to attempt before giving up on a failed step.
        """
        plan = self.get_recovery_plan(failed_action, workflow_type, error_message)
        return [step.action.value for step in plan.steps]


# Module-level singleton
_recovery_engine: RecoveryEngine | None = None


def get_recovery_engine() -> RecoveryEngine:
    global _recovery_engine
    if _recovery_engine is None:
        _recovery_engine = RecoveryEngine()
    return _recovery_engine
