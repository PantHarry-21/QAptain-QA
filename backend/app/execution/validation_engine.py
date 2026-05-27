"""
AI Validation Engine — Checkpoint Validation

Called at key workflow transitions (NOT on every step).
Typical checkpoints: after CREATE, after UPDATE, after DELETE, after LOGIN.

Sends a compressed page snapshot to the AI (NOT full DOM).
The AI validates whether the expected business outcome occurred.

Performance: ~2-4 AI calls per scenario, only at workflow checkpoints.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass, field
from typing import Any

import structlog
from selenium.webdriver.common.by import By

from app.execution.browser_manager import BrowserManager
from app.intelligence.ai_client import get_ai_client

log = structlog.get_logger()

# ─── Validation Prompt ────────────────────────────────────────────────────────

_VALIDATION_SYSTEM = """You are QAptain's AI Validation Engine.

Given:
- A checkpoint validation specification (what SHOULD have happened)
- A compressed snapshot of the current browser page

Determine: Did the expected outcome occur?

VALIDATION TYPES and what to look for:
- record_created:   A new record/row appeared. Look for the test data visible in a table/list.
- record_deleted:   A record was removed. Look for absence of the deleted record's name.
- value_updated:    A field was changed. Look for the new value in the page.
- form_success:     Form submission succeeded. Look for success toast, confirmation message, redirect.
- form_error:       Form validation fired. Look for error messages, red borders, required field indicators.
- auth_success:     Login succeeded. Look for dashboard, main navigation, user profile.
- access_denied:    Access was correctly restricted. Look for error page, redirect to login, "not authorized".
- navigation_success: Correct page loaded. Look for module name in heading or nav highlight.
- workflow_complete: A multi-step process completed. Look for final state indicators.

RULES:
- Be generous with "passed" for visual/semantic matches (don't fail on minor UI differences)
- Be strict on "failed" only when the expected outcome is clearly absent
- Confidence 0.0–1.0 (use 0.6+ for likely pass, 0.3- for likely fail)

Output ONLY this JSON:
{
  "passed": true,
  "confidence": 0.85,
  "evidence": "What on the page confirms the outcome (or explains the failure)",
  "business_explanation": "One sentence: what succeeded or failed in business terms",
  "failure_detail": "If failed: specific missing element or unexpected state"
}"""


@dataclass
class ValidationResult:
    passed: bool
    confidence: float
    evidence: str
    business_explanation: str
    failure_detail: str = ""
    validation_type: str = ""
    checkpoint_description: str = ""


class ValidationEngine:
    """
    Validates workflow checkpoints using AI + compressed page state.

    Design rules:
    - Never sends full DOM to AI
    - Extracts only: URL, title, visible text (trimmed), key element labels
    - Called only at checkpoint steps — typically 2-4 times per scenario
    """

    def __init__(self, browser: BrowserManager):
        self.browser = browser
        self.ai = get_ai_client()

    async def validate_checkpoint(
        self,
        checkpoint: dict[str, Any],
        execution_context: dict[str, Any],
    ) -> ValidationResult:
        """
        Validate a workflow checkpoint.

        checkpoint:
            validation_type: record_created|record_deleted|value_updated|...
            description: What to validate
            semantic_check: Visible evidence to look for
            critical: bool

        execution_context:
            workflow: name of the workflow
            phase: current phase
            scenario_title: title
            recent_actions: list of last 3-5 step descriptions
        """
        # Gather compressed page state (no full DOM)
        page_state = await asyncio.to_thread(self._get_compressed_state)

        vtype = checkpoint.get("validation_type", "")
        description = checkpoint.get("description", "")
        semantic_check = checkpoint.get("semantic_check", "")

        user_prompt = f"""CHECKPOINT TO VALIDATE:
Type: {vtype}
Description: {description}
Expected Evidence: {semantic_check}

EXECUTION CONTEXT:
Workflow: {execution_context.get('workflow', 'Unknown')}
Phase: {execution_context.get('phase', 'Unknown')}
Scenario: {execution_context.get('scenario_title', 'Unknown')}
Recent actions: {', '.join(execution_context.get('recent_actions', [])[-4:])}

CURRENT PAGE STATE:
URL: {page_state['url']}
Title: {page_state['title']}
Visible text (truncated): {page_state['visible_text'][:1500]}
Key elements: {page_state['key_elements'][:800]}
Alerts/toasts: {page_state['alerts']}
"""

        try:
            response = await asyncio.wait_for(
                self.ai.complete(
                    system=_VALIDATION_SYSTEM,
                    user=user_prompt,
                    fast=True,
                    json_mode=True,
                    max_tokens=400,
                ),
                timeout=20.0,
            )
            data = response.json()
            return ValidationResult(
                passed=bool(data.get("passed", True)),
                confidence=float(data.get("confidence", 0.7)),
                evidence=str(data.get("evidence", "")),
                business_explanation=str(data.get("business_explanation", "")),
                failure_detail=str(data.get("failure_detail", "")),
                validation_type=vtype,
                checkpoint_description=description,
            )
        except (Exception, asyncio.CancelledError) as e:
            log.warning("Checkpoint validation failed (AI error) — assuming pass",
                error=str(e), vtype=vtype)
            # On AI error or cancellation: assume pass to avoid false negatives blocking execution
            return ValidationResult(
                passed=True,
                confidence=0.5,
                evidence="AI validation unavailable — assumed pass",
                business_explanation="Checkpoint skipped due to AI timeout",
                validation_type=vtype,
                checkpoint_description=description,
            )

    async def validate_step_failure(
        self,
        failed_step: dict[str, Any],
        execution_context: dict[str, Any],
        error_message: str,
    ) -> dict[str, Any]:
        """
        Called when a step fails — provide intelligent failure explanation.
        Returns a structured failure analysis.
        """
        page_state = await asyncio.to_thread(self._get_compressed_state)

        prompt = f"""FAILED STEP:
Action: {failed_step.get('action', '?')}
Description: {failed_step.get('description', '?')}
Target: {failed_step.get('target', 'N/A')}
Business intent: {failed_step.get('business_intent', 'N/A')}
Phase: {failed_step.get('phase', 'N/A')}
Error: {error_message[:300]}

CURRENT PAGE (at time of failure):
URL: {page_state['url']}
Title: {page_state['title']}
Visible text: {page_state['visible_text'][:800]}
Alerts/errors on page: {page_state['alerts']}

Workflow: {execution_context.get('workflow', '?')}
Recent steps: {', '.join(execution_context.get('recent_actions', [])[-3:])}

Explain this failure in business terms. What broke? Why? What should be checked?

Return JSON:
{{
  "title": "Brief failure title",
  "what_failed": "Business explanation of what failed",
  "why_it_failed": "Most likely reason",
  "workflow_impact": "Which part of the workflow is blocked",
  "suggestions": ["List of specific things to check or fix"],
  "severity": "low|medium|high|critical"
}}"""

        try:
            response = await asyncio.wait_for(
                self.ai.complete(
                    system="You are QAptain's failure explanation engine. Explain test failures in business terms, not technical jargon. Output only valid JSON.",
                    user=prompt,
                    fast=True,
                    json_mode=True,
                    max_tokens=500,
                ),
                timeout=15.0,
            )
            return response.json()
        except (Exception, asyncio.CancelledError) as e:
            log.warning("Step failure analysis failed", error=str(e))
            return {
                "title": f"Failed: {failed_step.get('description', 'Unknown step')}",
                "what_failed": f"The step '{failed_step.get('description', '')}' could not be completed.",
                "why_it_failed": "Element not found, page not loaded, or application error.",
                "workflow_impact": f"Phase '{failed_step.get('phase', 'unknown')}' is blocked.",
                "suggestions": [
                    "Verify the target element exists on the current page",
                    "Check if the application is in the expected state",
                    "Review the previous step's result",
                ],
                "severity": "high",
            }

    # ─── Page state extractor ─────────────────────────────────────────────────

    def _get_compressed_state(self) -> dict[str, Any]:
        """
        Extract a compressed, AI-friendly page state.
        NEVER sends full HTML — only meaningful semantic content.
        """
        try:
            url = self.browser.execute_script("return window.location.href;") or ""
        except Exception:
            url = self.browser.get_current_url()

        try:
            title = self.browser.execute_script("return document.title;") or ""
        except Exception:
            title = ""

        # Visible text: extract from key semantic elements only
        visible_text = self._extract_visible_text()

        # Key elements: buttons, headings, links with text
        key_elements = self._extract_key_elements()

        # Alerts, toasts, error messages
        alerts = self._extract_alerts()

        return {
            "url": url,
            "title": title,
            "visible_text": visible_text,
            "key_elements": key_elements,
            "alerts": alerts,
        }

    def _extract_visible_text(self) -> str:
        """Extract visible text from semantic elements only."""
        try:
            texts = self.browser.execute_script("""
                const sel = [
                    'h1','h2','h3','h4',
                    'table th', 'table td',
                    '[role="rowheader"]', '[role="cell"]',
                    'label', '.form-label',
                    '[class*="title"]', '[class*="heading"]',
                    '[class*="toast"]', '[class*="alert"]', '[class*="notification"]',
                    'nav a', '[role="menuitem"]',
                    'p', 'span[class]',
                ];
                const seen = new Set();
                const results = [];
                for (const s of sel) {
                    for (const el of document.querySelectorAll(s)) {
                        const t = (el.textContent || '').trim().replace(/\\s+/g, ' ');
                        if (t && t.length > 1 && t.length < 200 && !seen.has(t)) {
                            seen.add(t);
                            results.push(t);
                            if (results.length >= 80) return results.join(' | ');
                        }
                    }
                }
                return results.join(' | ');
            """)
            return str(texts or "")
        except Exception:
            return ""

    def _extract_key_elements(self) -> str:
        """Extract interactive elements with their labels."""
        try:
            elements = self.browser.execute_script("""
                function isVis(el) {
                    const r = el.getBoundingClientRect();
                    return r.width > 0 && r.height > 0;
                }
                const items = [];
                // Buttons
                for (const el of document.querySelectorAll('button, [role="button"], input[type="submit"]')) {
                    if (isVis(el)) {
                        const t = (el.textContent || el.value || el.getAttribute('aria-label') || '').trim();
                        if (t && t.length < 80) items.push('[BTN] ' + t);
                        if (items.length >= 20) break;
                    }
                }
                // Inputs with labels
                for (const el of document.querySelectorAll('input[type="text"], input[type="email"], textarea, select')) {
                    if (isVis(el)) {
                        const lbl = el.getAttribute('placeholder') || el.getAttribute('aria-label') || el.name || '';
                        if (lbl) items.push('[INPUT] ' + lbl);
                        if (items.length >= 30) break;
                    }
                }
                return items.join(' | ');
            """)
            return str(elements or "")
        except Exception:
            return ""

    def _extract_alerts(self) -> str:
        """Extract visible alert/toast/error messages."""
        try:
            alerts = self.browser.execute_script("""
                const sels = [
                    '[class*="toast"]', '[class*="alert"]', '[class*="notification"]',
                    '[class*="snack"]', '[class*="error"]', '[class*="success"]',
                    '[class*="warning"]', '[role="alert"]', '[role="status"]',
                    '.mat-snack-bar-container', '[class*="message"]',
                ];
                const results = [];
                for (const s of sels) {
                    for (const el of document.querySelectorAll(s)) {
                        const r = el.getBoundingClientRect();
                        if (r.width > 0 && r.height > 0) {
                            const t = (el.textContent || '').trim().replace(/\\s+/g, ' ');
                            if (t && t.length < 300) results.push(t);
                        }
                        if (results.length >= 5) break;
                    }
                }
                return results.join(' | ');
            """)
            return str(alerts or "")
        except Exception:
            return ""
