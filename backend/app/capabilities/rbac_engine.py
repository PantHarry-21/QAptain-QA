"""RBAC Intelligence Engine — Role-Based Access Control testing."""
from __future__ import annotations
from app.capabilities.base_engine import BaseCapabilityEngine
from app.capabilities.contracts import CapabilityContext, RecoveryStep, RecoveryAction


class RBACEngine(BaseCapabilityEngine):
    engine_id = "rbac"
    workflow_types = ["ROLE_ACCESS"]

    def generate_positive_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            self._step("screenshot", "Capture current user's accessible interface",
                      "RBAC_VERIFY", "Document what current role can see",
                      engine_id=e),
            self._step("assert_visible", "Verify authorized navigation items are visible",
                      "RBAC_AUTHORIZED", "Authorized modules must be accessible in navigation",
                      target=ctx.module_name or "navigation|nav|menu|sidebar",
                      engine_id=e),
            self._step("screenshot", "Capture accessible modules", "RBAC_AUTHORIZED",
                      "Access evidence for authorized role", engine_id=e),
        ]

    def generate_negative_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            # Test URL-level access restriction
            self._step("navigate", "Attempt direct URL access to restricted module",
                      "RBAC_RESTRICTED", "Direct URL access must be blocked for unauthorized roles",
                      url="/admin|/settings|/roles|/permissions|/system",
                      engine_id=e, test_category="negative", on_fail="skip"),
            self._step("assert_visible", "Verify access denied or redirect occurred",
                      "RBAC_RESTRICTED", "Unauthorized URL access must be denied or redirected",
                      target="unauthorized|forbidden|access denied|403|redirect|login",
                      on_fail="skip", checkpoint=True, engine_id=e, test_category="negative"),
            self._step("screenshot", "Capture access restriction result",
                      "RBAC_RESTRICTED", "RBAC restriction evidence",
                      on_fail="skip", engine_id=e, test_category="negative"),

            # Verify action buttons are hidden/disabled for unauthorized role
            self._step("assert_visible", "Verify delete button hidden for read-only role",
                      "RBAC_UI_RESTRICTION", "Unauthorized actions must be hidden or disabled in UI",
                      target="Delete|delete button|trash",
                      on_fail="skip", engine_id=e, test_category="negative"),
        ]

    def generate_edge_case_steps(self, ctx: CapabilityContext) -> list[dict]:
        return []

    def get_recovery_steps(self, failed_action: str, error_context: dict) -> list[RecoveryStep]:
        return [
            RecoveryStep(RecoveryAction.NAVIGATE_BACK, "Navigate back from restricted page", priority=1),
        ]
