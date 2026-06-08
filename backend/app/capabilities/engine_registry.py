"""
Engine Registry — Central routing system for QA Capability Engines.
Maps workflow types and scenario characteristics to the appropriate engines.
"""
from __future__ import annotations
from typing import Any
import structlog

from app.capabilities.contracts import CapabilityContext, WorkflowType
from app.capabilities.base_engine import BaseCapabilityEngine
from app.capabilities.crud_engine import CRUDEngine
from app.capabilities.table_engine import TableEngine
from app.capabilities.form_engine import FormEngine
from app.capabilities.search_engine import SearchEngine
from app.capabilities.pagination_engine import PaginationEngine
from app.capabilities.sorting_engine import SortingEngine
from app.capabilities.rbac_engine import RBACEngine
from app.capabilities.notification_engine import NotificationEngine
from app.capabilities.auth_engine import AuthEngine
from app.capabilities.file_upload_engine import FileUploadEngine
from app.capabilities.export_engine import ExportEngine
from app.capabilities.assertion_engine import AssertionEngine, get_assertion_engine
from app.capabilities.recovery_engine import RecoveryEngine, get_recovery_engine

log = structlog.get_logger()


class EngineRegistry:
    """
    Central registry for all QA Capability Engines.

    Responsibilities:
    - Register engines by workflow type
    - Route scenarios to appropriate engines
    - Compose multi-engine strategies
    - Provide capability context building
    """

    def __init__(self):
        self._engines: dict[str, BaseCapabilityEngine] = {}
        self._assertion_engine = get_assertion_engine()
        self._recovery_engine = get_recovery_engine()
        self._register_all()

    def _register_all(self):
        """Register all built-in capability engines."""
        engines = [
            CRUDEngine(),
            TableEngine(),
            FormEngine(),
            SearchEngine(),
            PaginationEngine(),
            SortingEngine(),
            RBACEngine(),
            NotificationEngine(),
            AuthEngine(),
            FileUploadEngine(),
            ExportEngine(),
        ]
        for engine in engines:
            self._engines[engine.engine_id] = engine
            log.debug("Capability engine registered", engine_id=engine.engine_id)

    def get_engine(self, engine_id: str) -> BaseCapabilityEngine | None:
        return self._engines.get(engine_id)

    def get_engines_for_workflow(self, workflow_type: str) -> list[BaseCapabilityEngine]:
        """Return all engines that handle the given workflow type."""
        return [
            engine for engine in self._engines.values()
            if workflow_type in engine.workflow_types
        ]

    def get_primary_engine(self, workflow_type: str) -> BaseCapabilityEngine | None:
        """Return the single best engine for this workflow type."""
        primary_map = {
            "CRUD":             "crud",
            "SEARCH_FILTER":    "search",
            "PAGINATION":       "pagination",
            "SORTING":          "sorting",
            "FORM_VALIDATION":  "form",
            "ROLE_ACCESS":      "rbac",
            "AUTH":             "auth",        # AuthEngine: tests login feature itself
            "FILE_UPLOAD":      "file_upload", # FileUploadEngine
            "EXPORT":           "export",      # ExportEngine
            "NAVIGATION":       None,          # simple — AI system prompt handles it
            "BUSINESS_WORKFLOW": None,         # AI-driven, no deterministic engine
        }
        engine_id = primary_map.get(workflow_type)
        return self._engines.get(engine_id) if engine_id else None

    def build_capability_context(
        self,
        scenario_title: str,
        scenario_description: str,
        workflow_type: str,
        module_name: str = "",
        module_url: str = "",
        execution_mode: str = "functional",
    ) -> CapabilityContext:
        """Build a CapabilityContext from scenario metadata."""
        # Infer entity name from scenario title and module name
        entity = self._infer_entity_name(scenario_title, module_name)

        return CapabilityContext(
            workflow_type=workflow_type,
            scenario_title=scenario_title,
            scenario_description=scenario_description,
            module_name=module_name,
            module_url=module_url,
            execution_mode=execution_mode,
            entity_name=entity,
            entity_plural=entity + "s" if entity and not entity.endswith("s") else entity,
        )

    def generate_capability_steps(
        self,
        ctx: CapabilityContext,
        include_negative: bool = True,
        include_edge_cases: bool = True,
        include_security: bool = True,
    ) -> dict[str, list[dict]]:
        """
        Generate all capability steps for the given context.
        Returns a dict with categories: positive, negative, edge_case, security.

        Primary engine handles the main workflow.
        Secondary engines (TableEngine, NotificationEngine) contribute supplementary
        steps for workflows that involve table interaction or user notifications.
        """
        engine = self.get_primary_engine(ctx.workflow_type)
        if not engine:
            return {"positive": [], "negative": [], "edge_case": [], "security": []}

        result = {
            "positive": engine.generate_positive_steps(ctx),
            "negative": engine.generate_negative_steps(ctx) if include_negative else [],
            "edge_case": engine.generate_edge_case_steps(ctx) if include_edge_cases else [],
            "security": engine.generate_security_steps(ctx) if include_security else [],
        }

        # ── TableEngine secondary contributions ───────────────────────────────
        # CRUD needs table verification in VERIFY phases.
        # SEARCH/PAGINATION/SORTING are entirely table-centric — add table edge cases.
        table_engine = self._engines.get("table")
        if table_engine:
            if ctx.workflow_type == "CRUD":
                # Add empty-state edge case: what happens when there are no records?
                if include_edge_cases:
                    result["edge_case"].extend(table_engine.generate_edge_case_steps(ctx))
            elif ctx.workflow_type in ("SEARCH_FILTER", "PAGINATION", "SORTING"):
                # For table-centric workflows: prepend table-presence verification to positive steps
                table_positive = table_engine.generate_positive_steps(ctx)
                result["positive"] = table_positive + result["positive"]
                if include_edge_cases:
                    result["edge_case"].extend(table_engine.generate_edge_case_steps(ctx))

        # ── NotificationEngine secondary contributions ─────────────────────────
        # For FORM_VALIDATION the primary engine (FormEngine) doesn't check notifications —
        # NotificationEngine adds the "error notification must appear" negative check.
        notification_engine = self._engines.get("notification")
        if notification_engine:
            if ctx.workflow_type == "FORM_VALIDATION":
                if include_negative:
                    result["negative"].extend(notification_engine.generate_negative_steps(ctx))

        log.info("Capability steps generated",
            engine=engine.engine_id,
            workflow=ctx.workflow_type,
            positive=len(result["positive"]),
            negative=len(result["negative"]),
            edge_case=len(result["edge_case"]),
            security=len(result["security"]),
        )

        return result

    def get_assertion_context(self, ctx: CapabilityContext) -> dict[str, Any]:
        """
        Get assertion context for AI prompt enrichment.
        Merges AssertionEngine critical assertions with NotificationEngine
        per-operation toast patterns so the AI knows exactly what to assert
        after each CRUD operation.
        """
        base = self._assertion_engine.build_assertion_context(ctx.workflow_type, ctx)

        # For CRUD workflows: inject specific toast assertion targets per operation
        if ctx.workflow_type == "CRUD":
            notification_engine = self._engines.get("notification")
            if notification_engine and hasattr(notification_engine, "get_toast_assertion_for_outcome"):
                toast_hints = [
                    notification_engine.get_toast_assertion_for_outcome("create").get("target", ""),
                    notification_engine.get_toast_assertion_for_outcome("update").get("target", ""),
                    notification_engine.get_toast_assertion_for_outcome("delete").get("target", ""),
                ]
                base.setdefault("toast_patterns", toast_hints)

        return base

    def get_recovery_plan(
        self,
        failed_action: str,
        workflow_type: str,
        error_message: str = "",
    ) -> list[str]:
        """Get recovery action strings for a failed step."""
        return self._recovery_engine.get_recovery_actions_for_plan_runner(
            failed_action, workflow_type, error_message
        )

    def list_engines(self) -> list[dict]:
        """Return metadata about all registered engines."""
        return [engine.get_capability_summary() for engine in self._engines.values()]

    @staticmethod
    def _infer_entity_name(scenario_title: str, module_name: str) -> str:
        """
        Infer the primary entity name from module name or scenario title.

        Priority:
          1. Module name (most reliable — set by knowledge graph mapping)
          2. Regex extraction from scenario title

        Result is CamelCase with no spaces so it works in test data naming:
          "Generic Master" → "GenericMaster"  →  "TestGenericMaster001"
          "User Management" → "UserManagement" →  "TestUserManagement001"
        """
        import re

        _STOP = {"the", "a", "an", "for", "and", "test", "verify", "all", "of",
                 "possible", "scenarios", "operations", "functionality", "module"}

        def _to_camel(text: str) -> str:
            """Convert any space/hyphen/underscore separated words to CamelCase."""
            parts = [p for p in re.split(r"[\s\-_]+", text) if len(p) > 1 and p.lower() not in _STOP]
            return "".join(p.capitalize() for p in parts) if parts else ""

        # ── 1. Module name is always most reliable ────────────────────────────
        if module_name:
            result = _to_camel(module_name)
            if result:
                return result

        # ── 2. Regex extraction from scenario title ───────────────────────────
        title = scenario_title.strip()

        # Multi-word patterns first (greedier)
        multi_patterns = [
            r"(?:test|verify|validate|check)\s+((?:\w+\s+){1,3}\w+)\s+(?:crud|operations|scenarios|functionality)",
            r"(?:crud|operations|scenarios)\s+(?:for|of)\s+((?:\w+\s+){1,3}\w+)",
            r"(?:add|create|manage)\s+((?:\w+\s+){1,2}\w+)",
        ]
        for pattern in multi_patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                result = _to_camel(match.group(1))
                if result:
                    return result

        # Single-word patterns
        single_patterns = [
            r"Test\s+(\w+)\s+CRUD",
            r"CRUD\s+for\s+(\w+)",
            r"Manage\s+(\w+)",
            r"(\w+)\s+Management",
            r"(\w+)\s+Module",
        ]
        for pattern in single_patterns:
            match = re.search(pattern, title, re.IGNORECASE)
            if match:
                word = match.group(1).strip()
                if len(word) > 2 and word.lower() not in _STOP:
                    return word.capitalize()

        return "Record"


# Module-level singleton
_registry: EngineRegistry | None = None


def get_engine_registry() -> EngineRegistry:
    global _registry
    if _registry is None:
        _registry = EngineRegistry()
    return _registry
