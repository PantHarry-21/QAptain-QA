"""
Confidence engine — tracks AI confidence scores and trends across an execution run.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger()

HIGH_THRESHOLD = 0.75
LOW_THRESHOLD = 0.40
CRITICAL_THRESHOLD = 0.25


@dataclass
class ConfidenceRecord:
    score: float
    reason: str
    context: str
    action: str
    timestamp: float = field(default_factory=time.monotonic)


class ConfidenceEngine:
    """Tracks and interprets AI confidence scores for an execution run."""

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._history: list[ConfidenceRecord] = []
        self._phase_scores: dict[str, list[float]] = {}

    def record(
        self,
        score: float,
        reason: str,
        context: str = "",
        phase: str = "",
    ) -> None:
        record = ConfidenceRecord(
            score=score,
            reason=reason,
            context=context,
            action=phase,
        )
        self._history.append(record)
        if phase:
            self._phase_scores.setdefault(phase, []).append(score)

    def assess_checkpoint(self, checkpoint_result: dict[str, Any]) -> tuple[str, str]:
        passed = checkpoint_result.get("passed", False)
        confidence = float(checkpoint_result.get("confidence", 0.0))

        if confidence < CRITICAL_THRESHOLD:
            return "abort", "Critical low confidence"

        if confidence >= HIGH_THRESHOLD:
            return "proceed", "High confidence — continue"

        if confidence >= LOW_THRESHOLD:
            return "warn", "Medium confidence — monitoring"

        # confidence < LOW_THRESHOLD
        if not passed:
            return "pause", "Low confidence on failure"

        return "warn", "Low confidence but passed — monitoring"

    def should_pause(self, score: float) -> bool:
        return score < LOW_THRESHOLD

    def should_abort(self, score: float) -> bool:
        return score < CRITICAL_THRESHOLD

    def get_trend(self) -> str:
        if len(self._history) < 3:
            return "insufficient_data"

        scores = [r.score for r in self._history]
        recent = scores[-3:]
        prior = scores[-6:-3] if len(scores) >= 6 else scores[:-3]

        if not prior:
            return "insufficient_data"

        recent_avg = sum(recent) / len(recent)
        prior_avg = sum(prior) / len(prior)
        delta = recent_avg - prior_avg

        if delta > 0.1:
            return "recovering"
        if delta < -0.1:
            return "declining"
        return "stable"

    def get_average(self) -> float:
        if not self._history:
            return 0.0
        return round(sum(r.score for r in self._history) / len(self._history), 3)

    def get_phase_summary(self) -> dict[str, float]:
        return {
            phase: round(sum(scores) / len(scores), 3)
            for phase, scores in self._phase_scores.items()
            if scores
        }

    def summary(self) -> dict[str, Any]:
        scores = [r.score for r in self._history]
        return {
            "overall_avg": self.get_average(),
            "trend": self.get_trend(),
            "low_confidence_count": sum(1 for s in scores if s < LOW_THRESHOLD),
            "high_confidence_count": sum(1 for s in scores if s >= HIGH_THRESHOLD),
            "total_recorded": len(self._history),
        }
