"""
Test Intent Analyzer — Semantic Intent Extraction.

Fast AI call that converts a scenario title + description into structured
business testing intent. This feeds the IntentOrchestrator which in turn
enriches the QAReasoningEngine and EntityTracker.

Why this matters:
  "Test Products CRUD" → entity=Product, fields=[Name,Code,Price,Status],
  rules=["Name must be unique"], data_naming={create:"TestProduct001", update:"UpdatedProduct001"}

  Without this, the AI guesses entity names, the EntityTracker uses "Record",
  and recovery/reporting have no business-level context.

Design:
  - Called ONCE per scenario at plan generation time (not execution time)
  - Fast=True, max_tokens=500, 10s timeout
  - Rule-based fallback on any failure — never blocks execution
"""
from __future__ import annotations
import asyncio
import re
from typing import Any

import structlog

from app.intelligence.ai_client import get_ai_client

log = structlog.get_logger()

_SYSTEM = """You are QAptain's Test Intent Analyzer.

Given a test scenario title and description, extract the semantic testing intent.

Rules:
- primary_entity: the main business entity under test (e.g. "Product", "User", "Sample")
  NOT the module name — the ENTITY the module manages
- entity_plural: correct English plural (e.g. "Products", "Users", "Samples")
- workflow_type: pick ONE — CRUD|SEARCH_FILTER|PAGINATION|SORTING|FORM_VALIDATION|AUTH|ROLE_ACCESS|FILE_UPLOAD|EXPORT|NAVIGATION|BUSINESS_WORKFLOW
- likely_fields: top 4-6 field names this entity likely has (e.g. ["Name","Code","Status","Price"])
- critical_business_rules: up to 3 inferred business rules (e.g. "Name must be unique")
- data_naming.create_name: realistic test entity name for creation — use entity name (e.g. "TestProduct001" NOT "TestRecord001")
- data_naming.update_name: updated name after modification (e.g. "UpdatedProduct001")

Output ONLY valid JSON:
{
  "primary_entity": "Product",
  "entity_plural": "Products",
  "workflow_type": "CRUD",
  "operations": ["create", "read", "update", "delete"],
  "business_context": "Verify full product lifecycle management in the inventory system",
  "likely_fields": ["Name", "Code", "Price", "Status", "Category"],
  "critical_business_rules": ["Product name must be unique", "Price must be positive"],
  "risk_areas": ["duplicate prevention", "deletion confirmation", "required field validation"],
  "test_scope": "full_coverage",
  "data_naming": {
    "create_name": "TestProduct001",
    "update_name": "UpdatedProduct001"
  }
}"""


class IntentAnalyzer:
    """Extracts semantic testing intent from a scenario title + description."""

    def __init__(self) -> None:
        self.ai = get_ai_client()

    async def analyze(
        self,
        title: str,
        description: str = "",
        module_name: str = "",
        module_context: str = "",
    ) -> dict[str, Any]:
        """
        Analyze scenario intent. Returns structured dict.
        Always succeeds — falls back to rule-based on any error.
        """
        prompt = f"Scenario Title: {title}\nDescription: {description or 'N/A'}\nModule: {module_name or 'Unknown'}\nContext: {module_context or 'N/A'}"

        try:
            response = await asyncio.wait_for(
                self.ai.complete(
                    system=_SYSTEM,
                    user=prompt,
                    fast=True,
                    json_mode=True,
                    max_tokens=500,
                ),
                timeout=10.0,
            )
            result = response.json()
            # Validate minimum required fields
            if result.get("primary_entity") and result.get("workflow_type"):
                log.debug("Intent analyzed (AI)",
                    entity=result["primary_entity"], workflow=result["workflow_type"])
                return result
        except (Exception, asyncio.CancelledError) as e:
            log.debug("Intent analysis AI call failed — using rules", error=str(e)[:80])

        return self._rule_based(title, description, module_name)

    def _rule_based(self, title: str, description: str, module_name: str) -> dict[str, Any]:
        """Deterministic fallback. Fast, zero dependencies."""
        combined = (title + " " + description).lower()

        # Workflow type
        if any(k in combined for k in ("search", "filter", "find", "query", "lookup")):
            workflow = "SEARCH_FILTER"
        elif any(k in combined for k in ("paginat", "page", "next page", "prev page")):
            workflow = "PAGINATION"
        elif any(k in combined for k in ("sort", "ascending", "descending", "order by")):
            workflow = "SORTING"
        elif any(k in combined for k in ("login", "auth", "sign in", "credential")):
            workflow = "AUTH"
        elif any(k in combined for k in ("role", "rbac", "permission", "access control", "restricted")):
            workflow = "ROLE_ACCESS"
        elif any(k in combined for k in ("upload", "attach file", "file upload")):
            workflow = "FILE_UPLOAD"
        elif any(k in combined for k in ("export", "download csv", "export excel")):
            workflow = "EXPORT"
        elif any(k in combined for k in ("crud", "create", "update", "delete", "add", "edit", "manage")):
            workflow = "CRUD"
        else:
            workflow = "NAVIGATION"

        # Entity name
        entity = self._extract_entity(title, module_name)
        plural = entity + "s" if not entity.lower().endswith("s") else entity

        # Deterministic test data names (match CRUDEngine convention)
        create_name = f"Test{entity}001"
        update_name = f"Updated{entity}001"

        return {
            "primary_entity": entity,
            "entity_plural": plural,
            "workflow_type": workflow,
            "operations": (
                ["create", "read", "update", "delete"] if workflow == "CRUD"
                else ["read"] if workflow in ("SEARCH_FILTER", "PAGINATION", "SORTING")
                else ["auth"] if workflow == "AUTH"
                else []
            ),
            "business_context": f"Verify {entity} {workflow.replace('_', ' ').lower()} functionality",
            "likely_fields": ["Name", "Code", "Status", "Description"],
            "critical_business_rules": [
                f"{entity} name must be unique",
                "Required fields must be validated",
            ],
            "risk_areas": ["data validation", "state persistence"],
            "test_scope": "functional",
            "data_naming": {
                "create_name": create_name,
                "update_name": update_name,
            },
        }

    @staticmethod
    def _extract_entity(title: str, module_name: str) -> str:
        """Extract primary entity name from scenario title or module name."""
        # "Test Products CRUD" → "Product"
        # "CRUD for Inventory Items" → "Inventory Items" → "Item"
        # "Verify Search for Users" → "User"
        patterns = [
            r"(?:test|verify|check|validate)\s+(\w+)\s+(?:crud|search|filter|paginat|sort)",
            r"(?:crud|test)\s+(?:for\s+)?(\w+?)(?:\s+crud)?$",
            r"(?:for|of|on)\s+(\w+)\s*$",
            r"^(\w+)\s+(?:module|management|operations?|listing)",
        ]
        for pat in patterns:
            m = re.search(pat, title, re.IGNORECASE)
            if m:
                word = m.group(1).strip().rstrip("s")  # de-pluralize
                if len(word) > 2:
                    return word.title()

        # Try module name (strip common suffixes)
        if module_name:
            clean = re.sub(r"\s*(module|management|list|page)$", "", module_name, flags=re.IGNORECASE).strip()
            if clean:
                return clean.rstrip("s").title()

        # Last resort: first capitalized word from title
        for word in title.split():
            if word[0].isupper() and len(word) > 3 and word.lower() not in (
                "test", "verify", "check", "crud", "search", "filter",
            ):
                return word.rstrip("s").title()
        return "Record"
