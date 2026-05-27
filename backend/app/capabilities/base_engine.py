"""Abstract base for all QA Capability Engines."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any
from app.capabilities.contracts import CapabilityContext, RecoveryStep


class BaseCapabilityEngine(ABC):
    """
    All QA Capability Engines inherit from this.

    Engines are stateless pure-Python generators — no Selenium, no async.
    They produce deterministic step sequences and assertion specs that
    feed into the QA Reasoning Engine's prompt and the PlanRunner's
    recovery system.
    """

    engine_id: str = "base"
    workflow_types: list[str] = []

    @abstractmethod
    def generate_positive_steps(self, ctx: CapabilityContext) -> list[dict]:
        """Generate positive (happy path) test steps."""
        ...

    @abstractmethod
    def generate_negative_steps(self, ctx: CapabilityContext) -> list[dict]:
        """Generate negative/validation test steps."""
        ...

    def generate_edge_case_steps(self, ctx: CapabilityContext) -> list[dict]:
        """Generate edge case test steps. Default: empty."""
        return []

    def generate_security_steps(self, ctx: CapabilityContext) -> list[dict]:
        """Generate security validation steps. Default: empty."""
        return []

    def get_recovery_steps(self, failed_action: str, error_context: dict) -> list[RecoveryStep]:
        """Return ordered recovery strategies for a failed action."""
        return []

    def get_assertions(self, ctx: CapabilityContext) -> list[dict]:
        """Return assertion templates for this workflow type."""
        return []

    def get_capability_summary(self) -> dict:
        """Return human-readable summary of what this engine tests."""
        return {
            "engine_id": self.engine_id,
            "workflow_types": self.workflow_types,
            "capabilities": [],
        }

    # ── Shared helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _step(action: str, description: str, phase: str, business_intent: str,
              target: str = "", value: str = "", url: str = "",
              timeout_ms: int = 10000, on_fail: str = "fail",
              checkpoint: bool = False, engine_id: str = "",
              test_category: str = "positive") -> dict:
        return {
            "action": action,
            "description": description,
            "phase": phase,
            "business_intent": business_intent,
            "target": target,
            "value": value,
            "url": url,
            "timeout_ms": timeout_ms,
            "on_fail": on_fail,
            "checkpoint": checkpoint,
            "engine_id": engine_id,
            "test_category": test_category,
        }

    @staticmethod
    def _screenshot(phase: str, desc: str = "", engine_id: str = "") -> dict:
        return {
            "action": "screenshot",
            "description": desc or f"Capture state after {phase}",
            "phase": phase,
            "business_intent": "Visual evidence",
            "target": "", "value": "", "url": "",
            "timeout_ms": 5000, "on_fail": "skip",
            "checkpoint": False,
            "engine_id": engine_id,
            "test_category": "positive",
        }

    @staticmethod
    def _wait_network(desc: str = "Wait for operation to complete", phase: str = "") -> dict:
        return {
            "action": "wait_network",
            "description": desc,
            "phase": phase,
            "business_intent": "Ensure async operation completes",
            "target": "", "value": "", "url": "",
            "timeout_ms": 15000, "on_fail": "skip",
            "checkpoint": False,
            "engine_id": "base",
            "test_category": "positive",
        }
