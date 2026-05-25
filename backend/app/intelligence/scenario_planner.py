"""
Scenario Planning Engine
Converts natural language test scenarios into structured, intelligent execution plans.

Architecture:
  - QAReasoningEngine (primary): AI reasons like a senior QA engineer
    → Classifies workflow type (CRUD, AUTH, ROLE_ACCESS, FORM_VALIDATION, SEARCH, NAVIGATION)
    → Auto-expands CRUD into 8 phases
    → Generates semantic validations + edge cases + checkpoint validations
  - Fallback: deterministic plan when AI is unavailable

AI is called ONCE per scenario — plan is cached and reused on re-runs.
"""
from __future__ import annotations
import json
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    Scenario, ExecutionPlan, Application, ApplicationModule,
    ApplicationPage, SemanticElement,
)
from app.intelligence.ai_client import get_ai_client
from app.intelligence.qa_reasoning_engine import QAReasoningEngine
from config import settings

log = structlog.get_logger()

ALLOWED_ACTIONS = frozenset([
    "navigate", "click", "fill", "clear", "select", "key_press",
    "assert_visible", "assert_text", "assert_not_text", "assert_url", "assert_count",
    "wait_network", "wait_element", "wait_ms",
    "scroll", "upload", "screenshot", "assert_ai_semantic",
])

MODE_CAPS = {
    "smoke":            {"max_steps": 12,  "depth": "minimal — happy path only"},
    "functional":       {"max_steps": 35,  "depth": "standard — key flows + basic validation"},
    "validation_heavy": {"max_steps": 55,  "depth": "thorough — including edge cases"},
    "regression":       {"max_steps": 80,  "depth": "comprehensive — all paths and validations"},
    "workflow_heavy":   {"max_steps": 100, "depth": "exhaustive — full workflow coverage"},
}


class ScenarioPlanner:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.ai = get_ai_client()
        self._qa_engine = QAReasoningEngine(db)

    async def generate_plan(
        self,
        scenario: Scenario,
        execution_mode: str = "functional",
    ) -> ExecutionPlan:
        """
        Generate a comprehensive QA execution plan using the AI reasoning engine.
        The AI classifies the workflow type and generates an intelligent plan
        with phases, validations, edge cases, and checkpoint validations.
        """
        caps = MODE_CAPS.get(execution_mode, MODE_CAPS["functional"])

        try:
            plan_data = await self._qa_engine.build_plan(scenario, execution_mode)
        except Exception as e:
            log.error("QA reasoning engine failed — using fallback",
                error=str(e), scenario_id=scenario.id)
            plan_data = self._fallback_plan(scenario)

        plan_data = self._validate_and_cap(plan_data, caps["max_steps"])

        plan = ExecutionPlan(
            scenario_id=scenario.id,
            execution_mode=execution_mode,
            plan_data=plan_data,
            ai_reasoning=plan_data.get("qa_reasoning", ""),
            semantic_intent=plan_data.get("semantic_intent", {}),
            workflow_stages=self._extract_workflow_stages(plan_data),
            risk_score=self._calculate_risk(plan_data, execution_mode),
            estimated_duration_seconds=len(plan_data.get("steps", [])) * 5,
            created_by_model=settings.PRIMARY_MODEL,
        )

        latest = await self._latest_plan_version(scenario.id)
        if latest:
            plan.version = latest.version + 1

        self.db.add(plan)
        await self.db.commit()

        log.info("Plan generated",
            plan_id=plan.id,
            workflow_type=plan_data.get("workflow_type", "?"),
            steps=len(plan_data.get("steps", [])),
            checkpoints=len(plan_data.get("checkpoint_validations", [])),
        )
        return plan

    async def generate_fallback_plan(
        self, scenario: Scenario, execution_mode: str = "functional"
    ) -> ExecutionPlan:
        """Fast plan generation — no AI call. Used for batch queuing."""
        plan_data = self._fallback_plan(scenario)
        caps = MODE_CAPS.get(execution_mode, MODE_CAPS["functional"])
        plan_data = self._validate_and_cap(plan_data, caps["max_steps"])

        plan = ExecutionPlan(
            scenario_id=scenario.id,
            execution_mode=execution_mode,
            plan_data=plan_data,
            ai_reasoning="Fallback plan — AI reasoning deferred to execution time",
            semantic_intent={},
            workflow_stages=[],
            risk_score=5,
            estimated_duration_seconds=len(plan_data.get("steps", [])) * 5,
            created_by_model="fallback",
        )
        latest = await self._latest_plan_version(scenario.id)
        if latest:
            plan.version = latest.version + 1

        self.db.add(plan)
        await self.db.commit()
        return plan

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _validate_and_cap(self, plan_data: dict, max_steps: int) -> dict:
        """Sanitize steps: filter invalid actions, cap count, ensure screenshots."""
        steps = [
            s for s in plan_data.get("steps", [])
            if s.get("action") in ALLOWED_ACTIONS
        ]
        steps = steps[:max_steps]

        for step in steps:
            step.setdefault("timeout_ms", 10000)
            step.setdefault("on_fail", "fail")
            step.setdefault("checkpoint", False)
            step.setdefault("business_intent", "")
            step.setdefault("phase", "")
            if step.get("action") == "screenshot":
                step["on_fail"] = "skip"
            if "description" not in step:
                step["description"] = f"{step.get('action', 'step').title()}"

        # Guarantee first + last screenshots
        if steps and steps[0].get("action") != "screenshot":
            steps.insert(0, {
                "action": "screenshot", "description": "Capture initial page state",
                "timeout_ms": 5000, "on_fail": "skip", "checkpoint": False,
                "business_intent": "Baseline evidence", "phase": "SETUP",
            })
        if steps and steps[-1].get("action") != "screenshot":
            steps.append({
                "action": "screenshot", "description": "Capture final page state as evidence",
                "timeout_ms": 5000, "on_fail": "skip", "checkpoint": False,
                "business_intent": "Final evidence", "phase": "TEARDOWN",
            })

        plan_data["steps"] = steps
        plan_data.setdefault("checkpoint_validations", [])
        plan_data.setdefault("qa_reasoning", "")
        plan_data.setdefault("test_strategy", {})
        plan_data.setdefault("workflow_type", "BUSINESS_WORKFLOW")
        return plan_data

    def _extract_workflow_stages(self, plan_data: dict) -> list[dict]:
        """Extract unique phases from steps as workflow stages."""
        phases_seen: list[str] = []
        for step in plan_data.get("steps", []):
            phase = step.get("phase", "")
            if phase and phase not in phases_seen:
                phases_seen.append(phase)

        return [
            {"stage": i + 1, "name": phase, "description": phase.replace("_", " ").title()}
            for i, phase in enumerate(phases_seen)
        ]

    def _calculate_risk(self, plan_data: dict, mode: str) -> float:
        base = {"smoke": 10, "functional": 25, "validation_heavy": 45,
                "regression": 65, "workflow_heavy": 80}.get(mode, 25)
        step_count = len(plan_data.get("steps", []))
        assert_count = sum(1 for s in plan_data.get("steps", [])
                          if "assert" in s.get("action", ""))
        checkpoint_count = len(plan_data.get("checkpoint_validations", []))
        return min(100.0, base + (step_count * 0.4) + (checkpoint_count * 5) - (assert_count * 2))

    async def _latest_plan_version(self, scenario_id: str) -> ExecutionPlan | None:
        result = await self.db.execute(
            select(ExecutionPlan)
            .where(ExecutionPlan.scenario_id == scenario_id)
            .order_by(ExecutionPlan.version.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    def _fallback_plan(self, scenario: Scenario) -> dict:
        return {
            "workflow": "BASIC_NAVIGATE",
            "workflow_type": "NAVIGATION",
            "goal": f"Verify {scenario.title} works as expected",
            "qa_reasoning": "Fallback plan — AI reasoning unavailable or deferred.",
            "test_strategy": {
                "phases": ["NAVIGATE", "VERIFY_LOADED"],
                "primary_operation": "navigate",
                "validations": ["Page loads without errors"],
                "negative_tests": [],
                "edge_cases": [],
            },
            "steps": [
                {"action": "screenshot", "description": "Capture initial state",
                 "timeout_ms": 5000, "on_fail": "skip", "checkpoint": False,
                 "business_intent": "Initial evidence", "phase": "SETUP"},
                {"action": "navigate", "description": "Open application", "url": "/",
                 "timeout_ms": 15000, "on_fail": "fail", "checkpoint": False,
                 "business_intent": "Navigate to application", "phase": "NAVIGATE"},
                {"action": "assert_visible", "description": "Verify page loaded",
                 "target": "page content", "text": "", "timeout_ms": 10000, "on_fail": "fail",
                 "checkpoint": True, "business_intent": "Application is accessible",
                 "phase": "VERIFY_LOADED"},
                {"action": "screenshot", "description": "Capture final state",
                 "timeout_ms": 5000, "on_fail": "skip", "checkpoint": False,
                 "business_intent": "Final evidence", "phase": "TEARDOWN"},
            ],
            "checkpoint_validations": [],
            "success_criteria": ["Application loads and is accessible"],
            "failure_indicators": ["Application fails to load"],
            "semantic_intent": {
                "module": "",
                "operation": "navigate",
                "pass_criteria": "Application is accessible",
                "fail_criteria": "Application does not load",
            },
        }
