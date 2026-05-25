"""
Observability layer — accumulates execution metrics in memory, produces summary for reports.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger()


@dataclass
class AICallRecord:
    purpose: str
    duration_ms: int
    tokens: int = 0
    timestamp: float = field(default_factory=time.monotonic)


@dataclass
class PhaseRecord:
    name: str
    started_at: float
    ended_at: float | None = None
    success: bool | None = None

    @property
    def duration_ms(self) -> int:
        end = self.ended_at if self.ended_at is not None else time.monotonic()
        return int((end - self.started_at) * 1000)


@dataclass
class ExecutionMetrics:
    run_id: str
    ai_calls: int
    ai_total_ms: int
    ai_avg_ms: float
    token_usage: int
    retry_counts: dict[str, int]
    total_retries: int
    confidence_trend: list[float]
    avg_confidence: float
    failure_categories: dict[str, int]
    workflow_stability: float
    phase_durations: dict[str, int]
    recovery_attempts: int
    total_steps: int
    passed_steps: int
    failed_steps: int
    duration_seconds: float


class ObservabilityLayer:
    """Collects execution telemetry for a single run."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._start_time: float = time.monotonic()
        self._ai_calls: list[AICallRecord] = []
        self._retry_counts: dict[str, int] = {}
        self._confidence_scores: list[float] = []
        self._phases: dict[str, PhaseRecord] = {}
        self._failure_categories: dict[str, int] = {}
        self._recovery_log: list[dict[str, Any]] = []
        self._total_steps: int = 0
        self._passed_steps: int = 0
        self._failed_steps: int = 0
        self._healed_steps: int = 0

    def record_ai_call(self, purpose: str, duration_ms: int, tokens: int = 0) -> None:
        self._ai_calls.append(AICallRecord(purpose=purpose, duration_ms=duration_ms, tokens=tokens))

    def record_retry(self, step_desc: str, reason: str) -> None:
        self._retry_counts[step_desc] = self._retry_counts.get(step_desc, 0) + 1
        log.debug("Retry recorded", step=step_desc, reason=reason)

    def record_confidence(self, score: float) -> None:
        self._confidence_scores.append(score)

    def record_phase_start(self, phase: str) -> None:
        self._phases[phase] = PhaseRecord(name=phase, started_at=time.monotonic())

    def record_phase_end(self, phase: str, success: bool) -> None:
        if phase in self._phases:
            self._phases[phase].ended_at = time.monotonic()
            self._phases[phase].success = success
        else:
            # Phase started before observability was attached
            self._phases[phase] = PhaseRecord(
                name=phase,
                started_at=time.monotonic(),
                ended_at=time.monotonic(),
                success=success,
            )

    def record_recovery(self, from_state: str, to_state: str, method: str) -> None:
        self._recovery_log.append({
            "from_state": from_state,
            "to_state": to_state,
            "method": method,
            "timestamp": time.monotonic(),
        })

    def record_failure(self, category: str, description: str) -> None:
        self._failure_categories[category] = self._failure_categories.get(category, 0) + 1
        log.debug("Failure recorded", category=category, description=description)

    def record_step(self, success: bool, healing_used: bool) -> None:
        self._total_steps += 1
        if success:
            self._passed_steps += 1
            if healing_used:
                self._healed_steps += 1
        else:
            self._failed_steps += 1

    def get_metrics(self) -> ExecutionMetrics:
        ai_total_ms = sum(c.duration_ms for c in self._ai_calls)
        ai_avg_ms = round(ai_total_ms / len(self._ai_calls), 1) if self._ai_calls else 0.0
        token_usage = sum(c.tokens for c in self._ai_calls)

        avg_confidence = (
            round(sum(self._confidence_scores) / len(self._confidence_scores), 3)
            if self._confidence_scores else 0.0
        )

        # Steps that passed without healing or retry are considered "stable"
        retried_steps = len(self._retry_counts)
        unstable_count = self._healed_steps + retried_steps
        stable_count = max(0, self._passed_steps - unstable_count)
        workflow_stability = (stable_count / self._total_steps) if self._total_steps > 0 else 1.0

        phase_durations = {name: rec.duration_ms for name, rec in self._phases.items()}

        return ExecutionMetrics(
            run_id=self.run_id,
            ai_calls=len(self._ai_calls),
            ai_total_ms=ai_total_ms,
            ai_avg_ms=ai_avg_ms,
            token_usage=token_usage,
            retry_counts=dict(self._retry_counts),
            total_retries=sum(self._retry_counts.values()),
            confidence_trend=list(self._confidence_scores),
            avg_confidence=avg_confidence,
            failure_categories=dict(self._failure_categories),
            workflow_stability=round(workflow_stability, 3),
            phase_durations=phase_durations,
            recovery_attempts=len(self._recovery_log),
            total_steps=self._total_steps,
            passed_steps=self._passed_steps,
            failed_steps=self._failed_steps,
            duration_seconds=round(time.monotonic() - self._start_time, 2),
        )

    def get_summary(self) -> dict[str, Any]:
        m = self.get_metrics()
        return {
            "ai_calls": m.ai_calls,
            "ai_avg_ms_per_call": m.ai_avg_ms,
            "total_retries": m.total_retries,
            "avg_confidence": m.avg_confidence,
            "workflow_stability": m.workflow_stability,
            "recovery_attempts": m.recovery_attempts,
            "phase_durations": m.phase_durations,
            "failure_categories": m.failure_categories,
            "token_usage": m.token_usage,
        }
