"""
Business Rule Discovery Engine.

Infers hidden business rules from the application knowledge graph:
  - Field validation constraints  → "Price must be > 0"
  - Workflow preconditions        → "Location must be selected before creating a Sample"
  - Workflow error paths          → "Duplicate barcode is rejected"
  - Domain patterns               → "End date cannot be before start date"

For each discovered rule, generates:
  - A positive test (rule is enforced correctly)
  - A negative test (violation is rejected with correct error)
"""
from __future__ import annotations
import asyncio
import json

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    ApplicationModule, ApplicationPage, ApplicationWorkflow,
    KnowledgeGraph, Scenario, ScenarioPriority,
)
from app.intelligence.ai_client import AIClient

log = structlog.get_logger()

_SYSTEM = """You are a senior QA engineer inferring business rules from application structure.

Analyze the provided forms, field validations, workflow preconditions, and error paths.
Infer all business rules — both explicit (stated in validation) and implicit (inferred from domain).

For each rule generate exactly:
- A positive test: verifies the rule is enforced when violated correctly
- A negative test: verifies the happy path passes with valid data

Output ONLY valid JSON:
{
  "rules": [
    {
      "id": "RULE_001",
      "name": "Descriptive rule name",
      "category": "data_validation|business_logic|access_control|data_integrity|workflow_constraint|uniqueness",
      "description": "Price must be greater than zero",
      "entity": "Product",
      "field": "Price (or null if entity-level)",
      "inferred_from": "form field validation: min > 0 | workflow precondition | error_path",
      "confidence": "HIGH|MEDIUM|LOW",
      "positive_test": {
        "title": "Reject negative product price",
        "description": "1. Navigate to Add Product\\n2. Enter Price = -1\\n3. Submit\\n4. Verify validation error shown",
        "priority": "HIGH",
        "test_data": {"Price": "-1"}
      },
      "negative_test": {
        "title": "Accept valid positive product price",
        "description": "1. Navigate to Add Product\\n2. Enter Price = 10.00\\n3. Submit\\n4. Verify product saved",
        "priority": "MEDIUM",
        "test_data": {"Price": "10.00"}
      }
    }
  ]
}

Infer aggressively — if a field is marked required, that is a rule. If a workflow has preconditions, those are rules.
Aim for 15–30 rules covering all forms and workflows provided."""


class BusinessRuleEngine:
    """
    Discovers business rules from the application knowledge graph and generates
    positive + negative test scenarios for each rule.
    """

    def __init__(self, db: AsyncSession, ai: AIClient):
        self.db = db
        self.ai = ai

    async def discover_rules(self, application_id: str) -> list[dict]:
        """Infer business rules from the knowledge graph. Returns raw rule dicts."""
        context = await self._build_context(application_id)
        return await self._ai_discover(context)

    async def generate_scenarios(
        self,
        application_id: str,
        user_id: str,
        rules: list[dict] | None = None,
    ) -> tuple[list[dict], list[Scenario]]:
        """
        Discover rules and persist test scenarios.
        Returns (rules_list, created_scenarios).
        """
        if rules is None:
            rules = await self.discover_rules(application_id)

        priority_map = {
            "CRITICAL": ScenarioPriority.CRITICAL,
            "HIGH": ScenarioPriority.HIGH,
            "MEDIUM": ScenarioPriority.MEDIUM,
            "LOW": ScenarioPriority.LOW,
        }
        created: list[Scenario] = []

        for rule in rules:
            entity = rule.get("entity", "")
            module_id = await self._find_module(application_id, entity)
            rule_desc = rule.get("description", "")
            rule_id = rule.get("id", "")
            category = rule.get("category", "business_rule")

            for test_key in ("positive_test", "negative_test"):
                t = rule.get(test_key)
                if not t or not t.get("title"):
                    continue

                desc = t.get("description", "")
                if rule_desc:
                    desc += f"\n\nBusiness Rule [{rule_id}]: {rule_desc}"
                if t.get("test_data"):
                    desc += f"\n\nTest Data:\n{json.dumps(t['test_data'], indent=2)}"

                test_category = "positive" if test_key == "positive_test" else "negative"
                tags = ["business_rule", test_category, category]
                if entity:
                    tags.append(entity.lower().replace(" ", "_"))

                scenario = Scenario(
                    application_id=application_id,
                    title=t["title"][:512],
                    description=desc,
                    priority=priority_map.get(
                        (t.get("priority") or "MEDIUM").upper(),
                        ScenarioPriority.MEDIUM,
                    ),
                    tags=tags,
                    module_id=module_id,
                    source="ai_generated",
                    created_by=user_id,
                )
                self.db.add(scenario)
                created.append(scenario)

        if created:
            await self.db.commit()
            for s in created:
                await self.db.refresh(s)

        log.info("Business rule scenarios generated",
            rules=len(rules), scenarios=len(created), application_id=application_id)
        return rules, created

    # ── Context builder ───────────────────────────────────────────────────────

    async def _build_context(self, application_id: str) -> dict:
        """Compile everything needed for rule inference."""
        kg_result = await self.db.execute(
            select(KnowledgeGraph)
            .where(KnowledgeGraph.application_id == application_id)
            .order_by(KnowledgeGraph.version.desc())
            .limit(1)
        )
        kg = kg_result.scalar_one_or_none()
        graph_data = kg.graph_data if kg else {}

        pages_result = await self.db.execute(
            select(ApplicationPage)
            .join(ApplicationModule, ApplicationPage.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == application_id)
            .limit(50)
        )
        pages = list(pages_result.scalars().all())

        wf_result = await self.db.execute(
            select(ApplicationWorkflow)
            .join(ApplicationModule, ApplicationWorkflow.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == application_id)
            .limit(50)
        )
        workflows = list(wf_result.scalars().all())

        # Aggregate field constraints across all forms
        field_constraints: list[dict] = []
        for p in pages:
            for f in (p.forms or []):
                for fld in (f.get("fields") or []):
                    if fld.get("required") or fld.get("validation") or fld.get("depends_on"):
                        field_constraints.append({
                            "form": f.get("name", ""),
                            "entity": f.get("entity", ""),
                            "submit_action": f.get("submit_action", ""),
                            "field": fld.get("label", ""),
                            "type": fld.get("type", "text"),
                            "required": fld.get("required", False),
                            "validation": fld.get("validation", ""),
                            "options": fld.get("options", [])[:6],
                            "depends_on": fld.get("depends_on"),
                        })

        # Workflow constraints (preconditions + error paths from success_indicators)
        workflow_constraints: list[dict] = []
        for wf in workflows:
            ep = wf.entry_point or {}
            if ep.get("preconditions") or wf.success_indicators:
                workflow_constraints.append({
                    "workflow": wf.name,
                    "entity": ep.get("entity", ""),
                    "type": wf.workflow_type,
                    "preconditions": ep.get("preconditions", []),
                    "success_criteria": wf.success_indicators or [],
                    "entry_trigger": ep.get("trigger", ""),
                })

        # CRUD coverage tells us which entities support which operations
        crud_coverage = graph_data.get("summary", {}).get("crud_coverage", {})
        business_objects = graph_data.get("summary", {}).get("business_objects", [])

        return {
            "business_objects": business_objects,
            "crud_coverage": crud_coverage,
            "field_constraints": field_constraints[:80],
            "workflow_constraints": workflow_constraints[:30],
        }

    # ── AI call ───────────────────────────────────────────────────────────────

    async def _ai_discover(self, context: dict) -> list[dict]:
        user_msg = (
            f"APPLICATION KNOWLEDGE:\n{json.dumps(context, indent=1)}\n\n"
            "Infer ALL business rules from the field constraints, preconditions, "
            "validation rules, and domain patterns. Generate both a positive and "
            "negative test per rule. Cover required fields, format constraints, "
            "range constraints, uniqueness, preconditions, and business logic."
        )
        try:
            response = await asyncio.wait_for(
                self.ai.complete(
                    system=_SYSTEM,
                    user=user_msg,
                    json_mode=True,
                    max_tokens=5000,
                ),
                timeout=90.0,
            )
            data = response.json()
            return data.get("rules", [])
        except Exception as e:
            log.warning("Business rule discovery failed", error=str(e))
            return []

    async def _find_module(self, application_id: str, entity: str) -> str | None:
        result = await self.db.execute(
            select(ApplicationModule).where(ApplicationModule.application_id == application_id)
        )
        modules = list(result.scalars().all())
        if not modules:
            return None
        if entity:
            ent_lower = entity.lower()
            for m in modules:
                if ent_lower in m.name.lower():
                    return m.id
        return modules[0].id
