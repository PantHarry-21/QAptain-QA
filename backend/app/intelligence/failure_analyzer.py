"""
Failure Intelligence Engine
Converts technical failures into business-meaningful explanations.
Workflow-aware: understands CRUD phases, checkpoint validation results, and business impact.
"""
from __future__ import annotations
import asyncio
from typing import Any

import structlog

from app.intelligence.ai_client import get_ai_client

log = structlog.get_logger()

_STEP_FAILURE_SYSTEM = """You are QAptain's Failure Intelligence Engine.

Explain test failures in BUSINESS terms — never in technical jargon.

NEVER say:
- "NoSuchElementException occurred"
- "Selector not found"
- "XPath timeout"
- "StaleElementReferenceException"

ALWAYS say:
- "The inventory form did not load after clicking 'Add Product'"
- "Login failed — credentials may be incorrect or the session expired"
- "The Delete button was not accessible — user may lack permission"
- "The product name field did not accept the typed value — form binding issue"

WORKFLOW PHASE CONTEXT — use the phase to explain impact:
- CRUD / CREATE: "New record could not be saved"
- CRUD / VERIFY_CREATED: "Record was saved but could not be confirmed in the list"
- CRUD / UPDATE: "Record changes could not be submitted"
- CRUD / VERIFY_UPDATED: "Update completed but the new value is not visible"
- CRUD / DELETE / VERIFY_DELETED: "Record deletion issue — record may still exist"
- AUTH: "User cannot log in — authentication workflow blocked"
- FORM_VALIDATION: "Form validation did not fire as expected"
- ROLE_ACCESS: "Role-based access control behaves differently than expected"
- SEARCH_FILTER: "Search did not return expected results"

Output JSON only:
{
  "title": "Brief human-readable failure title (max 10 words)",
  "explanation": "What happened in business terms (2-3 sentences)",
  "root_causes": [
    {
      "cause": "description",
      "probability": 0.7,
      "category": "ui_rendering|api_failure|auth|data|timing|permission|form_validation|navigation"
    }
  ],
  "workflow_phase_impact": "Which phase/stage of the workflow was interrupted",
  "user_journey_blocked": "What the end user cannot do as a result",
  "recommendations": ["Specific actionable recommendations — max 4"],
  "severity": "low|medium|high|critical",
  "recovery_hint": "One-line hint on how to unblock this"
}"""

_RUN_RCA_SYSTEM = """You are QAptain's Root Cause Analysis Engine.

Analyze test execution results and provide actionable business-level insights.

For the workflow type, focus on:
- CRUD: Did create/verify/update/delete phases all pass? Which broke first?
- AUTH: Was login the root cause or did it break later?
- FORM_VALIDATION: Did the form fire the right validation messages?
- ROLE_ACCESS: Did the access restriction work as expected?
- SEARCH_FILTER: Did the search return expected results?
- BUSINESS_WORKFLOW: Which stage of the multi-step process failed?

CHECKPOINT RESULTS are AI-validated business outcomes — they are more important than
individual step failures because they represent actual business behavior, not UI mechanics.
If a checkpoint failed, it means a real business outcome did not occur.

Output JSON only:
{
  "overall_health": "1-2 sentence summary of what passed and what failed in business terms",
  "critical_failures": ["The most important things that broke — in business terms, max 3"],
  "root_causes": [
    {
      "cause": "description",
      "affected_steps": ["step descriptions"],
      "probability": 0.8,
      "category": "ui|api|auth|data|timing|permission"
    }
  ],
  "workflow_analysis": {
    "phases_completed": ["phases that fully passed"],
    "phases_failed": ["phases that had failures"],
    "first_failure_phase": "which phase broke first (or null)",
    "workflow_completion_percent": 0
  },
  "checkpoint_summary": "What AI checkpoint validations found — did business outcomes occur?",
  "patterns": ["patterns across failures, e.g. 'all form submissions timed out'"],
  "recommendations": ["specific actions to fix issues — max 5"],
  "quality_score": 0,
  "business_impact": "What real users cannot do because of these failures"
}"""


class FailureAnalyzer:
    def __init__(self):
        self.ai = get_ai_client()

    async def analyze(
        self,
        failed_step: dict[str, Any],
        execution_context: dict[str, Any],
        error_details: dict[str, Any],
    ) -> dict[str, Any]:
        """Analyze a single step failure with full business and workflow context."""
        checkpoint_ctx = ""
        for cp in execution_context.get("checkpoint_results", [])[-3:]:
            status = "PASSED" if cp.get("passed") else "FAILED"
            checkpoint_ctx += f"\n  [{status}] {cp.get('description', '?')}: {cp.get('evidence', '')[:100]}"
        if checkpoint_ctx:
            checkpoint_ctx = "Recent checkpoints:" + checkpoint_ctx

        user_prompt = f"""FAILED STEP:
Action: {failed_step.get('action', '?')}
Description: {failed_step.get('description', '?')}
Target: {failed_step.get('target', 'N/A')}
Business intent: {failed_step.get('business_intent', 'N/A')}
Phase: {failed_step.get('phase', 'N/A')}

ERROR DETAILS:
Type: {error_details.get('type', 'Unknown')}
Message: {error_details.get('message', 'No details')[:400]}
Healing Attempts: {error_details.get('healing_attempts', 0)}

WORKFLOW CONTEXT:
Workflow type: {execution_context.get('workflow_type', 'Unknown')}
Workflow: {execution_context.get('workflow', 'Unknown')}
Current phase: {execution_context.get('current_phase', failed_step.get('phase', 'Unknown'))}
Recent actions: {', '.join(execution_context.get('recent_actions', [])[-4:])}
Page state: {execution_context.get('page_state', 'Unknown')}
Scenario: {execution_context.get('scenario_title', 'Unknown')}
{checkpoint_ctx}"""

        try:
            response = await asyncio.wait_for(
                self.ai.complete(
                    system=_STEP_FAILURE_SYSTEM,
                    user=user_prompt,
                    fast=True,
                    json_mode=True,
                    max_tokens=800,
                ),
                timeout=15.0,
            )
            return response.json()
        except (Exception, asyncio.CancelledError) as e:
            log.error("Failure analysis failed", error=str(e))
            return self._simple_analysis(failed_step, error_details)

    async def analyze_run(
        self,
        run_summary: dict[str, Any],
        failed_steps: list[dict[str, Any]],
        checkpoint_results: list[dict[str, Any]] | None = None,
        workflow_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Post-run root cause analysis.
        Includes workflow-type awareness and AI checkpoint validation results.
        """
        cp_results = checkpoint_results or []
        wctx = workflow_context or {}
        failed_checkpoints = [cp for cp in cp_results if not cp.get("passed")]

        if not failed_steps and not failed_checkpoints:
            phases = wctx.get("phases_completed", [])
            return {
                "overall_health": "All steps and checkpoint validations passed successfully.",
                "critical_failures": [],
                "root_causes": [],
                "workflow_analysis": {
                    "phases_completed": phases,
                    "phases_failed": [],
                    "first_failure_phase": None,
                    "workflow_completion_percent": 100,
                },
                "checkpoint_summary": (
                    f"{len(cp_results)} checkpoint(s) validated — all passed."
                    if cp_results else "No checkpoint validations recorded."
                ),
                "patterns": [],
                "recommendations": [],
                "quality_score": 100,
                "business_impact": "None — all workflows completed successfully.",
            }

        cp_lines = []
        for cp in cp_results:
            status = "PASSED" if cp.get("passed") else "FAILED"
            confidence = cp.get("confidence", 0)
            cp_lines.append(
                f"  [{status} {confidence:.0%}] {cp.get('validation_type', '?')}: "
                f"{cp.get('description', '?')} — {cp.get('evidence', '')[:100]}"
            )
        cp_text = "\n".join(cp_lines) if cp_lines else "No checkpoint validations recorded"

        user_prompt = f"""RUN SUMMARY:
Scenario: {run_summary.get('scenario_title', 'Unknown')}
Total Steps: {run_summary.get('total_steps', 0)}
Passed: {run_summary.get('passed', 0)}
Failed: {run_summary.get('failed', 0)}
Self-healed (auto-corrected): {run_summary.get('healed', 0)}
Workflow type: {wctx.get('workflow_type', run_summary.get('workflow_type', 'Unknown'))}
Workflow: {run_summary.get('workflow', 'Unknown')}
Phases completed: {', '.join(wctx.get('phases_completed', []) or ['Unknown'])}
Phases with failures: {', '.join(wctx.get('phases_failed', []) or ['None'])}

CHECKPOINT VALIDATION RESULTS (AI-validated business outcomes):
{cp_text}

FAILED STEPS:
{_format_failed_steps(failed_steps)}

Provide comprehensive root cause analysis."""

        try:
            response = await asyncio.wait_for(
                self.ai.complete(
                    system=_RUN_RCA_SYSTEM,
                    user=user_prompt,
                    json_mode=True,
                    max_tokens=1500,
                ),
                timeout=30.0,
            )
            return response.json()
        except (Exception, asyncio.CancelledError) as e:
            log.error("Run RCA failed", error=str(e))
            total_failed = run_summary.get("failed", 0)
            return {
                "overall_health": (
                    f"Run completed with {total_failed} failure(s) across "
                    f"{run_summary.get('total_steps', 0)} steps."
                ),
                "critical_failures": [s.get("description", "Unknown") for s in failed_steps[:3]],
                "root_causes": [],
                "workflow_analysis": {
                    "phases_completed": wctx.get("phases_completed", []),
                    "phases_failed": wctx.get("phases_failed", []),
                    "first_failure_phase": None,
                    "workflow_completion_percent": max(0, 100 - total_failed * 20),
                },
                "checkpoint_summary": f"{len(cp_results)} checkpoint(s) evaluated.",
                "patterns": [],
                "recommendations": ["Review failed steps and check application state"],
                "quality_score": max(0, 100 - total_failed * 20),
                "business_impact": "Some workflows may be blocked — review failed steps.",
            }

    def _simple_analysis(self, step: dict, error: dict) -> dict:
        action = step.get("action", "unknown")
        phase = step.get("phase", "")
        business_intent = step.get("business_intent", "")
        return {
            "title": f"Failed: {step.get('description', f'{action}')}"[:60],
            "explanation": (
                f"The step '{step.get('description', action)}' could not be completed"
                + (f" during the {phase} phase" if phase else "")
                + (f". Intent: {business_intent}" if business_intent else ".")
            ),
            "root_causes": [
                {"cause": "Element not found or not interactable", "probability": 0.6, "category": "ui_rendering"},
                {"cause": "Page not in expected state", "probability": 0.3, "category": "timing"},
            ],
            "workflow_phase_impact": phase or "Unknown phase",
            "user_journey_blocked": business_intent or "Workflow step could not complete",
            "recommendations": [
                "Verify the target element exists on the current page",
                "Check application logs for errors",
                "Confirm the previous step completed successfully",
            ],
            "severity": "high" if step.get("on_fail") == "fail" else "medium",
            "recovery_hint": "Check if the element exists and the page is in the expected state.",
        }


def _format_failed_steps(steps: list[dict]) -> str:
    lines = []
    for i, s in enumerate(steps[:10], 1):
        phase = s.get("phase", "")
        intent = s.get("business_intent", "")
        lines.append(
            f"{i}. [{s.get('action', '?')}] {s.get('description', '?')}"
            + (f" (phase: {phase})" if phase else "")
            + (f" — {intent}" if intent else "")
        )
        if s.get("error_message"):
            lines.append(f"   Error: {s['error_message'][:200]}")
    return "\n".join(lines)
