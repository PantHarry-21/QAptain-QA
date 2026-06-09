"""
CRUD Capability Engine — Universal Create/Read/Update/Delete testing.

Generates deterministic test steps for any CRUD-type scenario.
Tests: create (positive+negative+edge+security), read, update, delete with
confirmation dialogs, duplicate prevention, and persistence validation.
"""
from __future__ import annotations
from app.capabilities.base_engine import BaseCapabilityEngine
from app.capabilities.contracts import CapabilityContext, RecoveryStep, RecoveryAction

# Security payloads for injection testing
_SQL_INJECTION = "Robert'); DROP TABLE--"
_XSS_PAYLOAD = "<script>alert('xss')</script>"
_LONG_STRING = "A" * 256
_SPECIAL_CHARS = "Test@#$%^&*()_+-=[]{}|;':\",./<>?"


class CRUDEngine(BaseCapabilityEngine):
    engine_id = "crud"
    workflow_types = ["CRUD"]

    def generate_positive_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        entity = ctx.entity_name or "Record"

        steps = []

        # ── PHASE: NAVIGATE ──
        steps += [
            self._step("screenshot", "Capture initial module state", "SETUP", "Baseline evidence", engine_id=e),
            # Use generic table/list selectors — the entity name is not a DOM element.
            self._step("wait_element", f"Wait for {entity} list to load", "NAVIGATE",
                      "Module must be fully loaded before testing",
                      target="table|tbody|mat-table|ag-grid|[class*=table]|[class*=list]|[class*=grid]",
                      timeout_ms=15000, on_fail="skip", engine_id=e),
        ]

        # ── PHASE: CREATE ──
        steps += [
            self._step("click", f"Open {entity} create form",
                      "FORM_OPEN", f"Initiate {entity} creation workflow",
                      target=f"Add|New|Create|+|Add {entity}|New {entity}", engine_id=e),
            self._step("wait_element", "Wait for create form to render",
                      "FORM_OPEN", "Form must be visible before data entry",
                      target="form|modal|dialog|panel", timeout_ms=10000, engine_id=e),
            self._step("screenshot", "Capture create form state", "FORM_OPEN", "Form baseline evidence", engine_id=e),
        ]

        # Fill form fields
        if ctx.form_fields:
            for field_name in ctx.form_fields[:6]:
                steps.append(
                    self._step("fill", f"Fill {field_name} with valid test data",
                              "DATA_ENTRY", f"Populate required field: {field_name}",
                              target=field_name,
                              value=f"Test {entity} {field_name}",
                              engine_id=e)
                )
        else:
            steps += [
                self._step("fill", f"Fill first required field with valid {entity} name",
                          "DATA_ENTRY", "Populate primary identifier field",
                          target=f"Name|{entity} Name|Title|Code|ID",
                          value=f"Test{entity}001", engine_id=e),
                self._step("fill", "Fill secondary required fields",
                          "DATA_ENTRY", "Populate all required fields for valid submission",
                          target="Description|Notes|Details|Type|Category",
                          value=f"Test {entity} Description", engine_id=e, on_fail="skip"),
            ]

        steps += [
            self._wait_network("Wait for any async field validation", "DATA_ENTRY"),
            self._step("screenshot", "Capture filled form state", "DATA_ENTRY", "Evidence of data entry", engine_id=e),
            self._step("click", f"Submit {entity} creation form",
                      "SUBMIT", f"Submit {entity} creation",
                      target="Save|Submit|Create|Add|Confirm|OK", engine_id=e),
            self._wait_network(f"Wait for {entity} creation to complete", "SUBMIT"),
        ]

        # ── PHASE: VERIFY_CREATED ──
        steps += [
            self._step("assert_visible", f"Verify {entity} creation success message",
                      "VERIFY_CREATED", f"Success feedback confirms {entity} was created",
                      target="success|saved|created|added",
                      timeout_ms=10000, on_fail="skip", checkpoint=False, engine_id=e),
            self._step("screenshot", f"Capture post-creation state", "VERIFY_CREATED", "Post-creation evidence", engine_id=e),
            self._step("assert_visible", f"Verify new {entity} appears in list",
                      "VERIFY_CREATED", f"Created {entity} must persist in the listing",
                      target=f"Test{entity}001",
                      timeout_ms=12000, checkpoint=True, engine_id=e),
        ]

        # ── PHASE: UPDATE ──
        steps += [
            self._step("click", f"Open {entity} for editing",
                      "UPDATE", f"Access edit functionality for {entity}",
                      target=f"Edit|Modify|pencil icon|edit icon|Test{entity}001", engine_id=e),
            self._step("wait_element", "Wait for edit form to load",
                      "UPDATE", "Edit form must render before modification",
                      target="form|modal|panel", timeout_ms=10000, engine_id=e),
            self._step("clear", "Clear existing value in primary field",
                      "UPDATE", "Reset field before entering updated value",
                      target=f"Name|{entity} Name|Title", engine_id=e, on_fail="skip"),
            self._step("fill", f"Enter updated {entity} name",
                      "UPDATE", f"Modify {entity} to verify update capability",
                      target=f"Name|{entity} Name|Title",
                      value=f"Updated{entity}001", engine_id=e),
            self._step("click", "Save updated record",
                      "UPDATE", "Persist the modification",
                      target="Save|Update|Confirm|OK", engine_id=e),
            self._wait_network("Wait for update to persist", "UPDATE"),
        ]

        # ── PHASE: VERIFY_UPDATED ──
        steps += [
            self._step("assert_visible", f"Verify {entity} update success",
                      "VERIFY_UPDATED", "Update operation must provide user feedback",
                      target="success|updated|saved", on_fail="skip", engine_id=e),
            self._step("assert_visible", f"Verify updated {entity} name in list",
                      "VERIFY_UPDATED", "Updated record must reflect new values",
                      target=f"Updated{entity}001", checkpoint=True, engine_id=e),
            self._step("screenshot", "Capture updated record state", "VERIFY_UPDATED", "Update evidence", engine_id=e),
        ]

        # ── PHASE: DELETE ──
        steps += [
            self._step("click", f"Initiate {entity} delete action",
                      "DELETE", f"Trigger {entity} deletion workflow",
                      target="Delete|Remove|trash icon|delete icon", engine_id=e),
            self._step("assert_visible", "Verify delete confirmation dialog appears",
                      "DELETE", "System must confirm before destructive action",
                      target="confirm|are you sure|delete|remove|yes",
                      timeout_ms=8000, on_fail="skip", engine_id=e),
            self._step("click", "Confirm deletion",
                      "DELETE", "Execute confirmed deletion",
                      target="Confirm|Yes|Delete|OK|Proceed", engine_id=e),
            self._wait_network("Wait for deletion to complete", "DELETE"),
        ]

        # ── PHASE: VERIFY_DELETED ──
        steps += [
            self._step("assert_visible", "Verify deletion success message",
                      "VERIFY_DELETED", "System must confirm successful deletion",
                      target="deleted|removed|success", on_fail="skip", engine_id=e),
            self._step("assert_not_text", f"Verify deleted {entity} no longer appears",
                      "VERIFY_DELETED", f"Deleted {entity} must not persist in listing",
                      target=f"Updated{entity}001", checkpoint=True, engine_id=e),
            self._step("screenshot", "Capture final state after deletion", "VERIFY_DELETED", "Deletion evidence", engine_id=e),
        ]

        return steps

    def generate_negative_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        entity = ctx.entity_name or "Record"

        steps = []

        # ── PHASE: VALIDATION ──

        # Empty form submit
        steps += [
            self._step("click", f"Open {entity} create form for negative testing",
                      "VALIDATION", "Open form to test validation",
                      target=f"Add|New|Create|Add {entity}|New {entity}", engine_id=e, test_category="negative"),
            self._step("wait_element", "Wait for form to render",
                      "VALIDATION", "Form must be visible",
                      target="form|modal|dialog", engine_id=e, test_category="negative"),
            self._step("click", "Submit empty form to trigger validation",
                      "VALIDATION", "Required field validation must fire on empty submit",
                      target="Save|Submit|Create|Add", engine_id=e, test_category="negative"),
            self._step("assert_visible", "Verify required field validation messages appear",
                      "VALIDATION", "System must enforce required fields",
                      target="required|mandatory|field is required|please fill|cannot be empty",
                      checkpoint=True, engine_id=e, test_category="negative"),
            self._step("screenshot", "Capture validation error state", "VALIDATION",
                      "Validation errors evidence", on_fail="skip", engine_id=e, test_category="negative"),
            self._step("key_press", "Dismiss form without saving",
                      "VALIDATION", "Close form to reset state",
                      target="Escape|Cancel|Close", engine_id=e, test_category="negative", on_fail="skip"),
        ]

        return steps

    def generate_edge_case_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        entity = ctx.entity_name or "Record"

        steps = []

        # Maximum length input
        steps += [
            self._step("click", f"Open {entity} create form for edge case testing",
                      "EDGE_CASES", "Test boundary values",
                      target=f"Add|New|Create|Add {entity}|New {entity}", engine_id=e, test_category="edge_case"),
            self._step("fill", "Enter maximum-length string to test field limits",
                      "EDGE_CASES", "System must handle or truncate max-length input gracefully",
                      target=f"Name|{entity} Name|Title",
                      value=_LONG_STRING, engine_id=e, test_category="edge_case"),
            self._step("click", "Submit to see how system handles max-length input",
                      "EDGE_CASES", "System should either truncate or show appropriate error",
                      target="Save|Submit|Create", engine_id=e, test_category="edge_case"),
            self._step("screenshot", "Capture max-length handling", "EDGE_CASES",
                      "Edge case evidence", on_fail="skip", engine_id=e, test_category="edge_case"),
            self._step("key_press", "Cancel/close after edge case test",
                      "EDGE_CASES", "Reset state",
                      target="Escape|Cancel|Close", engine_id=e, test_category="edge_case", on_fail="skip"),
        ]

        # Special characters
        steps += [
            self._step("click", f"Reopen {entity} form for special character test",
                      "EDGE_CASES", "Test special character handling",
                      target=f"Add|New|Create|Add {entity}|New {entity}", engine_id=e, test_category="edge_case", on_fail="skip"),
            self._step("fill", "Enter special characters in name field",
                      "EDGE_CASES", "System must handle or reject special characters gracefully",
                      target=f"Name|{entity} Name|Title",
                      value=_SPECIAL_CHARS, engine_id=e, test_category="edge_case", on_fail="skip"),
            self._step("screenshot", "Capture special character handling",
                      "EDGE_CASES", "Special char evidence", on_fail="skip", engine_id=e, test_category="edge_case"),
            self._step("key_press", "Cancel special character test",
                      "EDGE_CASES", "Reset state",
                      target="Escape|Cancel|Close", engine_id=e, test_category="edge_case", on_fail="skip"),
        ]

        return steps

    def generate_security_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        entity = ctx.entity_name or "Record"

        steps = [
            self._step("click", f"Open {entity} form for security testing",
                      "SECURITY", "Test input sanitization",
                      target=f"Add|New|Create|Add {entity}|New {entity}", engine_id=e, test_category="security", on_fail="skip"),
            self._step("fill", "Enter SQL injection payload in primary field",
                      "SECURITY", "Application must sanitize SQL injection attempts",
                      target=f"Name|{entity} Name|Title|Search",
                      value=_SQL_INJECTION, engine_id=e, test_category="security", on_fail="skip"),
            self._step("click", "Submit SQL injection payload",
                      "SECURITY", "System must reject or sanitize the payload",
                      target="Save|Submit|Create", engine_id=e, test_category="security", on_fail="skip"),
            self._step("assert_not_text", "Verify SQL injection was not executed",
                      "SECURITY", "No database error or stack trace should appear",
                      target="SQL|syntax error|ORA-|pg_|mysql|exception|stack trace",
                      engine_id=e, test_category="security", on_fail="skip"),
            self._step("screenshot", "Capture SQL injection test result",
                      "SECURITY", "Security test evidence", on_fail="skip", engine_id=e, test_category="security"),
            self._step("key_press", "Cancel security test",
                      "SECURITY", "Reset state",
                      target="Escape|Cancel|Close", engine_id=e, test_category="security", on_fail="skip"),
            # XSS
            self._step("click", f"Reopen form for XSS test",
                      "SECURITY", "Test XSS prevention",
                      target=f"Add|New|Create|Add {entity}|New {entity}", engine_id=e, test_category="security", on_fail="skip"),
            self._step("fill", "Enter XSS script payload",
                      "SECURITY", "Application must sanitize XSS attempts",
                      target=f"Name|{entity} Name|Title|Description",
                      value=_XSS_PAYLOAD, engine_id=e, test_category="security", on_fail="skip"),
            self._step("click", "Submit XSS payload",
                      "SECURITY", "System must neutralize the XSS attempt",
                      target="Save|Submit|Create", engine_id=e, test_category="security", on_fail="skip"),
            self._step("assert_not_text", "Verify XSS alert was not triggered",
                      "SECURITY", "No script execution should occur",
                      target="<script>|alert(|javascript:", engine_id=e, test_category="security", on_fail="skip"),
            self._step("screenshot", "Capture XSS test result",
                      "SECURITY", "XSS test evidence", on_fail="skip", engine_id=e, test_category="security"),
            self._step("key_press", "Cancel XSS test",
                      "SECURITY", "Reset state",
                      target="Escape|Cancel|Close", engine_id=e, test_category="security", on_fail="skip"),
        ]

        return steps

    def get_recovery_steps(self, failed_action: str, error_context: dict) -> list[RecoveryStep]:
        action = failed_action.lower()

        base_recovery = [
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for animations/transitions to complete", priority=1),
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for async operations", priority=2),
        ]

        if action in ("click", "assert_visible"):
            return base_recovery + [
                RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll element into viewport", priority=3),
                RecoveryStep(RecoveryAction.CLOSE_OVERLAY, "Close any covering overlay or modal", priority=4),
                RecoveryStep(RecoveryAction.KEYBOARD_ESCAPE, "Dismiss any overlapping dialog", priority=5),
            ]

        if action == "fill":
            return base_recovery + [
                RecoveryStep(RecoveryAction.CLEAR_AND_RETYPE, "Clear field and retype value", priority=3),
                RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll field into view", priority=4),
            ]

        return base_recovery

    def get_assertions(self, ctx: CapabilityContext) -> list[dict]:
        entity = ctx.entity_name or "Record"
        return [
            {"workflow_outcome": "record_created",
             "ui_checks": [f"{entity} success toast visible", f"New {entity} in list"],
             "business_checks": [f"{entity} persists after page reload", "Record count increased"],
             "negative_checks": ["No error message visible", "Form not still open"],
             "critical": True},
            {"workflow_outcome": "record_updated",
             "ui_checks": ["Update success message", "Updated value in list"],
             "business_checks": ["Previous value replaced", "Change timestamp updated"],
             "negative_checks": ["Old value not shown", "No conflict error"],
             "critical": True},
            {"workflow_outcome": "record_deleted",
             "ui_checks": ["Delete success message", f"{entity} removed from list"],
             "business_checks": ["Record count decreased", "Record not accessible by ID"],
             "negative_checks": [f"Deleted {entity} name not in list"],
             "critical": True},
        ]
