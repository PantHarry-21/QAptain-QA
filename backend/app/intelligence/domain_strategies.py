"""
Domain strategy engine — detects module type and returns QA strategies per domain.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

import structlog

log = structlog.get_logger()


class ModuleType(str, Enum):
    INVENTORY = "inventory"
    ORDERS = "orders"
    USERS = "users"
    ROLES = "roles"
    REPORTING = "reporting"
    FINANCE = "finance"
    SETTINGS = "settings"
    DASHBOARD = "dashboard"
    APPROVAL = "approval"
    SEARCH = "search"
    GENERIC = "generic"


@dataclass
class DomainStrategy:
    module_type: ModuleType
    strategies: list[str]
    checkpoint_types: list[str]
    edge_cases: list[str]
    risk_level: str


_KEYWORDS: dict[str, ModuleType] = {
    "inventory": ModuleType.INVENTORY,
    "stock": ModuleType.INVENTORY,
    "product": ModuleType.INVENTORY,
    "item": ModuleType.INVENTORY,
    "sku": ModuleType.INVENTORY,
    "catalog": ModuleType.INVENTORY,
    "warehouse": ModuleType.INVENTORY,
    "batch": ModuleType.INVENTORY,
    "order": ModuleType.ORDERS,
    "purchase": ModuleType.ORDERS,
    "procurement": ModuleType.ORDERS,
    "sales": ModuleType.ORDERS,
    "quote": ModuleType.ORDERS,
    "user": ModuleType.USERS,
    "employee": ModuleType.USERS,
    "staff": ModuleType.USERS,
    "personnel": ModuleType.USERS,
    "profile": ModuleType.USERS,
    "account": ModuleType.USERS,
    "role": ModuleType.ROLES,
    "permission": ModuleType.ROLES,
    "access": ModuleType.ROLES,
    "privilege": ModuleType.ROLES,
    "policy": ModuleType.ROLES,
    "report": ModuleType.REPORTING,
    "analytics": ModuleType.REPORTING,
    "chart": ModuleType.REPORTING,
    "metrics": ModuleType.REPORTING,
    "kpi": ModuleType.REPORTING,
    "finance": ModuleType.FINANCE,
    "payment": ModuleType.FINANCE,
    "billing": ModuleType.FINANCE,
    "ledger": ModuleType.FINANCE,
    "accounting": ModuleType.FINANCE,
    "setting": ModuleType.SETTINGS,
    "config": ModuleType.SETTINGS,
    "preference": ModuleType.SETTINGS,
    "setup": ModuleType.SETTINGS,
    "approval": ModuleType.APPROVAL,
    "workflow": ModuleType.APPROVAL,
    "review": ModuleType.APPROVAL,
    "search": ModuleType.SEARCH,
    "filter": ModuleType.SEARCH,
    "find": ModuleType.SEARCH,
    "query": ModuleType.SEARCH,
    "dashboard": ModuleType.DASHBOARD,
}

_STRATEGIES: dict[ModuleType, DomainStrategy] = {
    ModuleType.INVENTORY: DomainStrategy(
        module_type=ModuleType.INVENTORY,
        strategies=[
            "Verify stock quantity updates after create/update",
            "Test negative quantity rejection",
            "Check SKU uniqueness enforcement",
            "Validate unit-of-measure field",
            "Verify search/filter by product code",
        ],
        checkpoint_types=["record_visible", "quantity_updated", "search_returns_record"],
        edge_cases=["zero quantity", "duplicate SKU", "special characters in product name", "max quantity overflow"],
        risk_level="MEDIUM",
    ),
    ModuleType.ORDERS: DomainStrategy(
        module_type=ModuleType.ORDERS,
        strategies=[
            "Verify order status transitions are correct",
            "Test order total calculation",
            "Check line item add/remove updates totals",
            "Validate required fields before submission",
            "Verify order appears in listing after create",
        ],
        checkpoint_types=["order_created", "status_transition", "total_correct", "record_visible"],
        edge_cases=["zero quantity line item", "order with no items", "duplicate order number", "max line items"],
        risk_level="HIGH",
    ),
    ModuleType.USERS: DomainStrategy(
        module_type=ModuleType.USERS,
        strategies=[
            "Verify unique email enforcement",
            "Test role assignment and permissions",
            "Check profile update reflects immediately",
            "Validate password strength requirements",
            "Verify deactivated user cannot login",
        ],
        checkpoint_types=["user_created", "role_assigned", "record_visible", "login_blocked"],
        edge_cases=["duplicate email", "empty required fields", "special characters in name", "max field length"],
        risk_level="HIGH",
    ),
    ModuleType.ROLES: DomainStrategy(
        module_type=ModuleType.ROLES,
        strategies=[
            "Verify permission inheritance",
            "Test role assignment to users",
            "Check restricted pages are inaccessible",
            "Validate role name uniqueness",
            "Verify role deletion removes from assigned users",
        ],
        checkpoint_types=["role_created", "permission_applied", "access_denied", "record_visible"],
        edge_cases=["duplicate role name", "role with no permissions", "delete role with active users"],
        risk_level="CRITICAL",
    ),
    ModuleType.REPORTING: DomainStrategy(
        module_type=ModuleType.REPORTING,
        strategies=[
            "Verify report renders without error",
            "Test date range filter produces correct output",
            "Check export produces downloadable file",
            "Validate chart data matches table data",
            "Verify empty-state for no-data scenarios",
        ],
        checkpoint_types=["report_rendered", "data_visible", "export_downloaded"],
        edge_cases=["no data in range", "very large date range", "future dates", "timezone edge cases"],
        risk_level="LOW",
    ),
    ModuleType.FINANCE: DomainStrategy(
        module_type=ModuleType.FINANCE,
        strategies=[
            "Verify transaction totals are accurate",
            "Test decimal precision for amounts",
            "Check currency formatting",
            "Validate negative amounts are rejected where appropriate",
            "Verify audit trail is recorded",
        ],
        checkpoint_types=["amount_correct", "record_visible", "audit_logged", "balance_updated"],
        edge_cases=["zero amount", "negative amount", "max decimal precision", "currency mismatch"],
        risk_level="CRITICAL",
    ),
    ModuleType.SETTINGS: DomainStrategy(
        module_type=ModuleType.SETTINGS,
        strategies=[
            "Verify settings persist after save",
            "Test settings affect application behavior",
            "Check invalid values are rejected",
            "Validate settings revert on cancel",
        ],
        checkpoint_types=["setting_saved", "behavior_changed"],
        edge_cases=["invalid format input", "empty required setting", "concurrent edit"],
        risk_level="MEDIUM",
    ),
    ModuleType.DASHBOARD: DomainStrategy(
        module_type=ModuleType.DASHBOARD,
        strategies=[
            "Verify all widgets render",
            "Test refresh updates metrics",
            "Check navigation links work",
        ],
        checkpoint_types=["widgets_visible", "data_loaded"],
        edge_cases=["no data state", "slow network widgets"],
        risk_level="LOW",
    ),
    ModuleType.APPROVAL: DomainStrategy(
        module_type=ModuleType.APPROVAL,
        strategies=[
            "Verify approval request is routed correctly",
            "Test approve and reject actions",
            "Check notifications are sent",
            "Validate status transitions are enforced",
        ],
        checkpoint_types=["request_submitted", "status_transition", "notification_sent"],
        edge_cases=["self-approval", "expired request", "missing approver"],
        risk_level="HIGH",
    ),
    ModuleType.SEARCH: DomainStrategy(
        module_type=ModuleType.SEARCH,
        strategies=[
            "Verify search returns relevant results",
            "Test filter combinations produce correct subset",
            "Check empty search returns all records",
            "Validate no-results state is shown",
        ],
        checkpoint_types=["results_visible", "filter_applied", "no_results_state"],
        edge_cases=["special characters in query", "SQL injection attempt", "very long query", "whitespace-only query"],
        risk_level="LOW",
    ),
    ModuleType.GENERIC: DomainStrategy(
        module_type=ModuleType.GENERIC,
        strategies=[
            "Verify CRUD operations complete successfully",
            "Test required field validation",
            "Check record appears in list after creation",
            "Validate form cancel discards changes",
        ],
        checkpoint_types=["record_visible", "validation_triggered"],
        edge_cases=["empty required fields", "duplicate records", "max field length"],
        risk_level="MEDIUM",
    ),
}

_CHECKPOINT_DEFINITIONS: dict[str, dict[str, Any]] = {
    "record_visible": {
        "validation_type": "record_visible",
        "description": "Verify created/updated record appears in the listing",
        "semantic_check": "Look for the record name or ID in the current table/list view",
        "critical": True,
    },
    "quantity_updated": {
        "validation_type": "quantity_updated",
        "description": "Verify stock quantity reflects the change",
        "semantic_check": "Confirm quantity value matches expected after create/update",
        "critical": True,
    },
    "search_returns_record": {
        "validation_type": "search_returns_record",
        "description": "Search for the record and verify it is found",
        "semantic_check": "Enter record identifier in search, confirm result appears",
        "critical": False,
    },
    "order_created": {
        "validation_type": "order_created",
        "description": "Verify order is created with correct status",
        "semantic_check": "Confirm order number and status in confirmation or listing",
        "critical": True,
    },
    "status_transition": {
        "validation_type": "status_transition",
        "description": "Verify status changed to expected value",
        "semantic_check": "Confirm status badge or field shows the new status",
        "critical": True,
    },
    "total_correct": {
        "validation_type": "total_correct",
        "description": "Verify calculated total matches sum of line items",
        "semantic_check": "Check displayed total equals expected calculation",
        "critical": True,
    },
    "user_created": {
        "validation_type": "user_created",
        "description": "Verify user account was created",
        "semantic_check": "Confirm user name/email appears in user listing",
        "critical": True,
    },
    "role_assigned": {
        "validation_type": "role_assigned",
        "description": "Verify role was assigned to user",
        "semantic_check": "Confirm role label appears on user record",
        "critical": True,
    },
    "login_blocked": {
        "validation_type": "login_blocked",
        "description": "Verify deactivated user cannot authenticate",
        "semantic_check": "Attempt login and confirm error message is shown",
        "critical": True,
    },
    "role_created": {
        "validation_type": "role_created",
        "description": "Verify role appears in role management listing",
        "semantic_check": "Confirm role name is visible in listing",
        "critical": True,
    },
    "permission_applied": {
        "validation_type": "permission_applied",
        "description": "Verify permission is reflected in the role",
        "semantic_check": "Confirm permission checkbox or label is active",
        "critical": True,
    },
    "access_denied": {
        "validation_type": "access_denied",
        "description": "Verify restricted page is inaccessible",
        "semantic_check": "Navigate to restricted URL and confirm denial message",
        "critical": True,
    },
    "report_rendered": {
        "validation_type": "report_rendered",
        "description": "Verify report page loaded without errors",
        "semantic_check": "Confirm report title is visible and no error message present",
        "critical": True,
    },
    "data_visible": {
        "validation_type": "data_visible",
        "description": "Verify data rows are present in the report",
        "semantic_check": "Confirm table or chart contains data",
        "critical": False,
    },
    "export_downloaded": {
        "validation_type": "export_downloaded",
        "description": "Verify export action triggers a file download",
        "semantic_check": "Click export and confirm download notification or file",
        "critical": False,
    },
    "amount_correct": {
        "validation_type": "amount_correct",
        "description": "Verify financial amount matches expected value",
        "semantic_check": "Confirm displayed amount equals entered or calculated value",
        "critical": True,
    },
    "audit_logged": {
        "validation_type": "audit_logged",
        "description": "Verify transaction appears in audit log",
        "semantic_check": "Navigate to audit log and confirm entry exists",
        "critical": True,
    },
    "balance_updated": {
        "validation_type": "balance_updated",
        "description": "Verify balance reflects the transaction",
        "semantic_check": "Confirm balance or running total changed by transaction amount",
        "critical": True,
    },
    "setting_saved": {
        "validation_type": "setting_saved",
        "description": "Verify setting persisted after save",
        "semantic_check": "Reload settings page and confirm value is unchanged",
        "critical": True,
    },
    "behavior_changed": {
        "validation_type": "behavior_changed",
        "description": "Verify application behavior reflects the setting change",
        "semantic_check": "Perform the relevant action and confirm new behavior",
        "critical": False,
    },
    "widgets_visible": {
        "validation_type": "widgets_visible",
        "description": "Verify all dashboard widgets rendered",
        "semantic_check": "Confirm widget containers are visible and not showing errors",
        "critical": True,
    },
    "data_loaded": {
        "validation_type": "data_loaded",
        "description": "Verify dashboard data loaded successfully",
        "semantic_check": "Confirm loaders have disappeared and numeric values are shown",
        "critical": False,
    },
    "request_submitted": {
        "validation_type": "request_submitted",
        "description": "Verify approval request was submitted",
        "semantic_check": "Confirm submission confirmation or pending status",
        "critical": True,
    },
    "notification_sent": {
        "validation_type": "notification_sent",
        "description": "Verify notification was dispatched",
        "semantic_check": "Check notification log or confirm toast/email sent message",
        "critical": False,
    },
    "results_visible": {
        "validation_type": "results_visible",
        "description": "Verify search results are displayed",
        "semantic_check": "Confirm result rows or count are visible",
        "critical": True,
    },
    "filter_applied": {
        "validation_type": "filter_applied",
        "description": "Verify filter reduced the result set",
        "semantic_check": "Confirm result count or items changed after filter applied",
        "critical": False,
    },
    "no_results_state": {
        "validation_type": "no_results_state",
        "description": "Verify empty state is shown when no results match",
        "semantic_check": "Confirm no-results message is visible",
        "critical": False,
    },
    "validation_triggered": {
        "validation_type": "validation_triggered",
        "description": "Verify form validation fires on invalid input",
        "semantic_check": "Confirm error message appears near the invalid field",
        "critical": True,
    },
}


class DomainStrategyEngine:
    """Maps module names and URLs to domain-specific QA strategies."""

    def detect(self, module_name: str, url: str = "") -> ModuleType:
        combined = (module_name + " " + url).lower()
        for keyword, module_type in _KEYWORDS.items():
            if keyword in combined:
                return module_type
        return ModuleType.GENERIC

    def get_strategy(self, module_type: ModuleType) -> DomainStrategy:
        return _STRATEGIES.get(module_type, _STRATEGIES[ModuleType.GENERIC])

    def get_strategy_for(self, module_name: str, url: str = "") -> DomainStrategy:
        module_type = self.detect(module_name, url)
        return self.get_strategy(module_type)

    def get_additional_checkpoints(
        self,
        module_type: ModuleType,
        executed_phases: list[str],
    ) -> list[dict[str, Any]]:
        strategy = self.get_strategy(module_type)
        result = []
        for cp_type in strategy.checkpoint_types:
            definition = _CHECKPOINT_DEFINITIONS.get(cp_type)
            if definition:
                result.append(definition)
        return result
