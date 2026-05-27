"""
Exploratory Testing Engine — Thinks like a human QA engineer.

Given "Test Add Product", automatically generates exploratory tests across
6 mandatory categories: empty form, invalid values, boundary values,
duplicate data, unauthorized access, and max length.

This produces the kind of tests a thorough QA engineer would write on their
first day exploring a feature — not just the happy path.
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

_SYSTEM = """You are a senior QA engineer performing exploratory testing on a new feature.

Given a test target (e.g. "Test Add Product") and the application's known forms/workflows,
generate comprehensive exploratory tests that a thorough human QA engineer would run.

You MUST cover ALL 6 categories:
1. empty_form      — Submit with no data, partial data, only required fields
2. invalid_values  — Wrong types, invalid formats, SQL injection, XSS, special chars
3. boundary_values — Min-1, min, max, max+1 for numeric/text/date fields
4. duplicate_data  — Resubmit identical record, duplicate unique field (e.g. email, code)
5. unauthorized_access — No login, wrong role, access another user's records
6. max_length      — Exceed field character limits, very long strings, unicode/emoji

Output ONLY valid JSON:
{
  "target_summary": "What feature/form is being tested",
  "entity": "Primary entity (e.g. Product, User, Sample)",
  "operation": "crud_create|crud_update|crud_delete|login|search|upload",
  "scenarios": [
    {
      "title": "Imperative title under 80 chars",
      "description": "Numbered steps: 1. Do X\\n2. Enter Y\\n3. Verify Z",
      "category": "empty_form|invalid_values|boundary_values|duplicate_data|unauthorized_access|max_length",
      "priority": "HIGH|MEDIUM|LOW",
      "tags": ["exploratory", "negative", "category_name"],
      "expected_behavior": "What should happen — error message shown, field highlighted, record rejected",
      "test_data": {"Field Label": "test value to enter"}
    }
  ]
}

Aim for 3–4 scenarios per category (18–24 total). Be specific — use actual field names from the form context."""


class ExploratoryTestEngine:
    """
    Generates exploratory test suites from a natural language test target.
    Covers 6 mandatory categories that mirror how a human QA engineer thinks.
    """

    def __init__(self, db: AsyncSession, ai: AIClient):
        self.db = db
        self.ai = ai

    async def generate(
        self,
        target: str,
        application_id: str,
        user_id: str,
    ) -> list[Scenario]:
        """
        target: natural language e.g. "Test Add Product" or "Exploratory test Login"
        Returns persisted Scenario records ready for planning + execution.
        """
        context = await self._build_context(target, application_id)
        raw = await self._ai_generate(target, context)
        return await self._persist(raw, application_id, user_id)

    # ── Context builder ───────────────────────────────────────────────────────

    async def _build_context(self, target: str, application_id: str) -> dict:
        """Find relevant forms/workflows in the knowledge graph for the target."""
        keywords = {
            w for w in target.lower().split()
            if w not in {"test", "the", "a", "an", "for", "to", "of", "in", "on"}
        }

        # Load knowledge graph summary
        kg_result = await self.db.execute(
            select(KnowledgeGraph)
            .where(KnowledgeGraph.application_id == application_id)
            .order_by(KnowledgeGraph.version.desc())
            .limit(1)
        )
        kg = kg_result.scalar_one_or_none()
        kg_summary = (kg.graph_data or {}).get("summary", {}) if kg else {}

        # Find relevant pages by keyword match on title/URL
        pages_result = await self.db.execute(
            select(ApplicationPage)
            .join(ApplicationModule, ApplicationPage.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == application_id)
        )
        pages = list(pages_result.scalars().all())

        def page_score(p: ApplicationPage) -> int:
            text = f"{p.title or ''} {p.url or ''}".lower()
            base = sum(1 for kw in keywords if kw in text)
            return base + (1 if p.page_type in ("form", "detail") else 0)

        top_pages = sorted(pages, key=page_score, reverse=True)[:5]

        # Find relevant workflows
        wf_result = await self.db.execute(
            select(ApplicationWorkflow)
            .join(ApplicationModule, ApplicationWorkflow.module_id == ApplicationModule.id)
            .where(ApplicationModule.application_id == application_id)
        )
        workflows = list(wf_result.scalars().all())

        def wf_score(wf: ApplicationWorkflow) -> int:
            return sum(1 for kw in keywords if kw in (wf.name or "").lower())

        top_wfs = sorted(workflows, key=wf_score, reverse=True)[:4]

        return {
            "business_objects": kg_summary.get("business_objects", []),
            "relevant_pages": [
                {
                    "title": p.title,
                    "url": p.url,
                    "page_type": p.page_type,
                    "forms": [
                        {
                            "name": f.get("name", ""),
                            "entity": f.get("entity", ""),
                            "submit_action": f.get("submit_action", ""),
                            "success_message": f.get("success_message", ""),
                            "fields": [
                                {
                                    "label": fld.get("label", ""),
                                    "type": fld.get("type", "text"),
                                    "required": fld.get("required", False),
                                    "validation": fld.get("validation", ""),
                                    "options": fld.get("options", [])[:8],
                                    "depends_on": fld.get("depends_on"),
                                }
                                for fld in (f.get("fields") or [])[:12]
                            ],
                        }
                        for f in (p.forms or [])[:3]
                    ],
                    "tables": [
                        {
                            "name": t.get("name", ""),
                            "entity": t.get("entity", ""),
                            "row_actions": t.get("row_actions", []),
                        }
                        for t in (p.tables or [])[:3]
                    ],
                    "crud_operations": (p.semantic_map or {}).get("crud_operations", {}),
                }
                for p in top_pages
            ],
            "relevant_workflows": [
                {
                    "name": wf.name,
                    "type": wf.workflow_type,
                    "entity": (wf.entry_point or {}).get("entity", ""),
                    "preconditions": (wf.entry_point or {}).get("preconditions", []),
                    "success_criteria": wf.success_indicators or [],
                    "stages": wf.stages or [],
                }
                for wf in top_wfs
            ],
        }

    # ── AI generation ─────────────────────────────────────────────────────────

    async def _ai_generate(self, target: str, context: dict) -> dict:
        user_msg = (
            f"TEST TARGET: {target}\n\n"
            f"APPLICATION CONTEXT:\n{json.dumps(context, indent=1)}\n\n"
            "Generate exploratory tests covering ALL 6 categories. "
            "Use the actual field names and validation rules from the context. "
            "Make each test specific and executable."
        )
        try:
            response = await asyncio.wait_for(
                self.ai.complete(
                    system=_SYSTEM,
                    user=user_msg,
                    json_mode=True,
                    max_tokens=4000,
                ),
                timeout=90.0,
            )
            return response.json()
        except Exception as e:
            log.warning("Exploratory AI generation failed", error=str(e))
            return {"scenarios": []}

    # ── Persistence ───────────────────────────────────────────────────────────

    async def _persist(self, raw: dict, application_id: str, user_id: str) -> list[Scenario]:
        priority_map = {
            "CRITICAL": ScenarioPriority.CRITICAL,
            "HIGH": ScenarioPriority.HIGH,
            "MEDIUM": ScenarioPriority.MEDIUM,
            "LOW": ScenarioPriority.LOW,
        }
        entity = raw.get("entity", "")
        module_id = await self._find_module(application_id, entity, raw.get("target_summary", ""))

        created: list[Scenario] = []
        for s in raw.get("scenarios", [])[:120]:
            title = (s.get("title") or "").strip()
            if not title:
                continue

            desc = s.get("description", "")
            if s.get("expected_behavior"):
                desc += f"\n\nExpected: {s['expected_behavior']}"
            if s.get("test_data"):
                desc += f"\n\nTest Data:\n{json.dumps(s['test_data'], indent=2)}"

            tags: list[str] = list(s.get("tags", [])) or []
            for required in ("exploratory", s.get("category", "")):
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

        log.info("Exploratory scenarios created",
            count=len(created), entity=entity, application_id=application_id)
        return created

    async def _find_module(
        self, application_id: str, entity: str, target: str
    ) -> str | None:
        result = await self.db.execute(
            select(ApplicationModule).where(ApplicationModule.application_id == application_id)
        )
        modules = list(result.scalars().all())
        if not modules:
            return None
        words = set((entity + " " + target).lower().split())
        words -= {"test", "the", "a", "add", "create", "edit", "update", "delete"}
        best, best_score = None, 0
        for m in modules:
            score = sum(1 for w in words if w in m.name.lower())
            if score > best_score:
                best_score, best = score, m
        return (best or modules[0]).id
