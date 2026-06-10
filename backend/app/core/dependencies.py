from __future__ import annotations
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.session import get_db
from app.db.models import User, Workspace, WorkspaceMember, WorkspaceRole, Application, ExecutionRun, Scenario
from app.core.security import decode_token

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    user_id = decode_token(credentials.credentials)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    result = await db.execute(select(User).where(User.id == user_id, User.is_active == True))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


async def get_workspace_access(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    min_role: WorkspaceRole = WorkspaceRole.VIEWER,
) -> WorkspaceMember:
    result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No workspace access")
    role_hierarchy = {
        WorkspaceRole.VIEWER: 0,
        WorkspaceRole.MEMBER: 1,
        WorkspaceRole.ADMIN: 2,
        WorkspaceRole.OWNER: 3,
    }
    if role_hierarchy[member.role] < role_hierarchy[min_role]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient permissions")
    return member


async def require_app_access(
    application_id: str,
    current_user: User,
    db: AsyncSession,
) -> Application:
    """Load an Application and verify the current user is a member of its workspace."""
    app_row = await db.execute(select(Application).where(Application.id == application_id))
    app = app_row.scalar_one_or_none()
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    await get_workspace_access(app.workspace_id, current_user, db)
    return app


async def require_run_access(
    run_id: str,
    current_user: User,
    db: AsyncSession,
) -> ExecutionRun:
    """Load an ExecutionRun and verify the current user is a member of its workspace."""
    run_row = await db.execute(select(ExecutionRun).where(ExecutionRun.id == run_id))
    run = run_row.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Execution run not found")
    scenario_row = await db.execute(select(Scenario).where(Scenario.id == run.scenario_id))
    scenario = scenario_row.scalar_one_or_none()
    if scenario:
        await require_app_access(scenario.application_id, current_user, db)
    return run
