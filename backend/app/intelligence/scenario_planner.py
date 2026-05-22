"""
Scenario Planning Engine
Converts natural language test scenarios into structured execution plans.
AI plans ONCE — Selenium executes deterministically.
"""
from __future__ import annotations
import json
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    Scenario, ExecutionPlan, Application, ApplicationModule,
    ApplicationPage, ApplicationWorkflow, AIMemoryChunk, MemoryKind,
)
from app.intelligence.ai_client import get_ai_client
from config import settings

log = structlog.get_logger()

# Allowed plan step actions — keeps Selenium execution deterministic
ALLOWED_ACTIONS = [
    "navigate",       # Go to URL/path
    "click",          # Click an element (semantic label based)
    "fill",           # Fill a form field
    "select",         # Select dropdown option
    "assert_visible", # Assert text/element is visible
    "assert_text",    # Assert specific text content
    "assert_url",     # Assert URL contains pattern
    "wait_network",   # Wait for network request
    "wait_element",   # Wait for element to appear
    "wait_ms",        # Fixed wait
    "scroll",         # Scroll to element/position
    "upload",         # File upload
    "screenshot",     # Capture evidence
]

# Mode caps: limits AI verbosity based on test depth needed
MODE_CAPS = {
    "smoke":            {"max_steps": 8,  "max_cases": 1, "depth": "minimal"},
    "functional":       {"max_steps": 20, "max_cases": 3, "depth": "standard"},
    "validation_heavy": {"max_steps": 40, "max_cases": 5, "depth": "thorough"},
    "regression":       {"max_steps": 60, "max_cases": 8, "depth": "comprehensive"},
    "workflow_heavy":   {"max_steps": 80, "max_cases": 10, "depth": "exhaustive"},
}

SYSTEM_PROMPT = """You are QAptain's Scenario Planning Engine — a Principal QA Architect.

Your role: convert a natural language test scenario into a STRUCTURED EXECUTION PLAN.

CRITICAL RULES:
1. Output ONLY valid JSON — no markdown, no explanation outside JSON
2. Use semantic labels for all elements (e.g., "Username input field", not CSS selectors)
3. Keep steps business-focused and human-readable
4. AI plans ONCE — execution is deterministic from your plan
5. Include verification steps (assert) after key actions
6. Handle dynamic UI: if a workflow has stages (e.g., login → location selection → dashboard), capture all stages

PLAN STRUCTURE:
{
  "workflow": "WORKFLOW_NAME",
  "semantic_intent": {
    "module": "module name",
    "operation": "create|read|update|delete|search|approve|verify",
    "business_context": "what this test verifies"
  },
  "workflow_stages": [
    {"stage": 1, "name": "Stage name", "description": "What happens at this stage"}
  ],
  "steps": [
    {
      "action": "navigate|click|fill|select|assert_visible|assert_text|assert_url|wait_network|wait_element|wait_ms|scroll|screenshot",
      "description": "Human-readable description of this step",
      "target": "semantic label of target element",
      "value": "value to fill/select",
      "url": "URL to navigate to",
      "text": "text to assert",
      "timeout_ms": 10000,
      "on_fail": "skip|retry|fail"
    }
  ],
  "success_criteria": ["What a successful run looks like"],
  "ai_reasoning": "Why you designed the plan this way"
}

IMPORTANT PATTERNS:
- Login workflows: navigate → fill username → fill password → click login → handle dynamic stages
- CRUD Create: navigate to module → click new/add → fill form fields → submit → assert success
- CRUD Read: navigate → search/filter → assert record visible
- CRUD Update: find record → click edit → modify fields → save → assert updated
- Approval: find pending item → click approve/reject → confirm → assert status changed
- Always add screenshot step after key workflow stages"""


class ScenarioPlanner:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.ai = get_ai_client()

    async def generate_plan(
        self,
        scenario: Scenario,
        execution_mode: str = "functional",
    ) -> ExecutionPlan:
        caps = MODE_CAPS.get(execution_mode, MODE_CAPS["functional"])

        # Gather context from application knowledge
        context = await self._build_scenario_context(scenario)

        user_prompt = f"""
SCENARIO TO PLAN:
Title: {scenario.title}
Description: {scenario.description or "No additional description"}
Priority: {scenario.priority.value if scenario.priority else "MEDIUM"}
Execution Mode: {execution_mode} (max_steps: {caps['max_steps']}, depth: {caps['depth']})

APPLICATION CONTEXT:
Base URL: {context['base_url']}
Description: {context['app_description']}

RELEVANT MODULES:
{json.dumps(context['modules'], indent=2)}

KNOWN WORKFLOWS:
{json.dumps(context['workflows'], indent=2)}

KNOWN PAGES & FORMS:
{json.dumps(context['pages'], indent=2)}

MEMORY HINTS:
{context['memory_hints']}

REQUIREMENTS:
- Maximum {caps['max_steps']} steps total
- Cover {caps['depth']} testing depth
- Include at least 2 assert steps to validate outcomes
- Use semantic element labels from the application context
- Handle all workflow stages (including dynamic UI transitions like location selection)
"""

        log.info("Generating execution plan", scenario_id=scenario.id, mode=execution_mode)

        response = await self.ai.complete(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            json_mode=True,
            max_tokens=4000,
            temperature=0.05,
        )

        try:
            plan_data = response.json()
        except Exception as e:
            log.error("Failed to parse AI plan", error=str(e), content=response.content[:500])
            plan_data = self._fallback_plan(scenario)

        # Validate and cap steps
        plan_data = self._validate_and_cap(plan_data, caps["max_steps"])

        # Persist plan
        plan = ExecutionPlan(
            scenario_id=scenario.id,
            execution_mode=execution_mode,
            plan_data=plan_data,
            ai_reasoning=plan_data.get("ai_reasoning", ""),
            semantic_intent=plan_data.get("semantic_intent", {}),
            workflow_stages=plan_data.get("workflow_stages", []),
            risk_score=self._calculate_risk(plan_data, execution_mode),
            estimated_duration_seconds=len(plan_data.get("steps", [])) * 3,
            created_by_model=settings.PRIMARY_MODEL,
        )

        # Version bump if existing plan exists
        existing = await self.db.execute(
            select(ExecutionPlan)
            .where(ExecutionPlan.scenario_id == scenario.id)
            .order_by(ExecutionPlan.version.desc())
        )
        latest = existing.scalar_one_or_none()
        if latest:
            plan.version = latest.version + 1

        self.db.add(plan)
        await self.db.commit()

        log.info("Plan generated", plan_id=plan.id, steps=len(plan_data.get("steps", [])))
        return plan

    async def _build_scenario_context(self, scenario: Scenario) -> dict:
        """Build rich context from application knowledge for the AI."""
        # Load application
        app_result = await self.db.execute(
            select(Application).where(Application.id == scenario.application_id)
        )
        app = app_result.scalar_one_or_none()

        # Load modules
        modules_result = await self.db.execute(
            select(ApplicationModule).where(ApplicationModule.application_id == scenario.application_id)
        )
        modules = modules_result.scalars().all()

        # Load relevant pages (limit to avoid token bloat)
        pages_result = await self.db.execute(
            select(ApplicationPage)
            .join(ApplicationModule, ApplicationPage.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == scenario.application_id)
            .limit(10)
        )
        pages = pages_result.scalars().all()

        # Load workflows
        workflows_result = await self.db.execute(
            select(ApplicationWorkflow)
            .join(ApplicationModule, ApplicationWorkflow.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == scenario.application_id)
            .limit(15)
        )
        workflows = workflows_result.scalars().all()

        # Load memory hints
        memory_result = await self.db.execute(
            select(AIMemoryChunk)
            .where(
                AIMemoryChunk.application_id == scenario.application_id,
                AIMemoryChunk.kind.in_([MemoryKind.MODULE, MemoryKind.WORKFLOW, MemoryKind.FIELD]),
            )
            .order_by(AIMemoryChunk.confidence.desc())
            .limit(5)
        )
        memory_chunks = memory_result.scalars().all()

        return {
            "base_url": app.base_url if app else "",
            "app_description": app.description if app else "",
            "modules": [
                {
                    "name": m.name,
                    "description": m.description,
                    "url_pattern": m.url_pattern,
                    "tags": m.semantic_tags or [],
                }
                for m in modules[:10]
            ],
            "pages": [
                {
                    "title": p.title,
                    "url": p.url,
                    "page_type": p.page_type,
                    "forms": p.forms or [],
                }
                for p in pages
            ],
            "workflows": [
                {
                    "name": w.name,
                    "type": w.workflow_type,
                    "stages": w.stages or [],
                }
                for w in workflows
            ],
            "memory_hints": "\n".join(c.content for c in memory_chunks) or "No prior knowledge available.",
        }

    def _validate_and_cap(self, plan_data: dict, max_steps: int) -> dict:
        """Ensure plan is valid and within step limits."""
        if "steps" not in plan_data:
            plan_data["steps"] = []

        # Filter to allowed actions only
        valid_steps = [
            s for s in plan_data["steps"]
            if s.get("action") in ALLOWED_ACTIONS
        ]

        # Cap steps
        plan_data["steps"] = valid_steps[:max_steps]

        # Ensure required fields
        for step in plan_data["steps"]:
            step.setdefault("timeout_ms", 10000)
            step.setdefault("on_fail", "fail")
            if "description" not in step:
                step["description"] = f"{step.get('action', 'action').title()} step"

        return plan_data

    def _calculate_risk(self, plan_data: dict, mode: str) -> float:
        """Calculate a risk score for this execution plan."""
        base = {"smoke": 10, "functional": 25, "validation_heavy": 45,
                "regression": 65, "workflow_heavy": 80}.get(mode, 25)
        step_count = len(plan_data.get("steps", []))
        assert_count = sum(1 for s in plan_data.get("steps", []) if "assert" in s.get("action", ""))
        stages = len(plan_data.get("workflow_stages", []))
        return min(100.0, base + (step_count * 0.5) + (stages * 5) - (assert_count * 2))

    def _fallback_plan(self, scenario: Scenario) -> dict:
        """Minimal fallback plan when AI parsing fails."""
        return {
            "workflow": "FALLBACK",
            "semantic_intent": {"operation": "verify", "business_context": scenario.title},
            "workflow_stages": [{"stage": 1, "name": "Navigate", "description": "Navigate to application"}],
            "steps": [
                {"action": "navigate", "description": "Open application", "url": "/", "timeout_ms": 15000, "on_fail": "fail"},
                {"action": "screenshot", "description": "Capture initial state", "timeout_ms": 5000, "on_fail": "skip"},
            ],
            "success_criteria": ["Application loads successfully"],
            "ai_reasoning": "Fallback plan — AI parsing failed",
        }
