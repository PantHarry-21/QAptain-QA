"""
Smart Test Generation Engine.

Generates comprehensive test suites (happy path, edge cases, negative, regression)
from multiple input artifact types:

  user_story       → acceptance criteria → test cases per criterion
  requirement      → extract testable requirements → test suite per requirement
  screenshot       → analyze visible UI → tests for all interactive elements
  workflow         → workflow stages + error paths → tests per stage + path
  production_logs  → error patterns + failures → regression tests per pattern
"""
from __future__ import annotations
import asyncio
import json
from typing import Literal

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    ApplicationModule, ApplicationWorkflow,
    KnowledgeGraph, Scenario, ScenarioPriority,
)
from app.intelligence.ai_client import AIClient

log = structlog.get_logger()

SourceType = Literal[
    "user_story", "requirement", "screenshot", "workflow", "production_logs"
]

_SYSTEM = """You are a senior QA engineer converting artifacts into comprehensive test scenarios.

Given the input artifact (user story, requirement doc, screenshot description, workflow, or production logs),
generate a complete test suite covering:
  1. happy_path  — golden path that should succeed end-to-end
  2. edge_case   — boundary conditions, unusual but valid inputs
  3. negative    — invalid inputs, constraint violations, error conditions
  4. regression  — things most likely to break if this feature changes

Output ONLY valid JSON:
{
  "source_summary": "One sentence describing what was analyzed",
  "entity": "Primary entity under test (e.g. Product, User, Order)",
  "module": "Best matching application module name",
  "scenarios": [
    {
      "title": "Imperative title under 80 chars",
      "description": "Numbered steps:\\n1. Navigate to...\\n2. Enter...\\n3. Verify...",
      "category": "happy_path|edge_case|negative|regression",
      "priority": "CRITICAL|HIGH|MEDIUM|LOW",
      "tags": ["smart_gen", "source_type", "category"],
      "preconditions": ["Pre-condition 1", "Pre-condition 2"],
      "test_data": {"Field Label": "value to enter"}
    }
  ]
}

Aim for: 3-5 happy_path, 3-5 edge_case, 4-6 negative, 3-5 regression = 13-21 total scenarios.
Be specific — use actual field names, actual error messages, actual business entity names."""


class SmartScenarioGenerator:
    """
    Converts multiple artifact types into test suites.
    All generated scenarios are persisted to the Scenario table.
    """

    def __init__(self, db: AsyncSession, ai: AIClient):
        self.db = db
        self.ai = ai

    async def generate(
        self,
        source_type: SourceType,
        content: str,
        application_id: str,
        user_id: str,
        image_bytes: bytes | None = None,
    ) -> list[Scenario]:
        """
        source_type: which artifact is being converted
        content:     text content, or workflow name/id for the "workflow" source
        image_bytes: PNG/JPG bytes when source_type = "screenshot"
        Returns persisted Scenario records.
        """
        app_ctx = await self._get_app_context(application_id)

        if source_type == "user_story":
            prompt = self._prep_user_story(content, app_ctx)
        elif source_type == "requirement":
            prompt = self._prep_requirement(content, app_ctx)
        elif source_type == "screenshot":
            prompt = self._prep_screenshot(content, image_bytes, app_ctx)
        elif source_type == "workflow":
            prompt = await self._prep_workflow(content, application_id, app_ctx)
        elif source_type == "production_logs":
            prompt = self._prep_logs(content, app_ctx)
        else:
            raise ValueError(f"Unknown source_type: {source_type!r}")

        raw = await self._ai_generate(source_type, prompt)
        return await self._persist(raw, application_id, user_id, source_type)

    # ── Source-specific input builders ────────────────────────────────────────

    def _prep_user_story(self, story: str, app_ctx: dict) -> str:
        return (
            f"USER STORY:\n{story}\n\n"
            f"APPLICATION CONTEXT:\n{json.dumps(app_ctx, indent=1)}\n\n"
            "Extract each acceptance criterion and generate test cases covering it. "
            "Include at least 2 negative cases (what the story says must NOT happen). "
            "Include edge cases for any mentioned data inputs or conditions."
        )

    def _prep_requirement(self, doc: str, app_ctx: dict) -> str:
        doc_trimmed = doc[:6000]
        return (
            f"REQUIREMENT DOCUMENT:\n{doc_trimmed}\n\n"
            f"APPLICATION CONTEXT:\n{json.dumps(app_ctx, indent=1)}\n\n"
            "Parse each requirement statement and generate test cases. "
            "Map each requirement to: one happy path, one edge case, one negative test. "
            "Add regression tests for the highest-risk requirements."
        )

    def _prep_screenshot(
        self, description: str, image_bytes: bytes | None, app_ctx: dict
    ) -> str:
        image_note = "[Screenshot image provided — analyze all visible UI elements]" if image_bytes else ""
        return (
            f"SCREENSHOT / UI DESCRIPTION:\n{description}\n{image_note}\n\n"
            f"APPLICATION CONTEXT:\n{json.dumps(app_ctx, indent=1)}\n\n"
            "Identify all interactive elements visible (buttons, fields, dropdowns, links). "
            "Generate tests for: each field (valid + invalid input), each button/action, "
            "each visible state (empty list, populated list, error state, loading state)."
        )

    async def _prep_workflow(
        self, workflow_id_or_name: str, application_id: str, app_ctx: dict
    ) -> str:
        # Resolve workflow from DB
        wf_result = await self.db.execute(
            select(ApplicationWorkflow)
            .join(ApplicationModule, ApplicationWorkflow.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == application_id)
        )
        workflows = list(wf_result.scalars().all())
        target_lower = workflow_id_or_name.lower()
        matched = next(
            (wf for wf in workflows
             if wf.id == workflow_id_or_name or target_lower in (wf.name or "").lower()),
            None,
        )

        if matched:
            ep = matched.entry_point or {}
            wf_ctx = {
                "name": matched.name,
                "type": matched.workflow_type,
                "entity": ep.get("entity", ""),
                "entry_trigger": ep.get("trigger", ""),
                "preconditions": ep.get("preconditions", []),
                "stages": matched.stages or [],
                "success_criteria": matched.success_indicators or [],
            }
        else:
            wf_ctx = {"name": workflow_id_or_name, "stages": []}

        return (
            f"EXISTING WORKFLOW:\n{json.dumps(wf_ctx, indent=1)}\n\n"
            f"APPLICATION CONTEXT:\n{json.dumps(app_ctx, indent=1)}\n\n"
            "Generate tests covering:\n"
            "1. Happy path: each workflow stage succeeds in order\n"
            "2. Edge cases: unusual but valid inputs at each stage\n"
            "3. Precondition violations: what happens if each precondition is not met\n"
            "4. Regression: tests that would catch regressions in the most critical stages"
        )

    def _prep_logs(self, logs: str, app_ctx: dict) -> str:
        logs_trimmed = logs[:5000]
        return (
            f"PRODUCTION LOGS:\n{logs_trimmed}\n\n"
            f"APPLICATION CONTEXT:\n{json.dumps(app_ctx, indent=1)}\n\n"
            "Analyze the logs for: errors, exceptions, slow operations, auth failures, "
            "validation failures, and repeated error patterns. "
            "Generate regression tests for each distinct issue pattern. "
            "Prioritize by: frequency (more occurrences = higher priority), "
            "then severity (500 errors > 400 errors > slow responses)."
        )

    # ── AI call ───────────────────────────────────────────────────────────────

    async def _ai_generate(self, source_type: str, user_prompt: str) -> dict:
        system = _SYSTEM + f"\n\nSource type being processed: {source_type}"
        try:
            response = await asyncio.wait_for(
                self.ai.complete(
                    system=system,
                    user=user_prompt,
                    json_mode=True,
                    max_tokens=5000,
                ),
                timeout=120.0,
            )
            return response.json()
        except Exception as e:
            log.warning("Smart generation AI call failed", source_type=source_type, error=str(e))
            return {"scenarios": []}

    # ── Persistence ───────────────────────────────────────────────────────────

    async def _persist(
        self,
        raw: dict,
        application_id: str,
        user_id: str,
        source_type: str,
    ) -> list[Scenario]:
        priority_map = {
            "CRITICAL": ScenarioPriority.CRITICAL,
            "HIGH": ScenarioPriority.HIGH,
            "MEDIUM": ScenarioPriority.MEDIUM,
            "LOW": ScenarioPriority.LOW,
        }
        module_id = await self._find_module(
            application_id, raw.get("module", ""), raw.get("entity", "")
        )
        created: list[Scenario] = []

        for s in raw.get("scenarios", [])[:200]:
            title = (s.get("title") or "").strip()
            if not title:
                continue

            desc = s.get("description", "")
            if s.get("preconditions"):
                preconds = "\n".join(f"- {p}" for p in s["preconditions"])
                desc = f"Preconditions:\n{preconds}\n\n{desc}"
            if s.get("test_data"):
                desc += f"\n\nTest Data:\n{json.dumps(s['test_data'], indent=2)}"

            tags: list[str] = list(s.get("tags", [])) or []
            for required in ("smart_gen", source_type, s.get("category", "")):
                if required and required not in tags:
                    tags.append(required)

            scenario = Scenario(
                application_id=application_id,
                title=title[:512],
                description=desc,
                priority=priority_map.get(
                    (s.get("priority") or "MEDIUM").upper(),
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

        log.info("Smart scenarios persisted",
            source=source_type, count=len(created), application_id=application_id)
        return created

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _get_app_context(self, application_id: str) -> dict:
        kg_result = await self.db.execute(
            select(KnowledgeGraph)
            .where(KnowledgeGraph.application_id == application_id)
            .order_by(KnowledgeGraph.version.desc())
            .limit(1)
        )
        kg = kg_result.scalar_one_or_none()
        summary = (kg.graph_data or {}).get("summary", {}) if kg else {}
        return {
            "business_objects": summary.get("business_objects", []),
            "modules": summary.get("module_names", []),
            "workflows_count": summary.get("workflows_count", 0),
            "crud_coverage": summary.get("crud_coverage", {}),
            "forms_total": summary.get("forms_total", 0),
        }

    async def _find_module(
        self, application_id: str, module_name: str, entity: str
    ) -> str | None:
        result = await self.db.execute(
            select(ApplicationModule).where(ApplicationModule.application_id == application_id)
        )
        modules = list(result.scalars().all())
        if not modules:
            return None
        for candidate in (module_name, entity):
            if not candidate:
                continue
            c_lower = candidate.lower()
            for m in modules:
                if c_lower in m.name.lower() or m.name.lower() in c_lower:
                    return m.id
        return modules[0].id
