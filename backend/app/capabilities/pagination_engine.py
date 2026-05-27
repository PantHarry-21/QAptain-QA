"""Pagination Capability Engine."""
from __future__ import annotations
from app.capabilities.base_engine import BaseCapabilityEngine
from app.capabilities.contracts import CapabilityContext, RecoveryStep, RecoveryAction


class PaginationEngine(BaseCapabilityEngine):
    engine_id = "pagination"
    workflow_types = ["PAGINATION"]

    def generate_positive_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id

        return [
            self._step("screenshot", "Capture first page initial state", "PAGINATION_SETUP",
                      "Baseline for pagination testing", engine_id=e),
            self._step("assert_visible", "Verify pagination controls are present",
                      "PAGINATION_VERIFY", "Pagination UI must be rendered",
                      target="pagination|paginator|mat-paginator|page-nav|next|previous",
                      checkpoint=False, engine_id=e),

            # Navigate to next page
            self._step("click", "Click Next Page button",
                      "PAGINATION_NEXT", "Navigate to next page of results",
                      target="Next|next page|>|chevron_right|arrow_forward", engine_id=e),
            self._wait_network("Wait for next page data to load", "PAGINATION_NEXT"),
            self._step("assert_visible", "Verify page indicator shows page 2 or next",
                      "PAGINATION_NEXT", "Page indicator must update to reflect current page",
                      target="2|Page 2|of|page", on_fail="skip", checkpoint=True, engine_id=e),
            self._step("screenshot", "Capture page 2 state", "PAGINATION_NEXT",
                      "Next page evidence", engine_id=e),

            # Navigate to previous page
            self._step("click", "Click Previous Page button",
                      "PAGINATION_PREV", "Navigate back to previous page",
                      target="Previous|prev|<|chevron_left|arrow_back", engine_id=e),
            self._wait_network("Wait for previous page data", "PAGINATION_PREV"),
            self._step("assert_visible", "Verify navigation returned to page 1",
                      "PAGINATION_PREV", "Previous page navigation must work correctly",
                      target="1|Page 1", on_fail="skip", checkpoint=True, engine_id=e),
            self._step("screenshot", "Capture return to page 1", "PAGINATION_PREV",
                      "Previous page evidence", engine_id=e),

            # Page size change
            self._step("click", "Change items-per-page selector",
                      "PAGINATION_SIZE", "Test page size change functionality",
                      target="items per page|rows per page|per page|page size|mat-select",
                      on_fail="skip", engine_id=e),
            self._step("select", "Select different page size",
                      "PAGINATION_SIZE", "Changing page size must reload with new count",
                      target="25|50|100|All", on_fail="skip", engine_id=e),
            self._wait_network("Wait for page size change", "PAGINATION_SIZE"),
            self._step("screenshot", "Capture changed page size state", "PAGINATION_SIZE",
                      "Page size change evidence", on_fail="skip", engine_id=e),
        ]

    def generate_negative_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            # Test boundary — first page Previous should be disabled
            self._step("assert_visible", "Verify Previous button is disabled on first page",
                      "PAGINATION_BOUNDARY", "Previous must be disabled on first page",
                      target="Previous[disabled]|prev[disabled]|aria-disabled",
                      on_fail="skip", checkpoint=False, engine_id=e, test_category="negative"),
        ]

    def get_recovery_steps(self, failed_action: str, error_context: dict) -> list[RecoveryStep]:
        return [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for page data", priority=1),
            RecoveryStep(RecoveryAction.SCROLL_INTO_VIEW, "Scroll pagination controls into view", priority=2),
        ]
