"""
Assertion Intelligence System — Multi-layer assertion architecture.
Generates contextual, business-aware assertion specifications.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from app.capabilities.contracts import CapabilityContext


@dataclass
class BusinessAssertion:
    workflow_outcome: str
    layer: str  # ui, workflow, business, data, security
    description: str
    semantic_check: str
    validation_type: str
    critical: bool = True
    confidence_threshold: float = 0.7


# Assertion library keyed by workflow outcome
_ASSERTION_LIBRARY: dict[str, list[BusinessAssertion]] = {
    "record_created": [
        BusinessAssertion("record_created", "ui",
            "Success toast or confirmation message is visible",
            "Look for green success notification, confirmation banner, or 'Created successfully'",
            "form_success", critical=False),
        BusinessAssertion("record_created", "business",
            "New record appears in the listing",
            "The newly created record's name or ID is visible in the table/list",
            "record_created", critical=True),
        BusinessAssertion("record_created", "data",
            "Record count increased",
            "The total number of records in the list is higher than before creation",
            "record_created", critical=False),
    ],
    "record_updated": [
        BusinessAssertion("record_updated", "ui",
            "Update success message is visible",
            "Look for success notification confirming the update",
            "form_success", critical=False),
        BusinessAssertion("record_updated", "business",
            "Updated values are reflected in the listing",
            "The modified field values appear in the table/list view",
            "value_updated", critical=True),
        BusinessAssertion("record_updated", "data",
            "Original values are replaced",
            "The old values no longer appear in the list for this record",
            "value_updated", critical=False),
    ],
    "record_deleted": [
        BusinessAssertion("record_deleted", "ui",
            "Deletion success message is visible",
            "Success notification confirms the deletion",
            "form_success", critical=False),
        BusinessAssertion("record_deleted", "business",
            "Deleted record is removed from listing",
            "The deleted record's name/ID does not appear in the table",
            "record_deleted", critical=True),
        BusinessAssertion("record_deleted", "data",
            "Record count decreased",
            "Total record count is lower than before deletion",
            "record_deleted", critical=False),
    ],
    "form_validation": [
        BusinessAssertion("form_validation", "ui",
            "Field-level error messages appear",
            "Red error text or icons appear next to invalid fields",
            "form_error", critical=True),
        BusinessAssertion("form_validation", "workflow",
            "Form submission is blocked",
            "The form was NOT submitted — user remains on the form with errors",
            "form_error", critical=True),
    ],
    "search_results": [
        BusinessAssertion("search_results", "ui",
            "Result count or result rows are visible",
            "Table shows matching records or result count indicator changes",
            "results_visible", critical=True),
        BusinessAssertion("search_results", "business",
            "Results match the search query",
            "Visible results contain the search term in relevant fields",
            "results_visible", critical=True),
    ],
    "access_denied": [
        BusinessAssertion("access_denied", "security",
            "Access denied message or redirect occurred",
            "User sees 403, 'Unauthorized', or is redirected to login",
            "access_denied", critical=True),
        BusinessAssertion("access_denied", "ui",
            "Restricted UI elements are not visible",
            "Buttons, menus, or data for unauthorized resources are hidden",
            "access_denied", critical=True),
    ],
    "export_complete": [
        BusinessAssertion("export_complete", "ui",
            "Download started or file was generated",
            "Browser download triggered or success message indicates export",
            "export_downloaded", critical=True),
    ],
    "pagination_worked": [
        BusinessAssertion("pagination_worked", "ui",
            "Page indicator updated to new page",
            "Page number, 'of N' text, or active page indicator changed",
            "navigation_success", critical=True),
        BusinessAssertion("pagination_worked", "data",
            "Table content changed after pagination",
            "The rows visible in the table are different from the previous page",
            "navigation_success", critical=True),
    ],
}


class AssertionEngine:
    """
    Generates contextual, multi-layer assertions based on workflow type and outcome.
    Called by the QA Reasoning Engine to enrich plans with business-aware validations.
    """

    def get_assertions_for_outcome(self, outcome: str) -> list[BusinessAssertion]:
        return _ASSERTION_LIBRARY.get(outcome, [])

    def get_assertions_for_workflow(self, workflow_type: str) -> list[BusinessAssertion]:
        """Map workflow type to relevant assertion outcomes."""
        outcome_map = {
            "CRUD": ["record_created", "record_updated", "record_deleted", "form_validation"],
            "SEARCH_FILTER": ["search_results"],
            "FORM_VALIDATION": ["form_validation"],
            "ROLE_ACCESS": ["access_denied"],
            "EXPORT": ["export_complete"],
            "PAGINATION": ["pagination_worked"],
            "SORTING": ["pagination_worked"],
        }
        outcomes = outcome_map.get(workflow_type, [])
        all_assertions = []
        for outcome in outcomes:
            all_assertions.extend(self.get_assertions_for_outcome(outcome))
        return all_assertions

    def build_checkpoint_validation(self, assertion: BusinessAssertion) -> dict:
        """Convert a BusinessAssertion to a checkpoint_validation dict for the plan."""
        return {
            "validation_type": assertion.validation_type,
            "description": assertion.description,
            "semantic_check": assertion.semantic_check,
            "critical": assertion.critical,
            "confidence_threshold": assertion.confidence_threshold,
            "layer": assertion.layer,
        }

    def build_assertion_context(
        self, workflow_type: str, ctx: CapabilityContext
    ) -> dict[str, Any]:
        """Build full assertion context for injection into AI prompt."""
        assertions = self.get_assertions_for_workflow(workflow_type)
        return {
            "workflow_type": workflow_type,
            "entity": ctx.entity_name or "Record",
            "assertion_layers": {
                "ui": [a.description for a in assertions if a.layer == "ui"],
                "business": [a.description for a in assertions if a.layer == "business"],
                "data": [a.description for a in assertions if a.layer == "data"],
                "security": [a.description for a in assertions if a.layer == "security"],
            },
            "critical_assertions": [a.description for a in assertions if a.critical],
            "checkpoint_validations": [
                self.build_checkpoint_validation(a) for a in assertions if a.critical
            ],
        }


# Module-level singleton
_assertion_engine: AssertionEngine | None = None


def get_assertion_engine() -> AssertionEngine:
    global _assertion_engine
    if _assertion_engine is None:
        _assertion_engine = AssertionEngine()
    return _assertion_engine
