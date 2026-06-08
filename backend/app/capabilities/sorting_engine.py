"""Sorting Capability Engine."""
from __future__ import annotations
from app.capabilities.base_engine import BaseCapabilityEngine
from app.capabilities.contracts import CapabilityContext, RecoveryStep, RecoveryAction


class SortingEngine(BaseCapabilityEngine):
    engine_id = "sorting"
    workflow_types = ["SORTING"]

    def generate_positive_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        entity = ctx.entity_name or "Record"

        return [
            self._step("screenshot", "Capture initial unsorted table state", "SORTING_SETUP",
                      "Baseline for sort comparison", engine_id=e),

            # Sort ascending
            self._step("click", "Click column header to sort ascending",
                      "SORT_ASCENDING", "Column header click must trigger ascending sort",
                      target=f"Name|{entity} Name|Title|Date|ID|Created", engine_id=e),
            self._wait_network("Wait for sort to apply", "SORT_ASCENDING"),
            self._step("assert_visible", "Verify ascending sort indicator is shown",
                      "SORT_ASCENDING", "Sort direction must be visually indicated",
                      target="sort|asc|arrow_upward|↑|active", on_fail="skip", engine_id=e),
            self._step("screenshot", "Capture ascending sort state", "SORT_ASCENDING",
                      "Ascending sort evidence", engine_id=e),

            # Sort descending (click again)
            self._step("click", "Click same column header again to sort descending",
                      "SORT_DESCENDING", "Second click must reverse sort direction",
                      target=f"Name|{entity} Name|Title|Date|ID|Created", engine_id=e),
            self._wait_network("Wait for descending sort", "SORT_DESCENDING"),
            self._step("assert_visible", "Verify descending sort indicator is shown",
                      "SORT_DESCENDING", "Descending sort must be visually indicated",
                      target="sort|desc|arrow_downward|↓|active", on_fail="skip", engine_id=e),
            self._step("screenshot", "Capture descending sort state", "SORT_DESCENDING",
                      "Descending sort evidence", checkpoint=True, engine_id=e),
        ]

    def generate_negative_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            # Try to sort by a non-sortable column — expect no sort applied
            self._step("click", "Click a non-sortable column header (e.g. Actions column)",
                      "SORT_NON_SORTABLE",
                      "Non-sortable columns must not trigger sort when clicked",
                      target="Actions|Action|Options|Controls|Buttons",
                      engine_id=e, test_category="negative", on_fail="skip"),
            self._wait_network("Wait to confirm no sort was applied", "SORT_NON_SORTABLE"),
            self._step("screenshot", "Capture result of clicking non-sortable column",
                      "SORT_NON_SORTABLE", "Non-sortable column behavior evidence",
                      on_fail="skip", engine_id=e, test_category="negative"),
        ]

    def generate_edge_case_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            # Third click — toggle back to unsorted or cycle to no-sort state
            self._step("click", "Click the sorted column a third time to clear sort",
                      "SORT_CLEAR",
                      "Third click on a column may return to default/unsorted order",
                      target="Name|Title|Date|ID|Created", engine_id=e,
                      test_category="edge_case", on_fail="skip"),
            self._wait_network("Wait for sort state change", "SORT_CLEAR"),
            self._step("screenshot", "Capture post-third-click sort state",
                      "SORT_CLEAR", "Sort clear/cycle evidence",
                      on_fail="skip", engine_id=e, test_category="edge_case"),
        ]

    def get_recovery_steps(self, failed_action: str, error_context: dict) -> list[RecoveryStep]:
        return [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for sort operation to complete", priority=1),
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll column header into view", priority=2),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for sort animation to settle", priority=3),
        ]
