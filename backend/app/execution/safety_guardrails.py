"""
Safety guardrails — prevents dangerous actions and enforces environment awareness.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger()

MAX_RETRIES_PER_STEP = 3
MAX_TOTAL_RETRIES = 15

DANGEROUS_PATTERNS: list[str] = [
    "delete all",
    "bulk delete",
    "drop table",
    "truncate",
    "reset all",
    "wipe",
    "purge all",
    "destroy",
    "delete.*all",
    "remove all",
]

PRODUCTION_URL_INDICATORS = ["prod", "production", "live", "app.", "www.", "enterprise"]
STAGING_URL_INDICATORS = ["staging", "stage", "stg", "uat", "preprod"]
DEV_URL_INDICATORS = ["dev", "local", "localhost", "test", "qa", "demo", "127.0.0.1"]


@dataclass
class SafetyCheckResult:
    allowed: bool
    reason: str
    risk_level: str
    safe_alternative: dict[str, Any] | None = None


def _matches_dangerous(text: str) -> bool:
    lower = text.lower()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, lower):
            return True
    return False


class SafetyGuardrails:
    """Enforces safety constraints on step execution."""

    def __init__(self, base_url: str, is_production: bool = False) -> None:
        self.base_url = base_url
        self._is_production = is_production or self.is_production(base_url)
        self._total_retries: int = 0
        self._step_retry_counts: dict[str, int] = {}

    def check_step(
        self,
        step: dict[str, Any],
        retry_count: int = 0,
    ) -> SafetyCheckResult:
        step_limit = self.get_retry_limit(step)

        if retry_count >= step_limit:
            return SafetyCheckResult(
                allowed=False,
                reason=f"Max retries reached ({retry_count}/{step_limit})",
                risk_level="HIGH",
            )

        description = step.get("description", "") or step.get("action", "")
        target = step.get("target", "") or ""
        combined = f"{description} {target}"

        if _matches_dangerous(combined):
            if self._is_production:
                return SafetyCheckResult(
                    allowed=False,
                    reason=f"Dangerous pattern detected in production: '{combined[:80]}'",
                    risk_level="CRITICAL",
                    safe_alternative={"suggestion": "Run this operation in staging first"},
                )
            log.warning("Dangerous pattern detected in non-production", combined=combined[:80])
            return SafetyCheckResult(
                allowed=True,
                reason=f"Dangerous pattern detected — proceeding with caution in non-prod: '{combined[:80]}'",
                risk_level="HIGH",
            )

        action = step.get("action", "")
        if (
            action == "click"
            and "delete" in target.lower()
            and not any(
                prev.get("action", "").startswith("assert")
                for prev in []  # caller may pass prior steps in metadata; default safe
            )
        ):
            return SafetyCheckResult(
                allowed=True,
                reason="Blind delete detected — no prior assert_visible for this record",
                risk_level="MEDIUM",
            )

        return SafetyCheckResult(allowed=True, reason="Step cleared", risk_level="LOW")

    def check_environment(self, url: str) -> str:
        lower = url.lower()
        if any(ind in lower for ind in PRODUCTION_URL_INDICATORS):
            return "production"
        if any(ind in lower for ind in STAGING_URL_INDICATORS):
            return "staging"
        if any(ind in lower for ind in DEV_URL_INDICATORS):
            return "development"
        return "unknown"

    def is_destructive(self, step: dict[str, Any]) -> bool:
        action = step.get("action", "")
        target = (step.get("target", "") or "").lower()
        description = (step.get("description", "") or "").lower()
        if action == "click":
            return _matches_dangerous(f"{target} {description}")
        return False

    def is_production(self, url: str) -> bool:
        lower = url.lower()
        if any(ind in lower for ind in DEV_URL_INDICATORS):
            return False
        if any(ind in lower for ind in STAGING_URL_INDICATORS):
            return False
        return any(ind in lower for ind in PRODUCTION_URL_INDICATORS)

    def get_retry_limit(self, step: dict[str, Any]) -> int:
        action = step.get("action", "")
        if action == "screenshot":
            return 1
        on_fail = step.get("on_fail", "continue")
        if on_fail == "fail":
            return MAX_RETRIES_PER_STEP
        return MAX_RETRIES_PER_STEP + 1

    @property
    def total_retries_counter(self) -> int:
        return self._total_retries

    def increment_retry(self, step_desc: str) -> bool:
        if self._total_retries >= MAX_TOTAL_RETRIES:
            log.warning("Total retry limit exceeded", total=self._total_retries)
            return False
        self._total_retries += 1
        self._step_retry_counts[step_desc] = self._step_retry_counts.get(step_desc, 0) + 1
        return True
