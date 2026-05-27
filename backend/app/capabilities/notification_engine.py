"""Notification + Toast Assertion Engine."""
from __future__ import annotations
from app.capabilities.base_engine import BaseCapabilityEngine
from app.capabilities.contracts import CapabilityContext


class NotificationEngine(BaseCapabilityEngine):
    engine_id = "notification"
    workflow_types = ["CRUD", "FORM_VALIDATION", "EXPORT"]

    # Common toast/notification selectors across frameworks
    TOAST_SELECTORS = [
        "snack-bar|mat-snack-bar",      # Angular Material
        "toast|p-toast|ngx-toastr",     # PrimeNG / ngx-toastr
        "alert|notification",            # Bootstrap / generic
        "success|error|warning|info",   # Generic semantic selectors
        "nz-message|ant-message",       # Ant Design
    ]

    SUCCESS_PATTERNS = [
        "success", "saved", "created", "updated", "deleted",
        "completed", "confirmed", "applied", "submitted",
    ]

    ERROR_PATTERNS = [
        "error", "failed", "invalid", "required", "not found",
        "conflict", "duplicate", "unauthorized", "forbidden",
    ]

    def generate_positive_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            self._step("assert_visible", "Verify success notification appears after operation",
                      "NOTIFICATION_VERIFY",
                      "User must receive feedback confirming successful action",
                      target="|".join(self.SUCCESS_PATTERNS),
                      timeout_ms=8000, on_fail="skip", engine_id=e),
        ]

    def generate_negative_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            self._step("assert_visible", "Verify error notification appears on failure",
                      "NOTIFICATION_ERROR",
                      "User must receive clear error feedback",
                      target="|".join(self.ERROR_PATTERNS),
                      on_fail="skip", engine_id=e, test_category="negative"),
        ]

    def get_toast_assertion_for_outcome(self, outcome: str) -> dict:
        """Get a targeted toast assertion for a specific workflow outcome."""
        patterns_map = {
            "create": "success|saved|created|added",
            "update": "success|updated|saved|modified",
            "delete": "deleted|removed|success",
            "error": "error|failed|invalid|conflict",
            "validation": "required|invalid|please fill|error",
        }
        pattern = patterns_map.get(outcome, "success|error")
        return self._step(
            "assert_visible",
            f"Verify {outcome} notification",
            "NOTIFICATION",
            f"System must notify user of {outcome} outcome",
            target=pattern,
            timeout_ms=8000,
            on_fail="skip",
            engine_id=self.engine_id,
        )
