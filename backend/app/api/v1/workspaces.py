from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete as sql_delete, update as sql_update
from slugify import slugify
import uuid

from app.db.session import get_db
from app.db.models import (
    User, Workspace, WorkspaceMember, WorkspaceRole, Application,
    Environment, Credential, EnvironmentType,
    Scenario, ExecutionRun,
)
from app.core.dependencies import get_current_user, get_workspace_access
from app.schemas.workspace import (
    WorkspaceCreate, WorkspaceUpdate, WorkspaceResponse,
    ApplicationCreate, ApplicationResponse,
    EnvironmentCreate, EnvironmentResponse,
    MemberInvite,
)
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

@router.put("/{workspace_id}", response_model=WorkspaceResponse)
async def update_workspace(
    workspace_id: str,
    payload: WorkspaceUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename / update a workspace (owner only)."""
    ws_result = await db.execute(select(Workspace).where(Workspace.id == workspace_id))
    ws = ws_result.scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    member_result = await db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == current_user.id,
            WorkspaceMember.role == WorkspaceRole.OWNER,
        )
    )
    if not member_result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Only workspace owners can edit a workspace")
    if payload.name is not None:
        ws.name = payload.name.strip()
        ws.slug = slugify(ws.name) or ws.slug
    if payload.description is not None:
        ws.description = payload.description
    await db.commit()
    await db.refresh(ws)
    return WorkspaceResponse.model_validate(ws)


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

    # Several FKs lack ondelete=CASCADE so PostgreSQL blocks the cascade chain.
    # Clean them up manually in dependency order before deleting the workspace.
    app_ids_result = await db.execute(
        select(Application.id).where(Application.workspace_id == workspace_id)
    )
    app_ids = [row[0] for row in app_ids_result.all()]

    if app_ids:
        # 1. Break circular FK: applications.knowledge_graph_id → knowledge_graphs
        await db.execute(
            sql_update(Application)
            .where(Application.workspace_id == workspace_id)
            .values(knowledge_graph_id=None)
        )

        # 2. Null out scenarios.module_id so module cascade-delete doesn't conflict
        #    (scenarios also cascade from application, but order vs modules is undefined)
        await db.execute(
            sql_update(Scenario)
            .where(Scenario.application_id.in_(app_ids))
            .values(module_id=None)
        )

        # 3. Delete execution_runs — no cascade from environments, scenarios, or plans.
        #    execution_steps / execution_logs / execution_reports cascade from runs.
        scenario_ids_result = await db.execute(
            select(Scenario.id).where(Scenario.application_id.in_(app_ids))
        )
        scenario_ids = [row[0] for row in scenario_ids_result.all()]
        if scenario_ids:
            await db.execute(
                sql_delete(ExecutionRun).where(ExecutionRun.scenario_id.in_(scenario_ids))
            )

        await db.commit()

    # Now delete the workspace — CASCADE handles the rest cleanly
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
