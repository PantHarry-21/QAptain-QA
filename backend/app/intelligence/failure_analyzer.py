"""
Failure Intelligence Engine
Converts technical failures into business-meaningful explanations with root cause analysis.
"""
from __future__ import annotations
from typing import Any

import structlog

from app.intelligence.ai_client import get_ai_client

log = structlog.get_logger()

SYSTEM_PROMPT = """You are QAptain's Failure Intelligence Engine.

When given a test execution failure, provide:
1. A business-meaningful explanation (NOT technical jargon)
2. Root cause analysis with probabilities
3. Recommended actions

NEVER say things like:
- "NoSuchElementException occurred"
- "Selector not found"
- "XPath timeout"

ALWAYS say things like:
- "The inventory form did not load after clicking 'Add Product'"
- "Login failed — credentials may be incorrect or session expired"
- "The approval button was not accessible — likely a permission issue"

Output JSON:
{
  "title": "Brief human-readable failure title",
  "explanation": "What happened in business terms",
  "root_causes": [
    {"cause": "description", "probability": 0.7, "category": "ui_rendering|api_failure|auth|data|timing|permission"}
  ],
  "affected_workflow": "Which business workflow was interrupted",
  "recommendations": ["Specific actionable recommendations"],
  "severity": "low|medium|high|critical"
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
        user_prompt = f"""
FAILED STEP:
Action: {failed_step.get('action')}
Description: {failed_step.get('description')}
Target: {failed_step.get('target', 'N/A')}

ERROR DETAILS:
Type: {error_details.get('type', 'Unknown')}
Message: {error_details.get('message', 'No details')}
Healing Attempts: {error_details.get('healing_attempts', 0)}

EXECUTION CONTEXT:
Workflow: {execution_context.get('workflow', 'Unknown')}
Stage: {execution_context.get('current_stage', 'Unknown')}
Previous Steps: {execution_context.get('previous_steps_summary', 'N/A')}
Page State: {execution_context.get('page_state', 'Unknown')}
"""

        try:
            response = await self.ai.complete(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                fast=True,
                json_mode=True,
                max_tokens=1000,
            )
            return response.json()
        except Exception as e:
            log.error("Failure analysis failed", error=str(e))
            return self._simple_analysis(failed_step, error_details)

    async def analyze_run(
        self,
        run_summary: dict[str, Any],
        failed_steps: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Generate post-run root cause analysis for the full report."""
        if not failed_steps:
            return {
                "overall_health": "Execution completed successfully with no failures.",
                "root_causes": [],
                "patterns": [],
                "recommendations": [],
            }

        user_prompt = f"""
RUN SUMMARY:
Total Steps: {run_summary.get('total_steps')}
Passed: {run_summary.get('passed')}
Failed: {run_summary.get('failed')}
Healed: {run_summary.get('healed')}
Scenario: {run_summary.get('scenario_title')}

FAILED STEPS:
{_format_failed_steps(failed_steps)}

Provide comprehensive root cause analysis for this test run.

Output JSON:
{{
  "overall_health": "summary sentence",
  "root_causes": [{{"cause": "...", "affected_steps": [...], "probability": 0.8}}],
  "patterns": ["any patterns observed across failures"],
  "workflow_interruption_analysis": "where the workflow broke and why",
  "recommendations": ["specific actions to fix issues"],
  "quality_score": 0-100
}}"""

        try:
            response = await self.ai.complete(
                system="You are QAptain's Root Cause Analysis Engine. Analyze test execution failures and provide actionable insights. Output only valid JSON.",
                user=user_prompt,
                json_mode=True,
                max_tokens=2000,
            )
            return response.json()
        except Exception as e:
            log.error("Run RCA failed", error=str(e))
            return {
                "overall_health": f"Run completed with {run_summary.get('failed', 0)} failures.",
                "root_causes": [],
                "patterns": [],
                "recommendations": ["Review failed steps and check application state"],
                "quality_score": max(0, 100 - (run_summary.get('failed', 0) * 20)),
            }

    def _simple_analysis(self, step: dict, error: dict) -> dict:
        action = step.get("action", "unknown")
        target = step.get("target", "unknown element")
        return {
            "title": f"Failed to {action} on {target}",
            "explanation": f"The test could not complete the '{step.get('description', action)}' step.",
            "root_causes": [
                {"cause": "Element not found or not interactable", "probability": 0.6, "category": "ui_rendering"},
                {"cause": "Page did not load correctly", "probability": 0.3, "category": "timing"},
            ],
            "affected_workflow": "Unknown",
            "recommendations": ["Verify the element exists on the page", "Check application logs"],
            "severity": "medium",
        }


def _format_failed_steps(steps: list[dict]) -> str:
    lines = []
    for i, s in enumerate(steps[:10], 1):
        lines.append(f"{i}. [{s.get('action', '?')}] {s.get('description', '?')}")
        if s.get("error_message"):
            lines.append(f"   Error: {s['error_message'][:200]}")
    return "\n".join(lines)
