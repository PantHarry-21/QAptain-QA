"""
Export Capability Engine — Data export and download workflow testing.

Covers: CSV/Excel/PDF export, filtered export, empty export, download verification.
"""
from __future__ import annotations
from app.capabilities.base_engine import BaseCapabilityEngine
from app.capabilities.contracts import CapabilityContext, RecoveryStep, RecoveryAction


class ExportEngine(BaseCapabilityEngine):
    engine_id = "export"
    workflow_types = ["EXPORT"]

    def generate_positive_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        entity = ctx.entity_name or "Record"

        return [
            self._step("screenshot", "Capture initial data list before export",
                      "EXPORT_SETUP", "Baseline data state before export", engine_id=e),
            self._step("assert_visible", "Verify export button or menu is present",
                      "EXPORT_SETUP", "Export control must be accessible",
                      target="Export|Download|CSV|Excel|PDF|export|download",
                      engine_id=e),

            # Trigger export
            self._step("click", "Click Export button",
                      "EXPORT_TRIGGER", "Initiate data export",
                      target="Export|Download|Export CSV|Export Excel|Export PDF|Export All",
                      engine_id=e),
            self._step("assert_visible", "Verify export format options appear (if shown)",
                      "EXPORT_TRIGGER", "Export menu must offer format choices if applicable",
                      target="CSV|Excel|PDF|XLS|XLSX|format|export type",
                      on_fail="skip", engine_id=e),
            self._step("click", "Select CSV export format",
                      "EXPORT_FORMAT", "Choose CSV as the export format",
                      target="CSV|csv|Comma|.csv",
                      on_fail="skip", engine_id=e),
            self._wait_network("Wait for export to generate and download to start",
                              "EXPORT_DOWNLOAD"),
            self._step("assert_visible", "Verify export success — download started or success message",
                      "EXPORT_VERIFY",
                      "Export must either trigger a file download or show a success confirmation",
                      target="success|downloaded|export complete|generating|file ready|done",
                      timeout_ms=20000, on_fail="skip", checkpoint=True, engine_id=e),
            self._step("screenshot", "Capture export completion state",
                      "EXPORT_VERIFY", "Export success evidence", engine_id=e),
        ]

    def generate_negative_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        entity = ctx.entity_name or "Record"

        return [
            # Export with no data (apply filter that returns no results, then export)
            self._step("click", "Apply a filter that returns zero results",
                      "EXPORT_EMPTY", "Test export behavior when no data matches",
                      target="Search|filter|Find",
                      on_fail="skip", engine_id=e, test_category="negative"),
            self._step("fill", "Enter filter that returns no results",
                      "EXPORT_EMPTY", "Create empty result set for export test",
                      target="Search|filter|Find",
                      value="ZZZNORESULT999", on_fail="skip",
                      engine_id=e, test_category="negative"),
            self._wait_network("Wait for empty results", "EXPORT_EMPTY"),
            self._step("click", "Attempt export with empty result set",
                      "EXPORT_EMPTY", "Export with no data should be handled gracefully",
                      target="Export|Download|CSV|Excel",
                      on_fail="skip", engine_id=e, test_category="negative"),
            self._step("assert_visible", "Verify system handles empty export gracefully",
                      "EXPORT_EMPTY",
                      "System must either show 'no data' message or export empty file with headers",
                      target="no data|no records|empty|nothing to export|0 records",
                      on_fail="skip", checkpoint=True, engine_id=e, test_category="negative"),
            self._step("screenshot", "Capture empty export result",
                      "EXPORT_EMPTY", "Empty export handling evidence",
                      on_fail="skip", engine_id=e, test_category="negative"),
        ]

    def generate_edge_case_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            # Export filtered subset
            self._step("click", "Filter data before export",
                      "EXPORT_FILTERED", "Test filtered export — only visible data should be exported",
                      target="Search|filter",
                      on_fail="skip", engine_id=e, test_category="edge_case"),
            self._step("fill", "Enter partial filter to get a subset",
                      "EXPORT_FILTERED", "Create a subset result for filtered export",
                      target="Search|filter|Find",
                      value="Test", on_fail="skip", engine_id=e, test_category="edge_case"),
            self._wait_network("Wait for filtered results", "EXPORT_FILTERED"),
            self._step("click", "Export filtered results",
                      "EXPORT_FILTERED", "Filtered export must only contain matching records",
                      target="Export|Download|CSV|Excel",
                      on_fail="skip", engine_id=e, test_category="edge_case"),
            self._step("screenshot", "Capture filtered export result",
                      "EXPORT_FILTERED", "Filtered export evidence",
                      on_fail="skip", engine_id=e, test_category="edge_case"),
        ]

    def get_recovery_steps(self, failed_action: str, error_context: dict) -> list[RecoveryStep]:
        return [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for export generation to finish", priority=1),
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll export button into view", priority=2),
            RecoveryStep(RecoveryAction.WAIT_ANIMATION, "Wait for export menu to open", priority=3),
        ]
