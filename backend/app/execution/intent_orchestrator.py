"""
Intent Orchestrator — Master Execution Intelligence Coordinator.

The central nervous system of QAptain's execution pipeline.
Transforms a scenario from "test intent" into "intelligent execution."

Architecture:
  ExecutionOrchestrator / BatchExecutionOrchestrator
    → IntentOrchestrator.prepare(scenario, plan_data, env_base_url)
        → IntentAnalyzer.analyze()          fast AI intent extraction
        → EntityTracker(entity_type)        entity lifecycle tracker
        → CapabilityEngine.build_context()  deterministic step/assertion context
        → returns ExecutionContext
    → runner.entity_tracker = ctx.entity_tracker
    → runner.execute_plan(plan_data)
    → IntentOrchestrator.post_execute(step_results, ctx)
        → validates entity lifecycle
        → returns business-level execution summary

This is the layer that makes QAptain behave like a human QA engineer
rather than a script runner. It understands WHAT is being tested, not
just which steps to execute.

Critical design rules:
  - prepare() is always non-blocking (10s AI timeout, rule-based fallback)
  - post_execute() never raises (all errors logged, not propagated)
  - EntityTracker is per-run, not shared across batch runs
  - No browser interaction here — pure intelligence coordination
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import Scenario, ApplicationModule
from app.execution.entity_tracker import EntityTracker
from app.intelligence.intent_analyzer import IntentAnalyzer

log = structlog.get_logger()


@dataclass
class ExecutionContext:
    """
    Shared intelligence context for one execution run.

    Created by IntentOrchestrator.prepare() and passed to:
      - PlanRunner (via runner.entity_tracker)
      - Reporting (via post_execute())
    """
    # ── Business intent ────────────────────────────────────────────────────────
    primary_entity: str          # "Product" (not "Products")
    entity_plural: str           # "Products"
    workflow_type: str           # "CRUD" | "SEARCH_FILTER" | ...
    business_context: str        # "Verify product lifecycle management"
    operations: list[str]        # ["create", "read", "update", "delete"]
    likely_fields: list[str]     # ["Name", "Code", "Price", "Status"]
    critical_rules: list[str]    # ["Name must be unique"]
    risk_areas: list[str]        # ["duplicate prevention"]

    # ── Test data naming (deterministic, matches capability engine) ────────────
    create_entity_name: str      # "TestProduct001"
    update_entity_name: str      # "UpdatedProduct001"

    # ── Runtime tracking ───────────────────────────────────────────────────────
    entity_tracker: EntityTracker = field(default_factory=EntityTracker)

    # ── Module context ─────────────────────────────────────────────────────────
    module_name: str = ""
    module_url: str = ""

    # ── Raw intent (for debugging / advanced use) ──────────────────────────────
    intent: dict = field(default_factory=dict)


class IntentOrchestrator:
    """
    Orchestrates intelligent test execution.

    Transforms a bare scenario into a rich ExecutionContext that carries
    entity tracking, business context, and test data naming throughout
    the entire execution lifecycle.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._analyzer = IntentAnalyzer()

    async def prepare(
        self,
        scenario: Scenario,
        plan_data: dict[str, Any],
        env_base_url: str = "",
    ) -> ExecutionContext:
        """
        Build execution context before the run starts.

        Steps:
          1. Load module name/URL from database
          2. Run fast AI intent extraction (10s timeout, rule-based fallback)
          3. Reconcile workflow_type with what the plan already classified
          4. Create EntityTracker with the correct entity type
          5. Return ExecutionContext

        Always returns a valid context — never raises.
        """
        try:
            module_name, module_url = await self._load_module_context(scenario)

            intent = await self._analyzer.analyze(
                title=scenario.title,
                description=scenario.description or "",
                module_name=module_name,
                module_context=f"url={env_base_url}",
            )

            # Trust the plan's workflow_type if AI already classified it
            workflow_type = (
                plan_data.get("workflow_type")
                or intent.get("workflow_type", "CRUD")
            )

            primary_entity = intent.get("primary_entity") or module_name or "Record"
            # De-pluralize if module name was used (e.g. "Products" → "Product")
            if primary_entity.lower().endswith("s") and len(primary_entity) > 4:
                entity_singular = primary_entity[:-1]
            else:
                entity_singular = primary_entity

            entity_plural = intent.get("entity_plural") or (entity_singular + "s")

            # Deterministic test data names — must match capability engine convention
            naming = intent.get("data_naming", {})
            create_name = naming.get("create_name") or f"Test{entity_singular}001"
            update_name = naming.get("update_name") or f"Updated{entity_singular}001"

            tracker = EntityTracker(entity_type=entity_singular)

            ctx = ExecutionContext(
                primary_entity=entity_singular,
                entity_plural=entity_plural,
                workflow_type=workflow_type,
                business_context=intent.get("business_context", ""),
                operations=intent.get("operations", []),
                likely_fields=intent.get("likely_fields", []),
                critical_rules=intent.get("critical_business_rules", []),
                risk_areas=intent.get("risk_areas", []),
                create_entity_name=create_name,
                update_entity_name=update_name,
                entity_tracker=tracker,
                module_name=module_name,
                module_url=module_url,
                intent=intent,
            )

            log.info("IntentOrchestrator: context prepared",
                entity=entity_singular,
                workflow=workflow_type,
                create_name=create_name,
                update_name=update_name,
                module=module_name or "—",
            )
            return ctx

        except Exception as e:
            log.warning("IntentOrchestrator.prepare failed — using minimal context",
                error=str(e)[:120])
            return self._minimal_context(scenario, plan_data)

    async def post_execute(
        self,
        step_results: list[Any],
        ctx: ExecutionContext,
    ) -> dict[str, Any]:
        """
        Post-execution business-level analysis.

        Validates entity lifecycle (was the entity created? deleted?),
        assesses workflow completion, and returns a structured summary
        that is merged into the execution report.

        Never raises — all errors are logged and a safe fallback is returned.
        """
        try:
            lifecycle = ctx.entity_tracker.get_lifecycle_summary()
            passed = sum(1 for r in step_results if getattr(r, "success", False))
            total = len(step_results)
            pass_rate = round(passed / max(total, 1) * 100, 1)

            # Business outcome validation
            unconfirmed: list[str] = []
            if ctx.workflow_type == "CRUD":
                if "create" in ctx.operations and not lifecycle["is_created"]:
                    unconfirmed.append(
                        f"{ctx.primary_entity} creation was not confirmed in the UI"
                    )
                if "delete" in ctx.operations and lifecycle["is_created"] and not lifecycle["is_deleted"]:
                    # Only flag if delete phase was reached (steps existed for it)
                    delete_steps_ran = any(
                        getattr(r, "phase", "") in ("DELETE", "VERIFY_DELETED")
                        for r in step_results
                    )
                    if delete_steps_ran:
                        unconfirmed.append(
                            f"{ctx.primary_entity} deletion was not confirmed in the UI"
                        )

            summary = {
                "intent_orchestrator": True,
                "workflow_type": ctx.workflow_type,
                "primary_entity": ctx.primary_entity,
                "business_context": ctx.business_context,
                "operations_tested": ctx.operations,
                "entity_lifecycle": lifecycle,
                "business_outcomes_confirmed": len(unconfirmed) == 0,
                "unconfirmed_outcomes": unconfirmed,
                "steps_passed": passed,
                "steps_total": total,
                "pass_rate": pass_rate,
                "critical_rules": ctx.critical_rules,
                "risk_areas": ctx.risk_areas,
            }

            if unconfirmed:
                log.warning("IntentOrchestrator: unconfirmed business outcomes",
                    outcomes=unconfirmed, entity=ctx.primary_entity)
            else:
                log.info("IntentOrchestrator: all business outcomes confirmed",
                    entity=ctx.primary_entity, workflow=ctx.workflow_type,
                    lifecycle_created=lifecycle["is_created"],
                    lifecycle_deleted=lifecycle["is_deleted"])

            return summary

        except Exception as e:
            log.warning("IntentOrchestrator.post_execute failed", error=str(e)[:120])
            return {"intent_orchestrator": True, "error": str(e)[:120]}

    # ─── Private helpers ──────────────────────────────────────────────────────

    async def _load_module_context(self, scenario: Scenario) -> tuple[str, str]:
        """Load the module name and URL from the scenario's associated module."""
        try:
            module_id = getattr(scenario, "module_id", None)
            if module_id:
                res = await self.db.execute(
                    select(ApplicationModule)
                    .where(ApplicationModule.id == module_id)
                    .limit(1)
                )
                mod = res.scalar_one_or_none()
                if mod:
                    return (mod.name or ""), (mod.base_url or "")

            # Fallback: attributes set on scenario during enrichment
            name = getattr(scenario, "module_name", "") or ""
            url  = getattr(scenario, "module_url",  "") or ""
            return name, url
        except Exception:
            return "", ""

    def _minimal_context(
        self, scenario: Scenario, plan_data: dict[str, Any]
    ) -> ExecutionContext:
        """Safe minimal context when prepare() fails."""
        wf = plan_data.get("workflow_type", "CRUD")
        title = scenario.title or "Scenario"
        entity = IntentAnalyzer._extract_entity(title, "")
        return ExecutionContext(
            primary_entity=entity,
            entity_plural=entity + "s",
            workflow_type=wf,
            business_context=f"Execute {title}",
            operations=[],
            likely_fields=[],
            critical_rules=[],
            risk_areas=[],
            create_entity_name=f"Test{entity}001",
            update_entity_name=f"Updated{entity}001",
            entity_tracker=EntityTracker(entity_type=entity),
        )
