"""
Copilot Context Builder
Enriches AI Copilot requests with ground-truth application knowledge from exploration.

When a user says "Add generic master", this module:
  1. Finds the best matching ApplicationModule by keyword overlap
  2. Loads its pages (with forms, tables, field definitions)
  3. Loads its discovered workflows (entry triggers, steps, success indicators)
  4. Loads semantic elements (exact button/field labels)
  5. Detects the operation type (crud_create, crud_update, etc.)
  6. Returns a structured context dict the AI prompt can use directly
"""
from __future__ import annotations
import re
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    ApplicationModule, ApplicationPage,
    ApplicationWorkflow, SemanticElement,
)

log = structlog.get_logger()


# ─── Operation Detection ──────────────────────────────────────────────────────

_OPERATION_KEYWORDS: dict[str, list[str]] = {
    "crud_create": ["add", "create", "new", "insert", "register", "submit", "adding", "creating"],
    "crud_update": ["edit", "update", "modify", "change", "correct", "fix", "revise", "editing"],
    "crud_delete": ["delete", "remove", "archive", "deactivate", "purge", "cancel", "deleting"],
    "crud_read":   ["view", "list", "browse", "read", "see", "display", "show", "viewing"],
    "search":      ["search", "find", "filter", "lookup", "query", "locate", "searching"],
    "navigation":  ["navigate", "go to", "open", "access", "visit"],
}


def detect_operation(description: str) -> str:
    """Classify the intended test operation from free-text description."""
    lower = description.lower()
    scores: dict[str, int] = {}
    for op, keywords in _OPERATION_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score:
            scores[op] = score
    if not scores:
        return "crud_create"
    return max(scores, key=lambda k: scores[k])


# ─── Scoring ──────────────────────────────────────────────────────────────────

def _word_overlap(a: str, b: str) -> float:
    """
    Jaccard-style word overlap between two strings, case-insensitive.
    Returns 0.0–1.0.
    """
    def tokens(s: str) -> set[str]:
        return set(re.sub(r"[^a-z0-9\s]", " ", s.lower()).split())

    t1, t2 = tokens(a), tokens(b)
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / min(len(t1), len(t2))


# ─── Context Builder ──────────────────────────────────────────────────────────

class CopilotContextBuilder:
    """
    Builds a rich context dict for the AI Copilot from exploration data.
    All DB queries are read-only and lightweight.
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def build(self, description: str, application_id: str) -> dict[str, Any]:
        """
        Main entry point.
        Returns a context dict used by the AI prompt builder.
        """
        operation = detect_operation(description)

        # 1 — Find best-matching module
        modules = await self._rank_modules(description, application_id)
        if not modules:
            return {
                "operation": operation,
                "has_exploration_data": False,
                "all_module_names": [],
            }

        best = modules[0]
        other_names = [m["name"] for m in modules[1:5]]

        # 2 — Load pages (forms + tables live inside pages)
        pages = await self._load_pages(best["id"])

        # 3 — Load workflows (have exact entry triggers + steps)
        workflows = await self._load_workflows(best["id"])

        # 4 — Load semantic elements (buttons, inputs with exact labels)
        page_ids = [p["id"] for p in pages]
        elements = await self._load_elements(page_ids) if page_ids else []

        # 5 — Extract forms and tables out of page records
        forms: list[dict] = []
        tables: list[dict] = []
        for page in pages:
            for form in (page.get("forms") or []):
                forms.append({**form, "_page_url": page["url"], "_page_type": page["page_type"]})
            for tbl in (page.get("tables") or []):
                tables.append({**tbl, "_page_url": page["url"]})

        # 6 — Match the best workflow for this operation type
        matched_workflow = self._best_workflow(operation, workflows)

        log.info(
            "Copilot context built",
            module=best["name"],
            operation=operation,
            pages=len(pages),
            forms=len(forms),
            elements=len(elements),
            workflows=len(workflows),
        )

        return {
            "operation": operation,
            "has_exploration_data": True,
            "module": best,
            "other_module_names": other_names,
            "pages": pages,
            "forms": forms,
            "tables": tables,
            "elements": elements,
            "workflows": workflows,
            "matched_workflow": matched_workflow,
        }

    # ─── Private helpers ──────────────────────────────────────────────────────

    async def _rank_modules(
        self, description: str, application_id: str
    ) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(ApplicationModule).where(
                ApplicationModule.application_id == application_id
            )
        )
        all_mods = result.scalars().all()
        if not all_mods:
            return []

        scored: list[dict] = []
        for mod in all_mods:
            score = _word_overlap(description, mod.name)
            if mod.description:
                score = max(score, _word_overlap(description, mod.description) * 0.8)
            tags = mod.semantic_tags
            if tags and isinstance(tags, list):
                score = max(score, _word_overlap(description, " ".join(tags)) * 0.6)
            scored.append({
                "id": mod.id,
                "name": mod.name,
                "url": mod.url_pattern or "",
                "description": mod.description or "",
                "score": score,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)

        # Return top-scoring results; if nothing matched, return highest-scoring anyway
        positives = [s for s in scored if s["score"] > 0]
        return positives[:5] if positives else scored[:1]

    async def _load_pages(self, module_id: str) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(ApplicationPage)
            .where(ApplicationPage.module_id == module_id)
            .limit(15)
        )
        pages = result.scalars().all()
        return [
            {
                "id": p.id,
                "title": p.title,
                "url": p.url,
                "page_type": p.page_type or "unknown",
                "forms": p.forms or [],
                "tables": p.tables or [],
                "navigation_links": p.navigation_links or [],
            }
            for p in pages
        ]

    async def _load_workflows(self, module_id: str) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(ApplicationWorkflow)
            .where(ApplicationWorkflow.module_id == module_id)
            .limit(15)
        )
        wfs = result.scalars().all()
        out = []
        for w in wfs:
            ep = w.entry_point or {}
            out.append({
                "name": w.name,
                "type": w.workflow_type or "unknown",
                "trigger": ep.get("trigger", ""),
                "entity": ep.get("entity", ""),
                "preconditions": ep.get("preconditions", []),
                "stages": w.stages or [],
                "success_indicators": w.success_indicators or [],
            })
        return out

    async def _load_elements(self, page_ids: list[str]) -> list[dict[str, Any]]:
        result = await self.db.execute(
            select(SemanticElement)
            .where(SemanticElement.page_id.in_(page_ids))
            .limit(80)
        )
        elems = result.scalars().all()
        return [
            {
                "label": e.semantic_label,
                "type": e.element_type or "element",
                "purpose": e.purpose or "",
                "stage": e.workflow_stage or "",
            }
            for e in elems
        ]

    def _best_workflow(
        self, operation: str, workflows: list[dict]
    ) -> dict[str, Any] | None:
        """Return the workflow whose type best matches the operation."""
        # Direct type match first
        for wf in workflows:
            if wf["type"] == operation:
                return wf
        # Prefix match (e.g. operation=crud_create matches crud_create_bulk)
        op_prefix = operation.split("_")[0]  # "crud" or "search" etc.
        for wf in workflows:
            if wf["type"].startswith(op_prefix):
                return wf
        return workflows[0] if workflows else None
