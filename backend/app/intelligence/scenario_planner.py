"""
Scenario Planning Engine
Converts natural language test scenarios into structured, intelligent execution plans.

Architecture:
  - QAReasoningEngine (primary): AI reasons like a senior QA engineer
    → Classifies workflow type (CRUD, AUTH, ROLE_ACCESS, FORM_VALIDATION, SEARCH, NAVIGATION)
    → Auto-expands CRUD into 8 phases
    → Generates semantic validations + edge cases + checkpoint validations
  - Fallback: capability engine plan — deterministic, no AI, uses KG data

AI is called ONCE per scenario — plan is cached and reused on re-runs.
"""
from __future__ import annotations
import time
import json
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Any

from app.db.models import (
    Scenario, ExecutionPlan, Application, ApplicationModule,
    ApplicationPage, SemanticElement, ApplicationWorkflow,
)
from app.intelligence.ai_client import get_ai_client
from app.intelligence.qa_reasoning_engine import QAReasoningEngine
from config import settings

log = structlog.get_logger()


def _detect_workflow_type(title: str, description: str = "") -> str:
    """Detect workflow type from scenario title — mirrors QA engine classification."""
    title_lower = title.lower()
    text = (title_lower + " " + description.lower())

    # AUTH is highest priority — very specific keywords (not "session" alone — too broad)
    if any(w in text for w in ("login", "sign in", "logout", "auth", "credential")):
        return "AUTH"

    # CRUD: a single CRUD verb in the TITLE is sufficient — the description often
    # contains "navigate to ..." which would otherwise suppress CRUD detection.
    # e.g. "Add Column record end-to-end" → title has "add" → CRUD.
    if any(w in title_lower for w in ("create", "add", "edit", "update", "delete", "remove")):
        return "CRUD"
    # If not in title, require 2+ signals from the full text
    crud_signals = sum(1 for w in ("create", "edit", "delete", "add", "update") if w in text)
    if crud_signals >= 2:
        return "CRUD"

    if any(w in text for w in ("search", "filter", "find record", "query")):
        return "SEARCH_FILTER"
    if any(w in text for w in ("pagination", "next page", "previous page", "paging")):
        return "PAGINATION"
    if any(w in text for w in ("sort", "ascending", "descending", "order by")):
        return "SORTING"
    if any(w in text for w in ("validation", "required field", "error message", "mandatory")):
        return "FORM_VALIDATION"
    if any(w in text for w in ("upload", "attach file", "import file")):
        return "FILE_UPLOAD"
    if any(w in text for w in ("export", "download", "csv", "excel", "pdf")):
        return "EXPORT"
    if any(w in text for w in ("access", "permission", "role", "restricted", "unauthorized")):
        return "ROLE_ACCESS"
    if any(w in text for w in ("navigate", "access module", "open page", "go to")):
        return "NAVIGATION"
    return "CRUD"  # safe default — covers most entity-management scenarios


def _extract_operation_intent(title: str, description: str = "") -> dict:
    """
    Extract which specific CRUD operation(s) the scenario intends to test.

    Returns:
      operation       — "create" | "update" | "delete" | "read" | "full_crud"
      crud_workflows  — ordered list of KG workflow types to stitch
      test_variants   — which test categories to include
      scope_note      — one-line scope constraint injected into the AI prompt
    """
    text = (title + " " + (description or "")).lower()
    title_lower = title.lower()

    _CREATE = ("add", "create", "insert", "new record", "add new", "create new",
               "adding", "submit form", "fill form")
    _UPDATE = ("edit", "update", "modify", "change", "amend", "alter", "updating")
    _DELETE = ("delete", "remove", "archive", "deactivate", "purge", "deleting")
    _READ   = ("view only", "read only", "display", "listing", "list records")

    in_title = {
        "create": any(w in title_lower for w in _CREATE),
        "update": any(w in title_lower for w in _UPDATE),
        "delete": any(w in title_lower for w in _DELETE),
        "read":   any(w in title_lower for w in _READ),
    }

    # Strong scope phrases take precedence over individual verb matching
    if any(p in text for p in ("e2e add", "end to end add", "add scenario", "test add",
                                "add test", "add only", "add feature", "add functionality",
                                "add record", "test adding", "adding scenario")):
        operation = "create"
    elif any(p in text for p in ("e2e edit", "end to end edit", "edit scenario", "test edit",
                                  "e2e update", "update scenario", "update only", "update feature",
                                  "update record", "test updating")):
        operation = "update"
    elif any(p in text for p in ("e2e delete", "end to end delete", "delete scenario",
                                  "test delete", "delete only", "delete feature",
                                  "delete record", "test deleting")):
        operation = "delete"
    elif any(p in text for p in ("full crud", "all operations", "create edit delete",
                                  "create update delete", "crud operations")):
        operation = "full_crud"
    # Single-operation title signals
    elif in_title["create"] and not in_title["update"] and not in_title["delete"]:
        operation = "create"
    elif in_title["update"] and not in_title["create"] and not in_title["delete"]:
        operation = "update"
    elif in_title["delete"] and not in_title["create"] and not in_title["update"]:
        operation = "delete"
    elif in_title["read"] and not any(in_title[k] for k in ("create", "update", "delete")):
        operation = "read"
    else:
        operation = "full_crud"  # ambiguous or multi-operation — run everything

    # Which KG workflow types to load (create is always first — need a record to edit/delete)
    workflow_map = {
        "create":    ["crud_create"],
        "update":    ["crud_create", "crud_update"],
        "delete":    ["crud_create", "crud_delete"],
        "read":      ["crud_create"],
        "full_crud": ["crud_create", "crud_update", "crud_delete"],
    }

    # Test variant categories — always positive + validation; expand if keywords present
    variants = ["positive", "validation"]
    if any(w in text for w in ("negative", "invalid", "error", "fail", "bad data")):
        variants.append("negative")
    if any(w in text for w in ("boundary", "bva", "edge case", "edge cases", "min", "max")):
        variants.append("bva")
    if any(w in text for w in ("security", "injection", "xss", "sql")):
        variants.append("security")
    if operation in ("create", "full_crud") and "negative" not in variants:
        variants.append("negative")

    scope_notes = {
        "create":    "SCOPE: Test ADD/CREATE only — do NOT generate update, edit, or delete phases.",
        "update":    "SCOPE: Test EDIT/UPDATE flow — create a record first, then test editing it. Do NOT generate delete phases.",
        "delete":    "SCOPE: Test DELETE flow — create a record first, then test deleting it. Do NOT generate update phases.",
        "read":      "SCOPE: Test READ/VIEW only — verify records are visible and data is correct. No mutations.",
        "full_crud": "SCOPE: Test the complete CRUD lifecycle — create, edit, and delete in sequence.",
    }

    return {
        "operation": operation,
        "crud_workflows": workflow_map.get(operation, ["crud_create", "crud_update", "crud_delete"]),
        "test_variants": list(dict.fromkeys(variants)),
        "scope_note": scope_notes.get(operation, ""),
    }

ALLOWED_ACTIONS = frozenset([
    "navigate", "click", "fill", "clear", "select", "key_press", "hover",
    "assert_visible", "assert_text", "assert_not_text", "assert_url", "assert_count",
    "wait_network", "wait_element", "wait_ms",
    "scroll", "upload", "screenshot", "assert_ai_semantic",
])

MODE_CAPS = {
    "smoke":            {"max_steps": 12,  "depth": "minimal — happy path only"},
    "functional":       {"max_steps": 30,  "depth": "standard — key flows + basic validation"},
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

        Falls back to the capability engine immediately when Azure is rate-limited
        so the user is never blocked waiting on 429 retries.
        """
        caps = MODE_CAPS.get(execution_mode, MODE_CAPS["functional"])

        # Tier 0: KG-recorded workflows — exact selectors, zero AI, zero rate limits.
        # Only available for modules that have been explored at least once.
        if scenario.module_id:
            try:
                kg_plan = await self._build_plan_from_kg(scenario, execution_mode)
                if kg_plan:
                    return kg_plan
            except Exception as _kg_err:
                log.warning("KG plan build failed — falling through to AI",
                    error=str(_kg_err)[:120], scenario_id=scenario.id)

        # Tier 1: AI reasoning (with rate-limit pre-check)
        # Pre-check Azure rate limiter — skip AI if we'd wait > 5 seconds.
        if settings.AI_PROVIDER == "azure_openai":
            from app.intelligence.azure_rate_limiter import get_azure_limiter
            limiter = get_azure_limiter()
            wait = limiter.current_wait()
            if wait > 5.0:
                log.warning(
                    "Azure rate limiter active — using capability engine plan immediately",
                    wait_seconds=round(wait, 1),
                    scenario_id=scenario.id,
                )
                return await self.generate_fallback_plan(scenario, execution_mode)

        try:
            plan_data = await self._qa_engine.build_plan(scenario, execution_mode)
        except Exception as e:
            log.error("QA reasoning engine failed — using capability engine fallback",
                error=str(e), scenario_id=scenario.id)
            return await self.generate_fallback_plan(scenario, execution_mode)

        plan_data = self._validate_and_cap(plan_data, caps["max_steps"])

        # Detect fallback so the batch executor can identify and retry these plans
        _qa_reasoning = plan_data.get("qa_reasoning", "")
        _is_fallback = (
            _qa_reasoning.startswith("Fallback plan")
            or _qa_reasoning.startswith("Capability engine plan")
        )

        plan = ExecutionPlan(
            scenario_id=scenario.id,
            execution_mode=execution_mode,
            plan_data=plan_data,
            ai_reasoning=plan_data.get("qa_reasoning", ""),
            semantic_intent=plan_data.get("semantic_intent", {}),
            workflow_stages=self._extract_workflow_stages(plan_data),
            risk_score=self._calculate_risk(plan_data, execution_mode),
            estimated_duration_seconds=len(plan_data.get("steps", [])) * 5,
            created_by_model="fallback" if _is_fallback else settings.PRIMARY_MODEL,
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
        """
        Capability-engine plan — no AI call.
        Uses KG data (module URL, form fields) + deterministic capability steps.
        Produces a real, runnable test plan even when Azure is unavailable.
        """
        from app.capabilities.engine_registry import get_engine_registry

        caps = MODE_CAPS.get(execution_mode, MODE_CAPS["functional"])

        # Load module context from DB
        module_url = "/"
        module_name = ""
        form_fields: list[str] = []

        if scenario.module_id:
            mod_result = await self.db.execute(
                select(ApplicationModule).where(ApplicationModule.id == scenario.module_id)
            )
            mod = mod_result.scalar_one_or_none()
            if mod:
                module_url = mod.url_pattern or "/"
                module_name = mod.name or ""
                # If url_pattern is empty, try the first page URL for this module
                if module_url == "/":
                    first_page = await self.db.execute(
                        select(ApplicationPage)
                        .where(ApplicationPage.module_id == scenario.module_id)
                        .limit(1)
                    )
                    fp = first_page.scalar_one_or_none()
                    if fp:
                        module_url = fp.url or "/"

            pages_result = await self.db.execute(
                select(ApplicationPage)
                .where(ApplicationPage.module_id == scenario.module_id)
                .limit(4)
            )
            # Keywords that indicate a search/filter widget on the list view,
            # not a field on a create/edit form.
            _SEARCH_KEYWORDS = ("search", "filter", "find", "query", "lookup",
                                 "look up", "by product", "by name", "by id")
            seen_fields: set[str] = set()
            for page in pages_result.scalars().all():
                for form in (page.forms or [])[:2]:
                    for fld in form.get("fields", [])[:10]:
                        lbl = (fld.get("label") or fld.get("placeholder") or "").strip()
                        if not lbl or lbl in seen_fields:
                            continue
                        if any(k in lbl.lower() for k in _SEARCH_KEYWORDS):
                            continue
                        seen_fields.add(lbl)
                        form_fields.append(lbl)

        # Detect workflow type + operation intent, then run capability engine
        workflow_type = _detect_workflow_type(scenario.title, scenario.description or "")
        op_intent = _extract_operation_intent(scenario.title, scenario.description or "")
        registry = get_engine_registry()
        cap_ctx = registry.build_capability_context(
            scenario_title=scenario.title,
            scenario_description=scenario.description or "",
            workflow_type=workflow_type,
            module_name=module_name,
            module_url=module_url,
            execution_mode=execution_mode,
        )
        cap_ctx.form_fields = form_fields
        # Pass operation intent so capability engines scope their step generation
        cap_ctx.operation_type = op_intent["operation"]
        cap_ctx.test_variants = op_intent["test_variants"]

        steps_by_cat = registry.generate_capability_steps(cap_ctx)

        # Navigate to the module first if we have a URL
        nav_steps: list[dict] = []
        if module_url and module_url != "/":
            nav_steps = [
                {
                    "action": "navigate",
                    "target": "",
                    "value": "",
                    "url": module_url,
                    "description": f"Navigate to {module_name or 'module'}",
                    "phase": "SETUP",
                    "business_intent": "Navigate to target module",
                    "timeout_ms": 15000,
                    "on_fail": "fail",
                    "checkpoint": False,
                },
                {
                    "action": "wait_ms",
                    "target": "",
                    "value": "",
                    "url": "",
                    "description": "Wait for SPA to render",
                    "ms": 2000,
                    "phase": "SETUP",
                    "business_intent": "Allow route change to complete",
                    "timeout_ms": 5000,
                    "on_fail": "skip",
                    "checkpoint": False,
                },
            ]

        # Combine: positive happy-path steps + limited negative tests
        positive = steps_by_cat.get("positive", [])
        negative = steps_by_cat.get("negative", [])[:5]
        remaining = caps["max_steps"] - len(nav_steps)
        combined = (positive + negative)[:remaining]
        all_steps = nav_steps + combined

        plan_data = {
            "workflow": workflow_type,
            "workflow_type": workflow_type,
            "goal": f"Verify {scenario.title} works as expected",
            "qa_reasoning": (
                f"Capability engine plan — AI unavailable (rate limited or error). "
                f"Engine: {workflow_type}, steps: {len(all_steps)}, "
                f"module: {module_name or 'unknown'}"
            ),
            "test_strategy": {
                "phases": list(dict.fromkeys(
                    s.get("phase", "") for s in all_steps if s.get("phase")
                )),
                "primary_operation": workflow_type.lower(),
                "validations": ["Module loads", "Operations complete successfully"],
                "negative_tests": [s.get("description", "") for s in negative[:3]],
            },
            "steps": all_steps,
            "checkpoint_validations": [],
            "semantic_intent": {
                "module": module_name,
                "operation": workflow_type.lower(),
                "pass_criteria": "All steps complete without errors",
                "fail_criteria": "Any critical step fails",
            },
        }

        plan_data = self._validate_and_cap(plan_data, caps["max_steps"])

        plan = ExecutionPlan(
            scenario_id=scenario.id,
            execution_mode=execution_mode,
            plan_data=plan_data,
            ai_reasoning=plan_data["qa_reasoning"],
            semantic_intent=plan_data.get("semantic_intent", {}),
            workflow_stages=self._extract_workflow_stages(plan_data),
            risk_score=self._calculate_risk(plan_data, execution_mode),
            estimated_duration_seconds=len(plan_data.get("steps", [])) * 5,
            created_by_model="capability_engine",
        )

        latest = await self._latest_plan_version(scenario.id)
        if latest:
            plan.version = latest.version + 1

        self.db.add(plan)
        await self.db.commit()

        log.info("Capability-engine fallback plan generated",
            plan_id=plan.id,
            workflow_type=workflow_type,
            steps=len(plan_data.get("steps", [])),
            module_url=module_url,
        )
        return plan

    async def _build_plan_from_kg(
        self,
        scenario: Scenario,
        execution_mode: str,
    ) -> "ExecutionPlan | None":
        """
        Tier 0 plan generation: build a precise execution plan directly from
        KG-recorded ApplicationWorkflow stages (exact CSS selectors, real test values).

        Returns None if the module has no recorded workflows yet — callers then
        fall through to AI or the capability engine.
        """
        if not scenario.module_id:
            return None

        mod_result = await self.db.execute(
            select(ApplicationModule).where(ApplicationModule.id == scenario.module_id)
        )
        mod = mod_result.scalar_one_or_none()
        if not mod:
            return None

        wf_result = await self.db.execute(
            select(ApplicationWorkflow).where(ApplicationWorkflow.module_id == scenario.module_id)
        )
        workflows: list = wf_result.scalars().all()
        if not workflows:
            return None

        caps = MODE_CAPS.get(execution_mode, MODE_CAPS["functional"])
        workflow_type = _detect_workflow_type(scenario.title, scenario.description or "")
        op_intent = _extract_operation_intent(scenario.title, scenario.description or "")

        # Normalise workflow type names: AI page-analyzer emits "crud_lifecycle",
        # "data_entry", "form_submission" etc. Map them to the canonical planner names.
        _WF_TYPE_ALIASES = {
            "crud_lifecycle":   "crud_create",
            "data_entry":       "crud_create",
            "form_submission":  "crud_create",
            "list_management":  "crud_create",
            "record_update":    "crud_update",
            "record_delete":    "crud_delete",
            "login":            "auth",
            "authentication":   "auth",
            "search_filter":    "search",
            "export_report":    "export",
        }
        wf_by_type: dict[str, Any] = {}
        for wf in workflows:
            canonical = _WF_TYPE_ALIASES.get(wf.workflow_type, wf.workflow_type)
            wf_by_type[canonical] = wf
            if wf.workflow_type != canonical:
                wf_by_type[wf.workflow_type] = wf  # keep original too

        # Determine which recorded workflows to stitch, scoped by operation intent.
        # e.g. "Test Add scenarios" → only crud_create; "Test Delete" → crud_create + crud_delete
        if workflow_type == "CRUD":
            ordered_types = op_intent["crud_workflows"]
        elif workflow_type == "AUTH":
            ordered_types = ["auth"]
        elif workflow_type == "SEARCH_FILTER":
            ordered_types = ["search", "crud_create"]
        elif workflow_type == "EXPORT":
            ordered_types = ["export", "crud_create"]
        else:
            # Use whatever workflows exist for this module
            ordered_types = list(wf_by_type.keys())

        available = [t for t in ordered_types if t in wf_by_type]
        if not available:
            return None

        # Resolve module URL for the navigate step
        module_url = mod.url_pattern or "/"
        if module_url == "/":
            first_page = await self.db.execute(
                select(ApplicationPage)
                .where(ApplicationPage.module_id == scenario.module_id)
                .limit(1)
            )
            fp = first_page.scalar_one_or_none()
            if fp and fp.url:
                module_url = fp.url

        # Build step list: navigate → stitched KG stages
        steps: list[dict] = [
            {
                "action": "navigate",
                "target": module_url,
                "value": "",
                "url": module_url,
                "description": f"Navigate to {mod.name or 'module'}",
                "phase": "SETUP",
                "on_fail": "fail",
                "timeout_ms": 15000,
                "checkpoint": False,
                "business_intent": "Open target module",
            },
        ]
        seq = 2
        for wf_type in ordered_types:
            wf = wf_by_type.get(wf_type)
            if not wf or not wf.stages:
                continue
            for stage in wf.stages:
                step = dict(stage)
                step["seq"] = seq
                # Ensure executor-expected keys are present
                step.setdefault("target", step.pop("selector", ""))
                step.setdefault("value", step.get("test_value", ""))
                step.setdefault("on_fail", "skip")
                step.setdefault("timeout_ms", 8000)
                step.setdefault("checkpoint", False)
                step.setdefault("business_intent", "")
                steps.append(step)
                seq += 1
                if seq > caps["max_steps"]:
                    break
            if seq > caps["max_steps"]:
                break

        # Append validation variant steps when the happy-path has room and
        # the scenario is testing a create/full-crud operation.
        remaining_budget = caps["max_steps"] - seq
        if remaining_budget >= 4 and op_intent["operation"] in ("create", "full_crud"):
            create_wf = wf_by_type.get("crud_create")
            if create_wf:
                variant_steps = self._build_validation_variant(
                    create_wf, seq, remaining_budget
                )
                steps.extend(variant_steps)
                seq += len(variant_steps)

        plan_data: dict[str, Any] = {
            "workflow_type": workflow_type,
            "goal": f"Verify {scenario.title} works as expected",
            "qa_reasoning": (
                f"KG-recorded plan from {len(available)} workflow(s) for '{mod.name}'. "
                f"Operation: {op_intent['operation']}. "
                f"Includes: {', '.join(op_intent['test_variants'])}. "
                f"Exact selectors from exploration — no AI needed."
            ),
            "steps": steps,
            "checkpoint_validations": [],
            "semantic_intent": {
                "source": "kg_recorded",
                "module": mod.name,
                "operation": op_intent["operation"],
                "operation_scope": op_intent["scope_note"],
                "test_variants": op_intent["test_variants"],
                "kg_workflows": available,
                "pass_criteria": "All KG-recorded steps complete without errors",
                "fail_criteria": "Any non-skippable step fails",
            },
        }
        plan_data = self._validate_and_cap(plan_data, caps["max_steps"])

        # Check AFTER _validate_and_cap — AI-analyzed stages store action descriptions
        # ("Click Add", "Fill form") that get filtered out by ALLOWED_ACTIONS. If nothing
        # executable survives filtering, the KG has nothing useful — fall through to AI.
        _VACUOUS = {"screenshot", "navigate", "wait_ms", "wait_element", "wait_network", "scroll"}
        validated_meaningful = [
            s for s in plan_data["steps"]
            if (s.get("action") or "").lower() not in _VACUOUS
        ]
        if not validated_meaningful:
            log.warning(
                "KG plan has no executable test steps after action filtering — falling back to AI",
                module=mod.name, workflow_type=workflow_type,
                raw_steps=len(steps), scenario_id=scenario.id,
            )
            return None

        latest = await self._latest_plan_version(scenario.id)
        real_step_count = len(plan_data["steps"])
        plan = ExecutionPlan(
            scenario_id=scenario.id,
            execution_mode=execution_mode,
            plan_data=plan_data,
            ai_reasoning=plan_data["qa_reasoning"],
            semantic_intent=plan_data.get("semantic_intent", {}),
            workflow_stages=self._extract_workflow_stages(plan_data),
            risk_score=self._calculate_risk(plan_data, execution_mode),
            estimated_duration_seconds=real_step_count * 5,
            created_by_model="kg_recorded",
            version=(latest.version + 1 if latest else 1),
        )
        self.db.add(plan)
        await self.db.commit()

        log.info(
            "Plan built from KG recorded workflows — no AI needed",
            plan_id=plan.id,
            module=mod.name,
            workflow_type=workflow_type,
            steps=real_step_count,
            meaningful=len(validated_meaningful),
            kg_workflows=available,
        )
        return plan

    # ─── Helpers ──────────────────────────────────────────────────────────────

    def _build_validation_variant(
        self,
        create_wf: "ApplicationWorkflow",
        start_seq: int,
        budget: int,
    ) -> list[dict]:
        """
        Build a compact required-field validation variant that appends after the
        KG happy-path steps. Finds the Add-button entry point from the recorded
        workflow, re-opens the form, submits empty, and asserts a validation error.

        This is one focused variant: empty-submit → required-field error. It costs
        6 steps and fits within the smallest budget (smoke: 12 total, so budget ≥ 4
        guard in caller ensures we only append when there is room).
        """
        entry = create_wf.entry_point or {}
        add_trigger = entry.get("selector") or entry.get("label") or "Add|New|Create"

        # Find the submit button from the recorded stages
        submit_target = "Save|Submit|Create|Add|OK|Confirm"
        for stage in (create_wf.stages or []):
            t = (stage.get("target") or stage.get("selector") or "").strip()
            if t and any(kw in t.lower() for kw in ("save", "submit", "create", "add", "ok")):
                submit_target = t
                break

        steps: list[dict] = []
        seq = start_seq

        base = {
            "on_fail": "skip",
            "checkpoint": False,
            "business_intent": "Required-field validation variant",
            "phase": "FORM_VALIDATION",
            "timeout_ms": 8000,
        }

        if seq < start_seq + budget:
            steps.append({**base, "seq": seq, "action": "screenshot",
                          "target": "", "value": "",
                          "description": "Baseline before required-field validation test",
                          "timeout_ms": 5000})
            seq += 1

        if seq < start_seq + budget:
            steps.append({**base, "seq": seq, "action": "click",
                          "target": add_trigger, "value": "",
                          "description": "Open Add form for empty-submit validation test"})
            seq += 1

        if seq < start_seq + budget:
            steps.append({**base, "seq": seq, "action": "click",
                          "target": submit_target, "value": "",
                          "description": "Click Save/Submit without filling any fields",
                          "business_intent": "Trigger required-field validation errors"})
            seq += 1

        if seq < start_seq + budget:
            steps.append({**base, "seq": seq,
                          "action": "assert_visible",
                          "target": "error|required|mandatory|cannot be empty|field is required",
                          "value": "",
                          "description": "Verify required-field validation errors are shown",
                          "checkpoint": True,
                          "business_intent": "Validation errors must appear on empty submit"})
            seq += 1

        if seq < start_seq + budget:
            steps.append({**base, "seq": seq, "action": "screenshot",
                          "target": "", "value": "",
                          "description": "Capture validation error state",
                          "timeout_ms": 5000})
            seq += 1

        if seq < start_seq + budget:
            steps.append({**base, "seq": seq, "action": "click",
                          "target": "Cancel|Close|×|✕|Dismiss",
                          "value": "",
                          "description": "Close form to reset state after validation test",
                          "timeout_ms": 5000})

        return steps

    def _validate_and_cap(self, plan_data: dict, max_steps: int) -> dict:
        """Sanitize steps: filter invalid actions, cap count, ensure screenshots."""
        steps = [
            s for s in plan_data.get("steps", [])
            if s.get("action") in ALLOWED_ACTIONS
        ]
        steps = steps[:max_steps]

        # Actions that should never abort a run on failure
        SAFE_ACTIONS = {"screenshot", "wait_ms", "scroll", "wait_element", "wait_network", "hover"}

        for step in steps:
            step.setdefault("timeout_ms", 10000)
            step.setdefault("on_fail", "fail")
            step.setdefault("checkpoint", False)
            step.setdefault("business_intent", "")
            step.setdefault("phase", "")
            if step.get("action") in SAFE_ACTIONS:
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

    def _fallback_plan(self, scenario: Scenario, module_url: str = "/") -> dict:
        nav_url = module_url or "/"
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
                {"action": "navigate", "description": f"Open {scenario.title}", "url": nav_url,
                 "timeout_ms": 15000, "on_fail": "fail", "checkpoint": False,
                 "business_intent": "Navigate to target module", "phase": "NAVIGATE"},
                {"action": "wait_ms", "description": "Wait for Angular SPA to render", "ms": 2000,
                 "timeout_ms": 5000, "on_fail": "skip", "checkpoint": False,
                 "business_intent": "Allow SPA route change to complete", "phase": "NAVIGATE"},
                {"action": "screenshot", "description": "Capture page after navigation",
                 "timeout_ms": 5000, "on_fail": "skip", "checkpoint": True,
                 "business_intent": "Evidence page loaded", "phase": "VERIFY_LOADED"},
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
