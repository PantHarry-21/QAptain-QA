"""
Entity Lifecycle Tracker — Cross-Step Entity Awareness.

Observes every step execution to track which test entities were created,
updated, and deleted. This gives later steps in the same run a live
reference to the entity name the AI generated — without hardcoding it.

Why this matters for CRUD:
  CREATE fills "TestProducts001" into the Name field.
  UPDATE must click the row for "TestProducts001" (or whatever was actually filled).
  DELETE must click the same row.
  VERIFY_DELETED must assert_not_text "UpdatedProducts001".

Without this, the plan runner searches for a hardcoded string that may not
match what was actually typed — causing UPDATE/DELETE steps to fail silently.

Integration:
  PlanRunner.entity_tracker = EntityTracker(entity_type)
  # Before each step:
      step = runner.entity_tracker.inject_into_step(step)
  # After each step:
      runner.entity_tracker.observe_step(step, result, step_num)
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any

import structlog

log = structlog.get_logger()

# Regex: fields that hold the entity's primary identifier
_NAME_FIELD_RE = re.compile(
    r"\b(name|title|code|label|key|identifier|subject|heading|ref|reference)\b",
    re.IGNORECASE,
)

# Phases in which we expect entity creation fills
_CREATE_PHASES = frozenset({
    "CREATE", "DATA_ENTRY", "FORM_OPEN", "SUBMIT", "VERIFY_CREATED",
})
# Phases in which we expect entity update fills
_UPDATE_PHASES = frozenset({"UPDATE", "VERIFY_UPDATED"})
# Phases in which we expect entity deletion
_DELETE_PHASES = frozenset({"DELETE", "VERIFY_DELETED"})


@dataclass
class LifecycleEvent:
    event: str          # "created" | "updated" | "deleted" | "confirmed"
    phase: str
    name: str           # entity name/value at time of event
    step_num: int


@dataclass
class LiveEntity:
    """Tracks a single test entity through its full CRUD lifecycle."""
    entity_type: str
    created_name: str        # value filled during CREATE
    updated_name: str = ""   # value filled during UPDATE
    is_confirmed: bool = False   # assert_visible passed after create
    is_deleted: bool = False
    events: list[LifecycleEvent] = field(default_factory=list)

    def get_current_name(self) -> str:
        """Name as it should appear in the UI right now."""
        return self.updated_name if self.updated_name else self.created_name


class EntityTracker:
    """
    Observes step execution in real-time and tracks the lifecycle of test entities.

    Thread-safety: not needed — single-threaded async execution.
    """

    def __init__(self, entity_type: str = "Record") -> None:
        self.entity_type = entity_type
        self._entities: list[LiveEntity] = []
        # Ring buffer of (phase, target, value) for all fill steps seen so far
        self._fill_history: list[tuple[str, str, str]] = []
        self._current_phase: str = ""

    def set_entity_type(self, entity_type: str) -> None:
        self.entity_type = entity_type

    # ─── Main hook ────────────────────────────────────────────────────────────

    def observe_step(
        self,
        step: dict[str, Any],
        result: Any,    # StepExecutionResult from plan_runner
        step_num: int,
    ) -> None:
        """Called by PlanRunner after every step. Records lifecycle events."""
        action   = step.get("action", "")
        phase    = step.get("phase", "") or self._current_phase
        target   = str(step.get("target", ""))
        value    = str(step.get("value", ""))
        success  = getattr(result, "success", False)

        if phase:
            self._current_phase = phase

        # ── Record fill on identifier fields ──────────────────────────────────
        if action == "fill" and value and _NAME_FIELD_RE.search(target):
            self._fill_history.append((phase, target, value))

        # ── Confirm entity created ─────────────────────────────────────────────
        # When the plan runner successfully asserts visibility in a CREATE phase,
        # the most recent name-fill is the entity that was just created.
        if phase in _CREATE_PHASES and action in ("assert_visible", "assert_text") and success:
            candidate = self._latest_name_fill(_CREATE_PHASES)
            if candidate and not self._known(candidate):
                entity = LiveEntity(
                    entity_type=self.entity_type,
                    created_name=candidate,
                    is_confirmed=True,
                )
                entity.events.append(LifecycleEvent("created", phase, candidate, step_num))
                self._entities.append(entity)
                log.info("EntityTracker: CREATED", type=self.entity_type, name=candidate)

        # ── Track entity update ───────────────────────────────────────────────
        if (phase in _UPDATE_PHASES and action == "fill"
                and value and _NAME_FIELD_RE.search(target) and success):
            live = self._primary()
            if live and live.created_name != value and live.updated_name != value:
                live.updated_name = value
                live.events.append(LifecycleEvent("updated", phase, value, step_num))
                log.info("EntityTracker: UPDATED",
                    type=self.entity_type, old=live.created_name, new=value)

        # ── Confirm entity deleted ────────────────────────────────────────────
        if phase in _DELETE_PHASES and action == "assert_not_text" and success:
            live = self._primary()
            if live:
                live.is_deleted = True
                live.events.append(
                    LifecycleEvent("deleted", phase, live.get_current_name(), step_num)
                )
                log.info("EntityTracker: DELETED",
                    type=self.entity_type, name=live.get_current_name())

    # ─── Template injection ────────────────────────────────────────────────────

    def inject_into_step(self, step: dict[str, Any]) -> dict[str, Any]:
        """
        Replace {{live_entity}} / {{created_entity}} / {{current_entity}} placeholders
        in step fields before the step is executed.

        This enables plan steps like:
          "target": "Edit|{{live_entity}}|pencil icon"
        to dynamically resolve to the actual entity name at runtime.
        """
        created = self.get_created_name()
        current = self.get_current_name()
        if not created and not current:
            return step

        step = dict(step)
        for key in ("target", "value", "text", "description"):
            v = step.get(key, "")
            if isinstance(v, str) and "{{" in v:
                v = v.replace("{{live_entity}}", current or created)
                v = v.replace("{{created_entity}}", created)
                v = v.replace("{{current_entity}}", current or created)
                step[key] = v
        return step

    # ─── Query API ────────────────────────────────────────────────────────────

    def get_created_name(self) -> str:
        """The name value filled during CREATE. May be empty if not yet created."""
        live = self._primary()
        if live:
            return live.created_name
        # Fall back: look in fill history even before confirmation
        return self._latest_name_fill(_CREATE_PHASES)

    def get_current_name(self) -> str:
        """Current UI name — updated_name if entity was updated, else created_name."""
        live = self._primary()
        if live:
            return live.get_current_name()
        return self.get_created_name()

    def is_created(self) -> bool:
        return any(not e.is_deleted for e in self._entities)

    def is_deleted(self) -> bool:
        return bool(self._entities) and all(e.is_deleted for e in self._entities)

    def get_lifecycle_summary(self) -> dict[str, Any]:
        """Used by IntentOrchestrator.post_execute() and execution reports."""
        return {
            "entity_type": self.entity_type,
            "created_name": self.get_created_name(),
            "current_name": self.get_current_name(),
            "is_created": self.is_created(),
            "is_deleted": self.is_deleted(),
            "entity_count": len(self._entities),
            "events": [
                {"event": ev.event, "phase": ev.phase, "name": ev.name, "step": ev.step_num}
                for e in self._entities
                for ev in e.events
            ],
        }

    # ─── Private helpers ──────────────────────────────────────────────────────

    def _latest_name_fill(self, phases: frozenset[str]) -> str:
        """Most recent fill on a name-like target within the given phases."""
        for phase, target, value in reversed(self._fill_history):
            if phase in phases and _NAME_FIELD_RE.search(target) and value:
                return value
        return ""

    def _known(self, name: str) -> bool:
        return any(e.created_name == name for e in self._entities)

    def _primary(self) -> LiveEntity | None:
        """The active (non-deleted) primary entity, or the last one."""
        for e in self._entities:
            if not e.is_deleted:
                return e
        return self._entities[-1] if self._entities else None
