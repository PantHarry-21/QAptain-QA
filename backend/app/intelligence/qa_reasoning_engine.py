"""
QA Reasoning Engine
The AI brain of QAptain's test executor.

Transforms a scenario title + description into a comprehensive, intelligent
execution plan — exactly as a senior human QA engineer would design it.

AI is called ONCE per scenario. The plan it returns is then executed
deterministically by the Selenium layer.

Workflow Classification:
  CRUD             → Create + Verify + Update + Verify + Delete + Verify + Form Validation
  AUTH             → Valid login + Invalid credentials + Empty fields + Session check
  ROLE_ACCESS      → Login as allowed user → verify access + Login as restricted → verify denied
  FORM_VALIDATION  → Empty submit + Invalid data + Valid submit + Error message verification
  SEARCH_FILTER    → Search valid term + verify results + search invalid + verify no-results + clear
  NAVIGATION       → Navigate to module + verify key page elements loaded
  BUSINESS_WORKFLOW→ Custom multi-step business process
"""
from __future__ import annotations
import asyncio
import json
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import (
    Application, ApplicationModule, ApplicationPage, SemanticElement, Scenario,
)
from app.intelligence.ai_client import get_ai_client

log = structlog.get_logger()

# ─── Prompt ───────────────────────────────────────────────────────────────────

QA_SYSTEM_PROMPT = """You are QAptain's AI QA Intelligence Engine — a senior QA engineer with deep expertise in enterprise application testing.

MISSION: Analyze the test scenario and generate a COMPLETE, INTELLIGENT execution plan with phases, validations, and edge cases.

════════════════════════════════════════
WORKFLOW TYPE CLASSIFICATION
════════════════════════════════════════
Classify the scenario as ONE of:

CRUD        — "test CRUD", "all operations", "create/edit/delete", "add and verify", "test [module]"
              → ALL 8 phases: SETUP → FORM_VALIDATION → CREATE → VERIFY_CREATED → UPDATE → VERIFY_UPDATED → DELETE → VERIFY_DELETED

AUTH        — "login", "sign in", "authentication", "credentials", "session", "logout"
              → VALID_LOGIN + INVALID_CREDENTIALS + EMPTY_SUBMIT

ROLE_ACCESS — "access", "permission", "role", "allowed", "restricted", "unauthorized", "only X can"
              → LOGIN_ALLOWED + VERIFY_ACCESS + LOGIN_RESTRICTED + VERIFY_DENIED

FORM_VALIDATION — "validation", "required fields", "error messages", "mandatory", "invalid input"
              → SUBMIT_EMPTY + VERIFY_FIELD_ERRORS + FILL_INVALID_DATA + VERIFY_FORMAT_ERRORS + FILL_VALID + VERIFY_SUCCESS

SEARCH_FILTER — "search", "filter", "find records", "query", "list"
              → NAVIGATE + SEARCH_VALID + VERIFY_FILTERED + SEARCH_EMPTY + VERIFY_NO_RESULTS + CLEAR + VERIFY_RESTORED

NAVIGATION  — "navigate", "access module", "open page", "go to", "can access"
              → NAVIGATE + VERIFY_PAGE_LOADED + CHECK_KEY_ELEMENTS

BUSINESS_WORKFLOW — any specific multi-step business process not fitting above
              → Each step of the described workflow

════════════════════════════════════════
CRUD EXPANSION (AUTO-GENERATE ALL PHASES)
════════════════════════════════════════
When workflow_type = CRUD, generate ALL these phases in this EXACT ORDER:

PHASE 1 — SETUP:
  screenshot (initial state)
  navigate to module URL

PHASE 2 — FORM_VALIDATION (negative test):
  screenshot
  click "Add/Create/New" button
  click "Save/Submit" WITHOUT filling fields
  assert_visible required field error messages
  screenshot (error state captured)

PHASE 3 — CREATE (happy path):
  fill all required fields with realistic test data
  screenshot (before submit)
  click "Save/Submit/Create"
  wait_network
  assert_visible success message or new record name
  screenshot (after create)

PHASE 4 — VERIFY_CREATED:
  assert_visible the newly created record in the list/table
  screenshot (record visible in list)
  [checkpoint: record_created]

PHASE 5 — UPDATE:
  find the created record and click "Edit/Pencil/Modify"
  clear the field being changed
  fill new/updated value
  screenshot (before save)
  click "Save/Update"
  wait_network
  assert_visible updated value
  screenshot (after update)

PHASE 6 — VERIFY_UPDATED:
  assert the updated value is visible in list or detail
  [checkpoint: value_updated]

PHASE 7 — DELETE:
  find the record and click "Delete/Remove/Trash"
  assert_visible confirmation dialog or prompt
  click "Confirm/Yes/OK" to confirm deletion
  wait_network
  screenshot (after delete)

PHASE 8 — VERIFY_DELETED:
  assert_not_text the deleted record's name (it should be gone)
  screenshot (final state — list without deleted record)
  [checkpoint: record_deleted]

════════════════════════════════════════
SEMANTIC TARGET RULES
════════════════════════════════════════
- Use what a human QA engineer would call the element
- GOOD: "Add Employee button", "First Name field", "Save button", "Delete confirmation dialog"
- BAD: "#btn-save", "input[name='fname']", "//button[@id='del']"
- For form fields use the label text: "First Name", "Email Address", "Phone Number"
- For buttons use visible button text: "Save", "Cancel", "Confirm Delete"
- For navigation use menu item text: "Employees", "Products", "Settings"

════════════════════════════════════════
STEP WRITING RULES
════════════════════════════════════════
- FIRST step = screenshot (initial state)
- LAST step = screenshot (final evidence)
- After every form submission: wait_network THEN assert_visible success
- After delete: assert_not_text the deleted item
- After navigation: assert_visible key element proving correct page loaded
- Set checkpoint: true on create/update/delete verification steps
- Use on_fail: "skip" for screenshots, on_fail: "fail" for all assertions
- set business_intent to explain WHY this step exists (what it validates)

════════════════════════════════════════
OUTPUT — Return ONLY this JSON, no markdown
════════════════════════════════════════
{
  "workflow": "SCREAMING_SNAKE_CASE_NAME",
  "workflow_type": "CRUD|AUTH|ROLE_ACCESS|FORM_VALIDATION|SEARCH_FILTER|NAVIGATION|BUSINESS_WORKFLOW",
  "goal": "One sentence: what business behavior this test proves",
  "qa_reasoning": "3-5 sentences: what you understood from the scenario, testing approach chosen, validations included, edge cases covered",
  "test_strategy": {
    "phases": ["SETUP", "FORM_VALIDATION", "CREATE", ...],
    "primary_operation": "main operation under test",
    "validations": ["list of what is being validated"],
    "negative_tests": ["negative/edge cases included"],
    "edge_cases": ["boundary conditions tested"]
  },
  "steps": [
    {
      "action": "screenshot|navigate|click|fill|clear|select|key_press|assert_visible|assert_text|assert_not_text|assert_url|wait_network|wait_element|wait_ms|scroll",
      "description": "Business-readable: what this step does",
      "target": "Semantic label",
      "value": "",
      "url": "",
      "text": "",
      "key": "",
      "timeout_ms": 10000,
      "on_fail": "fail",
      "checkpoint": false,
      "business_intent": "What this validates / what would fail if this is wrong",
      "phase": "SETUP|FORM_VALIDATION|CREATE|VERIFY_CREATED|UPDATE|VERIFY_UPDATED|DELETE|VERIFY_DELETED|etc"
    }
  ],
  "checkpoint_validations": [
    {
      "after_description": "exact step description after which this fires",
      "validation_type": "record_created|record_deleted|value_updated|form_success|form_error|auth_success|access_denied|navigation_success",
      "description": "Semantic validation: what to check",
      "semantic_check": "Visible evidence confirming the outcome (e.g. 'Employee name appears in the data table row', 'Success toast visible at top of page')",
      "critical": true
    }
  ],
  "success_criteria": ["Business-level pass conditions"],
  "failure_indicators": ["Business-level fail indicators"],
  "semantic_intent": {
    "module": "module name being tested",
    "operation": "create|read|update|delete|login|validate|navigate|search|authorize",
    "pass_criteria": "Business pass condition",
    "fail_criteria": "Business fail condition"
  }
}"""


# ─── Engine ───────────────────────────────────────────────────────────────────

class QAReasoningEngine:
    """
    Builds a comprehensive QA execution plan from a scenario using AI reasoning.

    Performance design:
    - AI called ONCE per scenario (not per step)
    - Application memory loaded before reasoning (modules, selectors, URLs)
    - Plan cached as ExecutionPlan record — reused on re-runs unless force_regenerate
    """

    # Max steps by mode (CRUD generates many steps — allow headroom)
    MODE_MAX_STEPS = {
        "smoke":            12,
        "functional":       35,
        "validation_heavy": 55,
        "regression":       80,
        "workflow_heavy":   100,
    }

    def __init__(self, db: AsyncSession):
        self.db = db
        self.ai = get_ai_client()

    async def build_plan(
        self,
        scenario: Scenario,
        execution_mode: str = "functional",
    ) -> dict[str, Any]:
        """
        Core reasoning method.
        Returns a rich plan dict ready to be stored as ExecutionPlan.plan_data.
        """
        max_steps = self.MODE_MAX_STEPS.get(execution_mode, 35)
        app_context = await self._load_application_context(scenario)

        user_prompt = self._build_user_prompt(scenario, app_context, max_steps)

        log.info("QA reasoning started",
            scenario_id=scenario.id,
            title=scenario.title[:60],
            mode=execution_mode,
        )

        plan_data: dict | None = None

        # Two attempts: json_mode first, raw second (Azure doesn't always support json_mode)
        for attempt, use_json in enumerate([True, False], 1):
            try:
                extra = "" if attempt == 1 else (
                    "\n\nIMPORTANT: Return ONLY the raw JSON object. "
                    "No markdown fences, no code blocks, no explanation."
                )
                response = await asyncio.wait_for(
                    self.ai.complete(
                        system=QA_SYSTEM_PROMPT,
                        user=user_prompt + extra,
                        json_mode=use_json,
                        max_tokens=3500,
                    ),
                    timeout=60.0,
                )
                if response.content.strip():
                    plan_data = response.json()
                    break
            except Exception as e:
                log.warning("QA reasoning attempt failed", attempt=attempt, error=str(e))
                if attempt == 2:
                    log.error("QA reasoning failed after 2 attempts — using fallback")
                    return self._fallback_plan(scenario)

        if not plan_data:
            return self._fallback_plan(scenario)

        # Post-process: sanitize + cap + enforce screenshots
        plan_data = self._post_process(plan_data, max_steps)

        log.info("QA reasoning complete",
            workflow=plan_data.get("workflow"),
            workflow_type=plan_data.get("workflow_type"),
            steps=len(plan_data.get("steps", [])),
            checkpoints=len(plan_data.get("checkpoint_validations", [])),
        )

        return plan_data

    # ─── Context Loading ──────────────────────────────────────────────────────

    async def _load_application_context(self, scenario: Scenario) -> dict[str, Any]:
        """Load application memory: modules, explored pages, known selectors."""
        # Application
        app_result = await self.db.execute(
            select(Application).where(Application.id == scenario.application_id)
        )
        app = app_result.scalar_one_or_none()

        # All modules
        mods_result = await self.db.execute(
            select(ApplicationModule).where(
                ApplicationModule.application_id == scenario.application_id
            )
        )
        modules = mods_result.scalars().all()

        # Module for this scenario (if set)
        scenario_module = None
        if scenario.module_id:
            for m in modules:
                if m.id == scenario.module_id:
                    scenario_module = m
                    break

        # Semantic elements from the scenario's module (selectors, labels)
        known_elements: list[dict] = []
        if scenario.module_id:
            el_result = await self.db.execute(
                select(SemanticElement)
                .join(ApplicationPage, SemanticElement.page_id == ApplicationPage.id)
                .where(ApplicationPage.module_id == scenario.module_id)
                .order_by(SemanticElement.confidence.desc())
                .limit(20)
            )
            for el in el_result.scalars().all():
                if el.semantic_label:
                    known_elements.append({
                        "label": el.semantic_label,
                        "type": el.element_type,
                        "css": el.css_selector or "",
                    })

        # Pages for the scenario module
        module_pages: list[dict] = []
        if scenario.module_id:
            pages_result = await self.db.execute(
                select(ApplicationPage)
                .where(ApplicationPage.module_id == scenario.module_id)
                .limit(5)
            )
            for p in pages_result.scalars().all():
                module_pages.append({
                    "title": p.title,
                    "url": p.url,
                    "type": p.page_type,
                    "forms": [f.get("name", "") for f in (p.forms or [])[:3]],
                    "tables": [t.get("name", "") for t in (p.tables or [])[:2]],
                })

        return {
            "app_name": app.name if app else "Application",
            "app_description": app.description if app else "",
            "base_url": app.base_url if app else "",
            "scenario_module": {
                "name": scenario_module.name if scenario_module else "",
                "url": scenario_module.url_pattern if scenario_module else "",
                "description": scenario_module.description if scenario_module else "",
            } if scenario_module else None,
            "all_modules": [
                {"name": m.name, "url": m.url_pattern or ""}
                for m in modules[:10]
            ],
            "known_elements": known_elements[:15],
            "module_pages": module_pages,
        }

    # ─── Prompt Construction ──────────────────────────────────────────────────

    def _build_user_prompt(
        self, scenario: Scenario, ctx: dict[str, Any], max_steps: int
    ) -> str:
        module_block = ""
        if ctx.get("scenario_module"):
            m = ctx["scenario_module"]
            module_block = f"""
TARGET MODULE: {m['name']}
Module URL: {m['url']}
Module Description: {m['description'] or 'N/A'}
"""

        elements_block = ""
        if ctx.get("known_elements"):
            elements_block = "\nKNOWN UI ELEMENTS (from exploration memory):\n" + "\n".join(
                f"  - [{e['type']}] {e['label']}"
                for e in ctx["known_elements"]
            )

        pages_block = ""
        if ctx.get("module_pages"):
            pages_block = "\nEXPLORED PAGES:\n" + "\n".join(
                f"  - {p['title']} ({p['url']}) forms={p['forms']} tables={p['tables']}"
                for p in ctx["module_pages"]
            )

        return f"""APPLICATION: {ctx['app_name']}
Description: {ctx['app_description'] or 'Enterprise business application'}
Base URL: {ctx['base_url']}
{module_block}
SCENARIO TITLE: {scenario.title}
SCENARIO DESCRIPTION: {scenario.description or 'N/A'}
Priority: {scenario.priority.value if scenario.priority else 'MEDIUM'}
Execution max steps: {max_steps}

ALL MODULES:
{json.dumps(ctx['all_modules'], indent=1)}
{elements_block}
{pages_block}

Generate the comprehensive QA execution plan for this scenario.
Remember: think and reason like a senior QA engineer.
Use semantic targets from the known UI elements where available.
For CRUD scenarios: generate ALL 8 phases (SETUP → FORM_VALIDATION → CREATE → VERIFY_CREATED → UPDATE → VERIFY_UPDATED → DELETE → VERIFY_DELETED)."""

    # ─── Post-processing ──────────────────────────────────────────────────────

    ALLOWED_ACTIONS = frozenset([
        "navigate", "click", "fill", "clear", "select", "key_press",
        "assert_visible", "assert_text", "assert_not_text", "assert_url",
        "assert_count", "wait_network", "wait_element", "wait_ms",
        "scroll", "upload", "screenshot", "assert_ai_semantic",
    ])

    def _post_process(self, plan: dict, max_steps: int) -> dict:
        steps = plan.get("steps", [])

        # Filter unknown actions
        steps = [s for s in steps if s.get("action") in self.ALLOWED_ACTIONS]

        # Cap steps
        steps = steps[:max_steps]

        # Ensure each step has required fields
        for i, step in enumerate(steps):
            step.setdefault("timeout_ms", 10000)
            step.setdefault("on_fail", "fail")
            step.setdefault("checkpoint", False)
            step.setdefault("business_intent", "")
            step.setdefault("phase", "")
            step.setdefault("description", f"{step.get('action', 'step')} #{i+1}")
            if step.get("action") == "screenshot":
                step["on_fail"] = "skip"

        # Guarantee first + last screenshots
        if steps and steps[0].get("action") != "screenshot":
            steps.insert(0, {
                "action": "screenshot",
                "description": "Capture initial page state",
                "timeout_ms": 5000,
                "on_fail": "skip",
                "checkpoint": False,
                "business_intent": "Baseline evidence before test starts",
                "phase": "SETUP",
            })
        if steps and steps[-1].get("action") != "screenshot":
            steps.append({
                "action": "screenshot",
                "description": "Capture final page state as test evidence",
                "timeout_ms": 5000,
                "on_fail": "skip",
                "checkpoint": False,
                "business_intent": "Final evidence after all test steps",
                "phase": "TEARDOWN",
            })

        plan["steps"] = steps

        # Ensure checkpoint_validations is a list
        if "checkpoint_validations" not in plan or not isinstance(plan["checkpoint_validations"], list):
            plan["checkpoint_validations"] = []

        # Ensure semantic_intent
        plan.setdefault("semantic_intent", {})
        plan.setdefault("qa_reasoning", "")
        plan.setdefault("test_strategy", {})
        plan.setdefault("workflow_type", "BUSINESS_WORKFLOW")
        plan.setdefault("goal", scenario_title_to_goal(plan.get("workflow", "")))
        plan.setdefault("success_criteria", [])
        plan.setdefault("failure_indicators", [])

        return plan

    # ─── Fallback ─────────────────────────────────────────────────────────────

    def _fallback_plan(self, scenario: Scenario) -> dict:
        return {
            "workflow": "BASIC_NAVIGATE",
            "workflow_type": "NAVIGATION",
            "goal": f"Verify {scenario.title} works as expected",
            "qa_reasoning": "Fallback plan — AI reasoning unavailable. Basic navigation and page load verification.",
            "test_strategy": {
                "phases": ["NAVIGATE", "VERIFY_LOADED"],
                "primary_operation": "navigate",
                "validations": ["Page loads without errors"],
                "negative_tests": [],
                "edge_cases": [],
            },
            "steps": [
                {"action": "screenshot", "description": "Capture initial state", "timeout_ms": 5000,
                 "on_fail": "skip", "checkpoint": False, "business_intent": "Initial evidence", "phase": "SETUP"},
                {"action": "navigate", "description": "Open application", "url": "/",
                 "timeout_ms": 15000, "on_fail": "fail", "checkpoint": False,
                 "business_intent": "Navigate to application", "phase": "NAVIGATE"},
                {"action": "assert_visible", "description": "Verify page loaded", "text": "",
                 "target": "page body", "timeout_ms": 10000, "on_fail": "fail", "checkpoint": True,
                 "business_intent": "Application responds and loads", "phase": "VERIFY_LOADED"},
                {"action": "screenshot", "description": "Capture final state", "timeout_ms": 5000,
                 "on_fail": "skip", "checkpoint": False, "business_intent": "Final evidence", "phase": "TEARDOWN"},
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


def scenario_title_to_goal(workflow_name: str) -> str:
    return workflow_name.replace("_", " ").title()
