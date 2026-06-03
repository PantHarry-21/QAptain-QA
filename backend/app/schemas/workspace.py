from datetime import datetime
from pydantic import BaseModel, Field, HttpUrl
from typing import Any

from app.db.models import ExploreMode, EnvironmentType, WorkspaceRole


class WorkspaceCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=255)


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=255)
    description: str | None = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    slug: str
    description: str | None
    created_at: datetime
    member_count: int = 0

    class Config:
        from_attributes = True


class ApplicationCreate(BaseModel):
    workspace_id: str
    # Core identity
    name: str = Field(..., min_length=1, max_length=255)
    base_url: str
    # AI guidance — the most important field
    description: str = Field(
        ...,
        min_length=10,
        description="Describe the application and its modules. This guides AI exploration and understanding."
    )
    # Initial auth
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    environment_name: str = Field(default="Default")
    environment_type: EnvironmentType = EnvironmentType.DEVELOPMENT
    # Exploration
    explore_mode: ExploreMode = ExploreMode.SMART


class ApplicationResponse(BaseModel):
    id: str
    workspace_id: str
    name: str
    base_url: str
    description: str | None
    explore_mode: str
    created_at: datetime
    has_knowledge: bool = False
    last_explored_at: datetime | None = None
    modules_count: int = 0

    class Config:
        from_attributes = True


class EnvironmentCreate(BaseModel):
    name: str
    env_type: EnvironmentType = EnvironmentType.DEVELOPMENT
    base_url: str
    is_default: bool = False


class EnvironmentResponse(BaseModel):
    id: str
    application_id: str
    name: str
    env_type: str
    base_url: str
    is_default: bool

    class Config:
        from_attributes = True


class MemberInvite(BaseModel):
    email: str
    role: WorkspaceRole = WorkspaceRole.MEMBER
