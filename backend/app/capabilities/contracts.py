"""Shared contracts, interfaces and type definitions for QA Capability Engines."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class WorkflowType(str, Enum):
    CRUD = "CRUD"
    SEARCH_FILTER = "SEARCH_FILTER"
    PAGINATION = "PAGINATION"
    SORTING = "SORTING"
    FORM_VALIDATION = "FORM_VALIDATION"
    AUTH = "AUTH"
    ROLE_ACCESS = "ROLE_ACCESS"
    FILE_UPLOAD = "FILE_UPLOAD"
    EXPORT = "EXPORT"
    NAVIGATION = "NAVIGATION"
    BUSINESS_WORKFLOW = "BUSINESS_WORKFLOW"


class RecoveryAction(str, Enum):
    RETRY_CLICK = "retry_click"
    SCROLL_INTO_VIEW = "scroll_into_view"
    CLOSE_OVERLAY = "close_overlay"
    REOPEN_DROPDOWN = "reopen_dropdown"
    WAIT_ANIMATION = "wait_animation"
    REFRESH_TABLE = "refresh_table"
    NAVIGATE_BACK = "navigate_back"
    KEYBOARD_ESCAPE = "keyboard_escape"
    WAIT_NETWORK = "wait_network"
    CLEAR_AND_RETYPE = "clear_and_retype"


@dataclass
class CapabilityContext:
    """Context provided to capability engines for step generation."""
    workflow_type: str
    scenario_title: str
    scenario_description: str = ""
    module_name: str = ""
    module_url: str = ""
    domain_type: str = "GENERIC"
    execution_mode: str = "functional"
    # Hints for data entry
    entity_name: str = ""        # e.g. "Sample", "User", "Order"
    entity_plural: str = ""      # e.g. "Samples", "Users", "Orders"
    form_fields: list[str] = field(default_factory=list)  # known field names


@dataclass
class RecoveryStep:
    """A recovery action to try when a step fails."""
    action: RecoveryAction
    description: str
    applies_to_actions: list[str] = field(default_factory=list)  # which action types trigger this
    priority: int = 5  # 1=highest priority


@dataclass
class AssertionLayer:
    """Multi-layer assertion for a workflow outcome."""
    workflow_outcome: str          # "record_created", "filter_applied", etc.
    ui_checks: list[str]           # what to look for on screen
    business_checks: list[str]     # business-level validations
    negative_checks: list[str]     # things that should NOT be present
    critical: bool = True
