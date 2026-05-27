"""
Table Capability Engine — Enterprise table interaction and validation.
Handles dynamic tables, row actions, bulk operations, and data assertions.
"""
from __future__ import annotations
from app.capabilities.base_engine import BaseCapabilityEngine
from app.capabilities.contracts import CapabilityContext, RecoveryStep, RecoveryAction


class TableEngine(BaseCapabilityEngine):
    engine_id = "table"
    workflow_types = ["CRUD", "SEARCH_FILTER", "PAGINATION", "SORTING"]

    def generate_positive_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        entity = ctx.entity_name or "Record"

        return [
            self._step("assert_visible", "Verify table/list container is present",
                      "TABLE_VERIFY", "Table structure must render correctly",
                      target="table|grid|list|data-grid|mat-table|ag-grid", engine_id=e),
            self._step("assert_visible", "Verify table has column headers",
                      "TABLE_VERIFY", "Column headers provide navigation context",
                      target="th|column|header|mat-header-cell", engine_id=e, on_fail="skip"),
            self._step("screenshot", "Capture table initial state",
                      "TABLE_VERIFY", "Table baseline evidence", engine_id=e),
            self._step("scroll", "Scroll through table to verify more rows",
                      "TABLE_VERIFY", "Verify scrollable content loads correctly",
                      target="table|grid|data-list", engine_id=e, on_fail="skip"),
        ]

    def generate_negative_steps(self, ctx: CapabilityContext) -> list[dict]:
        return []

    def generate_edge_case_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            self._step("assert_visible", "Verify empty state is handled gracefully",
                      "EMPTY_STATE", "Table must show empty state message when no records exist",
                      target="no records|no data|empty|nothing found|no results",
                      on_fail="skip", engine_id=e, test_category="edge_case"),
        ]

    def get_recovery_steps(self, failed_action: str, error_context: dict) -> list[RecoveryStep]:
        return [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for table data to load", priority=1),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for table animations", priority=2),
            RecoveryStep(RecoveryAction.REFRESH_TABLE, "Trigger table refresh", priority=3),
        ]
