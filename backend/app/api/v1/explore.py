from __future__ import annotations
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import (
    User, Application, ExploreSession, ExploreLog, HumanDecision,
    KnowledgeGraph, ExploreStatus,
)
from app.core.dependencies import get_current_user
from app.schemas.explore import (
    ExploreStart, ExploreSessionResponse, ExploreLogResponse,
    HumanDecisionRequest, HumanDecisionResponse, KnowledgeGraphResponse, ExploreDiscover
)
from app.explore.explore_engine import ExploreEngine

router = APIRouter()

# Global registry of running explorer engines — allows cancel endpoint to signal them
_running_explores: dict[str, ExploreEngine] = {}

@router.post("/discover", response_model=ExploreSessionResponse, status_code=201)
async def discover_modules(
    payload: ExploreDiscover,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Application).where(Application.id == payload.application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    # Check for running session
    running = await db.execute(
        select(ExploreSession).where(
            ExploreSession.application_id == payload.application_id,
            ExploreSession.status == ExploreStatus.RUNNING,
        )
    )
    if running.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Explore session already running for this application")

    session = ExploreSession(
        application_id=payload.application_id,
        mode=ExploreMode.SMART,
        status=ExploreStatus.PENDING,
        triggered_by=current_user.id,
    )
    db.add(session)
    await db.commit()

    # Launch exploration in background for discovery only
    background_tasks.add_task(_run_explore, session.id, app.id, discover_only=True)

    return ExploreSessionResponse.model_validate(session)

@router.post("/start", response_model=ExploreSessionResponse, status_code=201)
async def start_explore(
    payload: ExploreStart,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Application).where(Application.id == payload.application_id))
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")

    # Check for running session
    running = await db.execute(
        select(ExploreSession).where(
            ExploreSession.application_id == payload.application_id,
            ExploreSession.status == ExploreStatus.RUNNING,
        )
    )
    if running.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Explore session already running for this application")

    session = ExploreSession(
        application_id=payload.application_id,
        mode=payload.mode,
        status=ExploreStatus.PENDING,
        triggered_by=current_user.id,
    )
    db.add(session)
    await db.commit()

    # Launch exploration in background
    background_tasks.add_task(_run_explore, session.id, app.id, discover_only=False, module_ids=payload.selected_module_ids)

    return ExploreSessionResponse.model_validate(session)


@router.get("/{session_id}", response_model=ExploreSessionResponse)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ExploreSession).where(ExploreSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return ExploreSessionResponse.model_validate(session)


@router.get("/{session_id}/logs", response_model=list[ExploreLogResponse])
async def get_logs(
    session_id: str,
    since_id: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(ExploreLog).where(ExploreLog.session_id == session_id)
    if since_id:
        # Return logs after the given id (for polling)
        result_since = await db.execute(select(ExploreLog).where(ExploreLog.id == since_id))
        since_log = result_since.scalar_one_or_none()
        if since_log:
            query = query.where(ExploreLog.timestamp > since_log.timestamp)
    query = query.order_by(ExploreLog.timestamp)
    result = await db.execute(query)
    return [ExploreLogResponse.model_validate(l) for l in result.scalars().all()]


@router.get("/{session_id}/pending-decision", response_model=Optional[HumanDecisionResponse])
async def get_pending_decision(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(HumanDecision).where(
            HumanDecision.session_id == session_id,
            HumanDecision.selected_option == None,
        )
    )
    decision = result.scalar_one_or_none()
    if not decision:
        return None
    return HumanDecisionResponse.model_validate(decision)


@router.post("/{session_id}/decide", response_model=HumanDecisionResponse)
async def resolve_decision(
    session_id: str,
    payload: HumanDecisionRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime
    result = await db.execute(select(HumanDecision).where(HumanDecision.id == payload.decision_id))
    decision = result.scalar_one_or_none()
    if not decision:
        raise HTTPException(status_code=404, detail="Decision not found")

    decision.selected_option = payload.selected_option
    decision.decided_by = current_user.id
    decision.resolved_at = datetime.utcnow()
    decision.is_saved_as_preference = payload.save_as_preference

    if payload.save_as_preference:
        try:
            from app.db.models import WorkspacePreference
            app_id_result = await db.execute(
                select(ExploreSession.application_id).where(ExploreSession.id == session_id)
            )
            app_id = app_id_result.scalar()
            if app_id:
                pref = WorkspacePreference(
                    application_id=app_id,
                    preference_key=f"decision.{str(payload.decision_id)[:8]}",
                    preference_value=payload.selected_option,
                )
                db.add(pref)
        except Exception:
            pass  # preference save is non-critical

    await db.commit()
    await db.refresh(decision)
    return HumanDecisionResponse.model_validate(decision)


@router.get("/application/{application_id}/active", response_model=Optional[ExploreSessionResponse])
async def get_active_session(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return the currently running or waiting session for an application, if any."""
    result = await db.execute(
        select(ExploreSession)
        .where(
            ExploreSession.application_id == application_id,
            ExploreSession.status.in_([ExploreStatus.RUNNING, ExploreStatus.WAITING_HUMAN, ExploreStatus.PENDING]),
        )
        .order_by(ExploreSession.created_at.desc())
        .limit(1)
    )
    session = result.scalar_one_or_none()
    if not session:
        return None
    return ExploreSessionResponse.model_validate(session)


@router.post("/{session_id}/cancel", response_model=ExploreSessionResponse)
async def cancel_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import datetime
    result = await db.execute(select(ExploreSession).where(ExploreSession.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    if session.status in (ExploreStatus.COMPLETED, ExploreStatus.FAILED, ExploreStatus.CANCELLED):
        raise HTTPException(status_code=409, detail="Session already finished")

    # Signal the running explorer engine to stop gracefully
    if session_id in _running_explores:
        engine = _running_explores[session_id]
        engine.request_stop()

    session.status = ExploreStatus.CANCELLED
    session.completed_at = datetime.utcnow()
    await db.commit()
    return ExploreSessionResponse.model_validate(session)


@router.get("/application/{application_id}/knowledge", response_model=Optional[KnowledgeGraphResponse])
async def get_knowledge_graph(
    application_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(KnowledgeGraph)
        .where(KnowledgeGraph.application_id == application_id)
        .order_by(KnowledgeGraph.version.desc())
    )
    kg = result.scalar_one_or_none()
    if not kg:
        return None
    return KnowledgeGraphResponse.model_validate(kg)


async def _run_explore(session_id: str, application_id: str, discover_only: bool = False, module_ids: list[str] = None):
    """Background task that runs the explore engine."""
    from app.db.session import AsyncSessionFactory
    async with AsyncSessionFactory() as db:
        engine = ExploreEngine(db)
        # Register engine so cancel endpoint can signal it
        _running_explores[session_id] = engine
        try:
            await engine.run(session_id, application_id, discover_only=discover_only, module_ids=module_ids)
        finally:
            # Unregister when done
            _running_explores.pop(session_id, None)
