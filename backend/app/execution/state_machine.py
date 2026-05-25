"""
Workflow execution state machine — tracks states, phases, and transitions.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

log = structlog.get_logger()


class WState(str, Enum):
    INITIAL = "INITIAL"
    NAVIGATING = "NAVIGATING"
    LOGIN = "LOGIN"
    FORM_OPEN = "FORM_OPEN"
    DATA_ENTRY = "DATA_ENTRY"
    SUBMITTED = "SUBMITTED"
    VERIFYING = "VERIFYING"
    RECORD_CREATED = "RECORD_CREATED"
    RECORD_EDITING = "RECORD_EDITING"
    RECORD_UPDATED = "RECORD_UPDATED"
    RECORD_DELETED = "RECORD_DELETED"
    SEARCH_ACTIVE = "SEARCH_ACTIVE"
    RESULTS_VISIBLE = "RESULTS_VISIBLE"
    MODAL_OPEN = "MODAL_OPEN"
    WAITING_ASYNC = "WAITING_ASYNC"
    COMPLETED = "COMPLETED"
    PAUSED_HUMAN = "PAUSED_HUMAN"
    FAILED = "FAILED"


PHASE_STATE_MAP: dict[str, WState] = {
    "SETUP": WState.INITIAL,
    "LOGIN": WState.LOGIN,
    "NAVIGATE": WState.NAVIGATING,
    "FORM_OPEN": WState.FORM_OPEN,
    "DATA_ENTRY": WState.DATA_ENTRY,
    "CREATE": WState.DATA_ENTRY,
    "SUBMIT": WState.SUBMITTED,
    "VERIFY_CREATED": WState.VERIFYING,
    "UPDATE": WState.RECORD_EDITING,
    "VERIFY_UPDATED": WState.VERIFYING,
    "DELETE": WState.RECORD_DELETED,
    "VERIFY_DELETED": WState.VERIFYING,
    "SEARCH": WState.SEARCH_ACTIVE,
    "TEARDOWN": WState.COMPLETED,
}

ACTION_STATE_MAP: dict[str, WState] = {
    "navigate": WState.NAVIGATING,
    "fill": WState.DATA_ENTRY,
    "wait_network": WState.WAITING_ASYNC,
}

_TERMINAL_STATES = {WState.COMPLETED, WState.FAILED}


@dataclass
class StateTransition:
    from_state: WState
    to_state: WState
    trigger: str
    phase: str
    timestamp: float = field(default_factory=time.monotonic)
    metadata: dict[str, Any] | None = None


class WorkflowStateMachine:
    """Tracks execution state for a single workflow run."""

    def __init__(self, workflow_type: str = "") -> None:
        self.workflow_type = workflow_type
        self.current_state: WState = WState.INITIAL
        self.current_phase: str = ""
        self.history: list[StateTransition] = []
        self._completed_phases: list[str] = []
        self._start_time: float = time.monotonic()
        self._pre_pause_state: WState | None = None

    def transition(
        self,
        new_state: WState,
        trigger: str,
        phase: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        if self.current_state in _TERMINAL_STATES and new_state != WState.FAILED:
            log.warning(
                "Transition blocked — already terminal",
                current=self.current_state,
                requested=new_state,
            )
            return False

        transition = StateTransition(
            from_state=self.current_state,
            to_state=new_state,
            trigger=trigger,
            phase=phase or self.current_phase,
            metadata=metadata,
        )
        self.history.append(transition)
        self.current_state = new_state
        if phase:
            self.current_phase = phase

        log.debug(
            "State transition",
            from_state=transition.from_state,
            to_state=new_state,
            trigger=trigger,
            phase=phase,
        )
        return True

    def transition_from_step(
        self,
        step: dict[str, Any],
        success: bool,
        phase: str,
        ui_transitions: list[str] | None = None,
    ) -> None:
        if not success:
            self.transition(WState.FAILED, trigger=step.get("action", "unknown"), phase=phase)
            return

        # Phase takes priority over action for state inference
        phase_upper = phase.upper() if phase else ""
        new_state = PHASE_STATE_MAP.get(phase_upper)

        if new_state is None:
            action = step.get("action", "")
            for keyword, state in ACTION_STATE_MAP.items():
                if action.startswith(keyword):
                    new_state = state
                    break

            # assert_* actions → VERIFYING
            if new_state is None and action.startswith("assert"):
                new_state = WState.VERIFYING

        if new_state is not None:
            self.transition(new_state, trigger=step.get("action", "step"), phase=phase)

        if phase and phase not in self._completed_phases:
            self._completed_phases.append(phase)

    def mark_paused(self, reason: str) -> None:
        self._pre_pause_state = self.current_state
        self.transition(WState.PAUSED_HUMAN, trigger=f"pause:{reason}")

    def mark_resumed(self) -> None:
        target = self._pre_pause_state or WState.INITIAL
        self._pre_pause_state = None
        self.transition(target, trigger="resume")

    def get_recovery_state(self) -> WState | None:
        for t in reversed(self.history):
            if t.to_state not in {WState.FAILED, WState.PAUSED_HUMAN}:
                return t.to_state
        return None

    def is_terminal(self) -> bool:
        return self.current_state in _TERMINAL_STATES

    def summary(self) -> dict[str, Any]:
        return {
            "current_state": self.current_state,
            "current_phase": self.current_phase,
            "completed_phases": list(self._completed_phases),
            "transitions_count": len(self.history),
            "elapsed_seconds": round(time.monotonic() - self._start_time, 2),
        }
