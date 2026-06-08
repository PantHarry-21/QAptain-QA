"""
Form Capability Engine — Dynamic form testing intelligence.
Handles multi-step forms, dependent fields, validation, and edge cases.
"""
from __future__ import annotations
from app.capabilities.base_engine import BaseCapabilityEngine
from app.capabilities.contracts import CapabilityContext, RecoveryStep, RecoveryAction


class FormEngine(BaseCapabilityEngine):
    engine_id = "form"
    workflow_types = ["FORM_VALIDATION", "CRUD"]

    def generate_positive_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        entity = ctx.entity_name or "Record"

        return [
            self._step("assert_visible", "Verify form renders with all expected fields",
                      "FORM_VERIFY", "All required form fields must be visible",
                      target="form|mat-form-field|input|select|textarea", engine_id=e),
            self._step("screenshot", "Capture form initial state", "FORM_VERIFY",
                      "Form baseline for comparison", engine_id=e),
            self._step("assert_visible", "Verify Save/Submit button is present",
                      "FORM_VERIFY", "Form must have a submission mechanism",
                      target="Save|Submit|Create|Add|Confirm|OK", engine_id=e),
        ]

    def generate_negative_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        entity = ctx.entity_name or "Record"

        steps = [
            # Tab through fields without filling — check required indicators
            self._step("click", "Click first form field to focus it",
                      "FORM_VALIDATION", "Activate form field",
                      target="first input|Name|Title", engine_id=e, test_category="negative", on_fail="skip"),
            self._step("key_press", "Tab away without entering data",
                      "FORM_VALIDATION", "Trigger touched/dirty state on required field",
                      target="Tab", engine_id=e, test_category="negative", on_fail="skip"),
            self._step("assert_visible", "Verify field-level required indicator appears",
                      "FORM_VALIDATION", "Required fields must indicate status when touched",
                      target="required|*|error|invalid",
                      on_fail="skip", engine_id=e, test_category="negative"),

            # Submit empty form
            self._step("click", "Click submit with all fields empty",
                      "FORM_VALIDATION", "Test form-level required validation",
                      target="Save|Submit|Create|Add", engine_id=e, test_category="negative"),
            self._step("assert_visible", "Verify validation errors appear for all required fields",
                      "FORM_VALIDATION", "Each required field must show its own error message",
                      target="required|please fill|cannot be empty|field is required",
                      checkpoint=True, engine_id=e, test_category="negative"),
            self._step("screenshot", "Capture form validation errors",
                      "FORM_VALIDATION", "Validation state evidence", on_fail="skip",
                      engine_id=e, test_category="negative"),

            # Test cancel discards changes
            self._step("fill", "Enter test data in a field",
                      "FORM_CANCEL", "Populate form before testing cancel",
                      target="Name|Title|first input",
                      value="DiscardThisValue", engine_id=e, test_category="negative", on_fail="skip"),
            self._step("click", "Click Cancel without saving",
                      "FORM_CANCEL", "Cancel must discard all changes",
                      target="Cancel|Close|Discard|No|×", engine_id=e, test_category="negative", on_fail="skip"),
            self._step("assert_not_text", "Verify discarded value is not saved",
                      "FORM_CANCEL", "Cancelled changes must not persist",
                      target="DiscardThisValue",
                      on_fail="skip", engine_id=e, test_category="negative"),
        ]

        return steps

    def generate_edge_case_steps(self, ctx: CapabilityContext) -> list[dict]:
        """
        Use ValidationSpecEngine to generate field-type-specific edge cases
        when the CapabilityContext carries known form fields (from knowledge graph).
        Falls back to generic edge cases if no field type info is available.
        """
        e = self.engine_id
        steps = []

        # Field-type-specific edge cases from ValidationSpecEngine
        if ctx.form_fields:
            try:
                from app.capabilities.validation_spec import ValidationSpecEngine
                spec = ValidationSpecEngine()
                # Infer field types from labels: email, number, date, phone, url, text
                _type_hints = {
                    "email": ["email", "e-mail", "mail"],
                    "number": ["number", "quantity", "amount", "count", "price", "rate", "age", "qty"],
                    "date": ["date", "dob", "from", "to", "start", "end", "expiry", "deadline"],
                    "phone": ["phone", "mobile", "tel", "contact"],
                    "url": ["url", "website", "link", "href"],
                    "password": ["password", "pass", "secret", "pin"],
                }

                for field_label in ctx.form_fields[:4]:
                    label_lower = field_label.lower()
                    detected_type = "text"
                    for ftype, keywords in _type_hints.items():
                        if any(kw in label_lower for kw in keywords):
                            detected_type = ftype
                            break

                    edge_cases = spec.get_test_cases(detected_type)
                    edge_only = [c for c in edge_cases if c.test_category == "edge_case"]
                    for case in edge_only[:2]:
                        steps.append(
                            self._step("fill", f"Edge case — {field_label}: {case.test_name}",
                                      "FORM_EDGE_CASE",
                                      f"{field_label} field: {case.expected_behavior}",
                                      target=field_label,
                                      value=case.input_value,
                                      engine_id=e, test_category="edge_case", on_fail="skip")
                        )
                        steps.append(
                            self._step("screenshot",
                                      f"Capture {field_label} edge case result",
                                      "FORM_EDGE_CASE", "Edge case evidence",
                                      engine_id=e, on_fail="skip")
                        )
            except Exception:
                pass

        # Generic edge case if no field-specific ones were generated
        if not steps:
            steps.append(
                self._step("fill", "Enter whitespace-only value in a required field",
                          "FORM_EDGE_CASE",
                          "Whitespace-only input must be treated as empty by the form",
                          target="Name|Title|first input",
                          value="   ", engine_id=e, test_category="edge_case", on_fail="skip")
            )
            steps.append(
                self._step("click", "Submit whitespace-only value",
                          "FORM_EDGE_CASE",
                          "System must trim and reject whitespace-only required fields",
                          target="Save|Submit|Create|Add",
                          engine_id=e, test_category="edge_case", on_fail="skip")
            )
            steps.append(
                self._step("screenshot", "Capture whitespace edge case result",
                          "FORM_EDGE_CASE", "Whitespace handling evidence",
                          engine_id=e, on_fail="skip")
            )

        return steps

    def get_recovery_steps(self, failed_action: str, error_context: dict) -> list[RecoveryStep]:
        return [
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for form animation", priority=1),
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll form field into view", priority=2),
            RecoveryStep(RecoveryAction.CLOSE_OVERLAY, "Close overlapping overlay", priority=3),
            RecoveryStep(RecoveryAction.CLEAR_AND_RETYPE, "Clear and retype field value", priority=4),
        ]
