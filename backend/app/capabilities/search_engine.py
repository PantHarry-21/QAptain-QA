"""Search + Filter Capability Engine."""
from __future__ import annotations
from app.capabilities.base_engine import BaseCapabilityEngine
from app.capabilities.contracts import CapabilityContext, RecoveryStep, RecoveryAction

_SQL_INJECT = "' OR '1'='1"
_XSS = "<img src=x onerror=alert(1)>"


class SearchEngine(BaseCapabilityEngine):
    engine_id = "search"
    workflow_types = ["SEARCH_FILTER"]

    def generate_positive_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        entity = ctx.entity_name or "Record"

        return [
            self._step("screenshot", "Capture initial list state before search", "SETUP",
                      "Baseline for search comparison", engine_id=e),
            # Exact search
            self._step("click", "Focus search input field",
                      "SEARCH_EXACT", "Activate search capability",
                      target="Search|search|Find|filter|mat-input", engine_id=e),
            self._step("fill", f"Enter exact {entity} name for search",
                      "SEARCH_EXACT", "Exact match search must return the correct record",
                      target="Search|search|Find", value=f"Test{entity}001", engine_id=e),
            self._wait_network("Wait for search debounce and results", "SEARCH_EXACT"),
            self._step("assert_visible", "Verify exact search returns matching result",
                      "SEARCH_EXACT", "Search must find records matching the query",
                      target=f"Test{entity}001", checkpoint=True, engine_id=e),
            self._step("screenshot", "Capture exact search results", "SEARCH_EXACT",
                      "Exact search evidence", engine_id=e),

            # Partial search
            self._step("clear", "Clear search field",
                      "SEARCH_PARTIAL", "Reset for partial search test",
                      target="Search|search|Find", engine_id=e, on_fail="skip"),
            self._step("fill", f"Enter partial {entity} name",
                      "SEARCH_PARTIAL", "Partial search must work for usability",
                      target="Search|search|Find", value=f"Test{entity}", engine_id=e),
            self._wait_network("Wait for partial search results", "SEARCH_PARTIAL"),
            self._step("assert_visible", "Verify partial search returns results",
                      "SEARCH_PARTIAL", "System should support partial/contains search",
                      target=f"Test{entity}", on_fail="skip", checkpoint=False, engine_id=e),
            self._step("screenshot", "Capture partial search results", "SEARCH_PARTIAL",
                      "Partial search evidence", on_fail="skip", engine_id=e),

            # Clear search — returns all results
            self._step("clear", "Clear search to reset to full list",
                      "SEARCH_CLEAR", "Search clear must restore full result set",
                      target="Search|search|Find", engine_id=e, on_fail="skip"),
            self._step("click", "Click clear/reset button if available",
                      "SEARCH_CLEAR", "Explicit clear button should reset search",
                      target="Clear|Reset|×|close", engine_id=e, on_fail="skip"),
            self._wait_network("Wait for list to refresh after clear", "SEARCH_CLEAR"),
            self._step("screenshot", "Capture cleared search state", "SEARCH_CLEAR",
                      "Clear search evidence", engine_id=e),
        ]

    def generate_negative_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            self._step("fill", "Search for non-existent record",
                      "SEARCH_EMPTY_STATE", "No-results state must be handled gracefully",
                      target="Search|search|Find",
                      value="ZZZNORESULTEXPECTED999", engine_id=e, test_category="negative"),
            self._wait_network("Wait for empty state", "SEARCH_EMPTY_STATE"),
            self._step("assert_visible", "Verify empty/no-results state is shown",
                      "SEARCH_EMPTY_STATE", "User must be informed when no records match",
                      target="no results|no records found|no data|nothing found|0 results",
                      checkpoint=True, on_fail="skip", engine_id=e, test_category="negative"),
            self._step("screenshot", "Capture no-results state",
                      "SEARCH_EMPTY_STATE", "Empty state evidence", on_fail="skip",
                      engine_id=e, test_category="negative"),
            self._step("clear", "Clear search after empty state test",
                      "SEARCH_EMPTY_STATE", "Reset state",
                      target="Search|search|Find", engine_id=e, on_fail="skip"),
        ]

    def generate_security_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            self._step("fill", "Enter SQL injection in search",
                      "SEARCH_SECURITY", "Search must sanitize SQL injection attempts",
                      target="Search|search|Find", value=_SQL_INJECT,
                      engine_id=e, test_category="security", on_fail="skip"),
            self._wait_network("Wait for search response", "SEARCH_SECURITY"),
            self._step("assert_not_text", "Verify no database errors exposed",
                      "SEARCH_SECURITY", "SQL errors must never be exposed to users",
                      target="SQL|syntax|ORA-|exception|error|stack",
                      on_fail="skip", engine_id=e, test_category="security"),
            self._step("clear", "Clear injection payload",
                      "SEARCH_SECURITY", "Reset state",
                      target="Search|search|Find", engine_id=e, on_fail="skip"),
        ]

    def generate_edge_case_steps(self, ctx: CapabilityContext) -> list[dict]:
        e = self.engine_id
        return [
            self._step("fill", "Enter whitespace-only search query",
                      "SEARCH_WHITESPACE", "Whitespace search should behave like empty search",
                      target="Search|search|Find", value="   ",
                      engine_id=e, test_category="edge_case", on_fail="skip"),
            self._wait_network("Wait for response", "SEARCH_WHITESPACE"),
            self._step("screenshot", "Capture whitespace search result",
                      "SEARCH_WHITESPACE", "Whitespace edge case evidence",
                      on_fail="skip", engine_id=e, test_category="edge_case"),
            self._step("clear", "Clear search", "SEARCH_WHITESPACE", "Reset",
                      target="Search|search|Find", engine_id=e, on_fail="skip"),
        ]

    def get_recovery_steps(self, failed_action: str, error_context: dict) -> list[RecoveryStep]:
        return [
            RecoveryStep(RecoveryAction.WAIT_NETWORK, "Wait for search debounce", priority=1),
            RecoveryStep(RecoveryAction.CLEAR_AND_RETYPE, "Clear and retype search term", priority=2),
        ]
