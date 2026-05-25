from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete as sql_delete
from slugify import slugify
import uuid

from app.db.session import get_db
from app.db.models import User, Workspace, WorkspaceMember, WorkspaceRole, Application
from app.core.dependencies import get_current_user, get_workspace_access
from app.schemas.workspace import (
    WorkspaceCreate, WorkspaceResponse,
    ApplicationCreate, ApplicationResponse,
    EnvironmentCreate, EnvironmentResponse,
    MemberInvite,
)
from app.db.models import Environment, Credential, EnvironmentType
from app.core.security import encrypt_credential

router = APIRouter()


@router.get("", response_model=list[WorkspaceResponse])
async def list_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Workspace)
        .join(WorkspaceMember, Workspace.id == WorkspaceMember.workspace_id)
        .where(WorkspaceMember.user_id == current_user.id)
        .order_by(Workspace.created_at.desc())
    )
    workspaces = result.scalars().all()
    return [WorkspaceResponse.model_validate(w) for w in workspaces]


@router.post("", response_model=WorkspaceResponse, status_code=status.HTTP_201_CREATED)
async def create_workspace(
    payload: WorkspaceCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    slug = f"{slugify(payload.name)}-{uuid.uuid4().hex[:6]}"
    workspace = Workspace(name=payload.name, slug=slug, created_by=current_user.id)
    db.add(workspace)
    await db.flush()
    member = WorkspaceMember(workspace_id=workspace.id, user_id=current_user.id, role=WorkspaceRole.OWNER)
    db.add(member)
    await db.commit()
    return WorkspaceResponse.model_validate(workspace)


@router.get("/{workspace_id}", response_model=WorkspaceResponse)
async def get_workspace(
    workspace_id: str,
    _member: WorkspaceMember = Depends(lambda wid=None, u=None, db=None: None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ws = result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return WorkspaceResponse.model_validate(ws)


# â”€â”€â”€ Applications within a Workspace â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.delete("/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete a workspace and all its data (owner only)."""
    member_result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
            WorkspaceMember.role == WorkspaceRole.OWNER,
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Only workspace owners can delete a workspace")

    ws_result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    if not ws_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Use a raw DELETE so PostgreSQL's ondelete=CASCADE constraints cascade
    # through workspace_members, applications, and all child tables automatically.
    await db.execute(sql_delete(Workspace).where(Workspace.id == workspace_id))
    await db.commit()


@router.get("/{workspace_id}/applications", response_model=list[ApplicationResponse])
async def list_applications(
    workspace_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Application)
        .where(Application.workspace_id == workspace_id)
        .order_by(Application.created_at.desc())
    )
    apps = result.scalars().all()
    return [ApplicationResponse.model_validate(a) for a in apps]


@router.post("/{workspace_id}/applications", response_model=ApplicationResponse, status_code=201)
async def create_application(
    workspace_id: str,
    payload: ApplicationCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify workspace access
    member_result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="No workspace access")

    # Create application
    app = Application(
        workspace_id=workspace_id,
        name=payload.name,
        base_url=str(payload.base_url),
        description=payload.description,
        explore_mode=payload.explore_mode,
        created_by=current_user.id,
    )
    db.add(app)
    await db.flush()

    # Create default environment
    env = Environment(
        application_id=app.id,
        name=payload.environment_name,
        env_type=payload.environment_type,
        base_url=str(payload.base_url),
        is_default=True,
    )
    db.add(env)
    await db.flush()

    # Store credentials (encrypted)
    cred = Credential(
        application_id=app.id,
        environment_id=env.id,
        label="Default",
        username=payload.username,
        password_encrypted=encrypt_credential(payload.password),
        auth_blueprint={},
    )
    db.add(cred)
    await db.commit()

    return ApplicationResponse.model_validate(app)
