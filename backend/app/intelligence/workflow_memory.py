"""
Workflow memory engine — persists and recalls execution intelligence via AIMemoryChunk.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import AIMemoryChunk, MemoryKind

log = structlog.get_logger()


class WorkflowMemoryEngine:
    """Reads and writes execution learnings to the ai_memory_chunks table."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def store_successful_run(
        self,
        app_id: str,
        workflow_name: str,
        workflow_type: str,
        phases: list[str],
        step_count: int,
        duration_seconds: float,
        checkpoint_pass_rate: float,
    ) -> None:
        key = f"run_success:{workflow_name}"
        chunk = await self._find_chunk(app_id, MemoryKind.EXECUTION_LEARNING, key)
        now_iso = datetime.utcnow().isoformat()

        if chunk:
            run_count = chunk.extra.get("run_count", 1) + 1
            chunk.extra = {
                **chunk.extra,
                "key": key,
                "run_count": run_count,
                "last_success": now_iso,
                "phases": phases,
                "avg_duration_seconds": round(
                    (chunk.extra.get("avg_duration_seconds", duration_seconds) + duration_seconds) / 2, 2
                ),
                "checkpoint_pass_rate": checkpoint_pass_rate,
            }
            chunk.content = (
                f"Workflow '{workflow_name}' ({workflow_type}) completed successfully "
                f"{run_count} times. Phases: {', '.join(phases)}. "
                f"Steps: {step_count}. Checkpoint pass rate: {checkpoint_pass_rate:.0%}."
            )
        else:
            chunk = AIMemoryChunk(
                application_id=app_id,
                kind=MemoryKind.EXECUTION_LEARNING,
                content=(
                    f"Workflow '{workflow_name}' ({workflow_type}) completed successfully. "
                    f"Phases: {', '.join(phases)}. Steps: {step_count}. "
                    f"Checkpoint pass rate: {checkpoint_pass_rate:.0%}."
                ),
                extra={
                    "key": key,
                    "workflow_name": workflow_name,
                    "workflow_type": workflow_type,
                    "phases": phases,
                    "step_count": step_count,
                    "avg_duration_seconds": duration_seconds,
                    "checkpoint_pass_rate": checkpoint_pass_rate,
                    "run_count": 1,
                    "last_success": now_iso,
                },
            )
            self.db.add(chunk)

        await self.db.commit()
        log.debug("Stored successful run memory", workflow=workflow_name)

    async def store_navigation_path(
        self,
        app_id: str,
        module_name: str,
        url_path: str,
        nav_steps: list[str],
    ) -> None:
        key = f"nav:{module_name}"
        chunk = await self._find_chunk(app_id, MemoryKind.EXECUTION_LEARNING, key)

        if chunk:
            chunk.extra = {**chunk.extra, "key": key, "url_path": url_path, "nav_steps": nav_steps}
            chunk.content = f"Navigation to '{module_name}': {url_path}. Steps: {', '.join(nav_steps)}."
        else:
            chunk = AIMemoryChunk(
                application_id=app_id,
                kind=MemoryKind.EXECUTION_LEARNING,
                content=f"Navigation to '{module_name}': {url_path}. Steps: {', '.join(nav_steps)}.",
                extra={"key": key, "module_name": module_name, "url_path": url_path, "nav_steps": nav_steps},
            )
            self.db.add(chunk)

        await self.db.commit()

    async def store_dynamic_behavior(
        self,
        app_id: str,
        trigger: str,
        observed_transitions: list[str],
        wait_needed_ms: int,
    ) -> None:
        key = f"behavior:{trigger}"
        chunk = await self._find_chunk(app_id, MemoryKind.DYNAMIC_BEHAVIOR, key)

        if chunk:
            chunk.extra = {
                **chunk.extra,
                "key": key,
                "transitions": observed_transitions,
                "wait_needed_ms": wait_needed_ms,
            }
            chunk.content = (
                f"After '{trigger}': transitions={', '.join(observed_transitions)}, "
                f"wait_needed={wait_needed_ms}ms."
            )
        else:
            chunk = AIMemoryChunk(
                application_id=app_id,
                kind=MemoryKind.DYNAMIC_BEHAVIOR,
                content=(
                    f"After '{trigger}': transitions={', '.join(observed_transitions)}, "
                    f"wait_needed={wait_needed_ms}ms."
                ),
                extra={
                    "key": key,
                    "trigger": trigger,
                    "transitions": observed_transitions,
                    "wait_needed_ms": wait_needed_ms,
                },
            )
            self.db.add(chunk)

        await self.db.commit()

    async def recall_navigation_path(
        self, app_id: str, module_name: str
    ) -> dict[str, Any] | None:
        chunk = await self._find_chunk(app_id, MemoryKind.EXECUTION_LEARNING, f"nav:{module_name}")
        if chunk is None:
            return None
        await self._increment_access(chunk)
        return chunk.extra

    async def recall_dynamic_behavior(
        self, app_id: str, trigger: str
    ) -> dict[str, Any] | None:
        chunk = await self._find_chunk(app_id, MemoryKind.DYNAMIC_BEHAVIOR, f"behavior:{trigger}")
        if chunk is None:
            return None
        await self._increment_access(chunk)
        return chunk.extra

    async def get_run_history(
        self, app_id: str, workflow_name: str
    ) -> dict[str, Any]:
        chunk = await self._find_chunk(
            app_id, MemoryKind.EXECUTION_LEARNING, f"run_success:{workflow_name}"
        )
        if chunk is None:
            return {"run_count": 0, "confidence": 0.0}

        run_count = chunk.extra.get("run_count", 0)
        # Confidence grows with successful runs, capped at 0.95
        confidence = min(0.95, 0.5 + run_count * 0.05)
        return {"run_count": run_count, "confidence": round(confidence, 2)}

    async def _find_chunk(
        self,
        app_id: str,
        kind: MemoryKind,
        key: str,
    ) -> AIMemoryChunk | None:
        stmt = select(AIMemoryChunk).where(
            AIMemoryChunk.application_id == app_id,
            AIMemoryChunk.kind == kind,
        )
        result = await self.db.execute(stmt)
        chunks = result.scalars().all()
        for chunk in chunks:
            if chunk.extra and chunk.extra.get("key") == key:
                return chunk
        return None

    async def _increment_access(self, chunk: AIMemoryChunk) -> None:
        chunk.access_count = (chunk.access_count or 0) + 1
        chunk.last_accessed_at = datetime.utcnow()
        await self.db.commit()
