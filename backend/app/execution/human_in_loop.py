"""
Human-in-the-loop manager — pauses execution for human input on ambiguous decisions.
"""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import HumanDecision, WorkspacePreference

log = structlog.get_logger()

DEFAULT_TIMEOUT_SECONDS = 180


@dataclass
class InputRequest:
    run_id: str
    prompt: str
    options: list[str]
    input_type: str = "choice"  # "choice" | "text" | "confirm"
    context: str = ""
    preference_key: str = ""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class InputResponse:
    request_id: str
    value: str
    save_as_preference: bool = False


class HumanInLoopManager:
    """Manages pause/resume for human decisions during automated execution."""

    def __init__(
        self,
        db: AsyncSession,
        event_callback: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.db = db
        self.event_callback = event_callback
        self._pending: dict[str, asyncio.Future[InputResponse]] = {}

    async def request_input(
        self,
        request: InputRequest,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        app_id: str | None = None,
    ) -> str | None:
        if request.preference_key and app_id:
            saved = await self._recall_preference(app_id, request.preference_key)
            if saved is not None:
                log.info(
                    "Returning saved preference",
                    key=request.preference_key,
                    value=saved,
                )
                return str(saved)

        decision = HumanDecision(
            execution_run_id=request.run_id,
            question=request.prompt,
            context=request.context,
            options=request.options,
        )
        self.db.add(decision)
        await self.db.flush()
        decision_id = decision.id

        loop = asyncio.get_event_loop()
        future: asyncio.Future[InputResponse] = loop.create_future()
        self._pending[request.request_id] = future

        if self.event_callback:
            self.event_callback("user_input_required", {
                "run_id": request.run_id,
                "request_id": request.request_id,
                "decision_id": decision_id,
                "prompt": request.prompt,
                "context": request.context,
                "options": request.options,
                "input_type": request.input_type,
                "timeout_seconds": timeout_seconds,
            })

        log.info(
            "Waiting for human input",
            run_id=request.run_id,
            request_id=request.request_id,
            timeout=timeout_seconds,
        )

        try:
            response: InputResponse = await asyncio.wait_for(
                asyncio.shield(future), timeout=float(timeout_seconds)
            )
            decision.selected_option = response.value
            decision.resolved_at = datetime.utcnow()
            decision.is_saved_as_preference = response.save_as_preference

            if response.save_as_preference and request.preference_key and app_id:
                await self._save_preference(app_id, request.preference_key, response.value)

            await self.db.commit()
            log.info("Human input received", request_id=request.request_id, value=response.value)
            return response.value

        except asyncio.TimeoutError:
            self._pending.pop(request.request_id, None)
            fallback = request.options[0] if request.options else None
            log.warning(
                "Human input timed out — using fallback",
                request_id=request.request_id,
                fallback=fallback,
            )
            decision.selected_option = fallback
            decision.resolved_at = datetime.utcnow()
            await self.db.commit()
            return fallback

    def receive_response(
        self,
        request_id: str,
        value: str,
        save: bool = False,
    ) -> bool:
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(InputResponse(request_id=request_id, value=value, save_as_preference=save))
        return True

    def is_waiting(self, run_id: str) -> bool:
        return bool(self._pending)

    async def _recall_preference(
        self, app_id: str, preference_key: str
    ) -> Any | None:
        stmt = select(WorkspacePreference).where(
            WorkspacePreference.application_id == app_id,
            WorkspacePreference.preference_key == preference_key,
        )
        result = await self.db.execute(stmt)
        pref = result.scalar_one_or_none()
        return pref.preference_value if pref else None

    async def _save_preference(
        self, app_id: str, preference_key: str, value: Any
    ) -> None:
        stmt = select(WorkspacePreference).where(
            WorkspacePreference.application_id == app_id,
            WorkspacePreference.preference_key == preference_key,
        )
        result = await self.db.execute(stmt)
        pref = result.scalar_one_or_none()

        if pref:
            pref.preference_value = value
        else:
            pref = WorkspacePreference(
                application_id=app_id,
                preference_key=preference_key,
                preference_value=value,
            )
            self.db.add(pref)

        await self.db.flush()
