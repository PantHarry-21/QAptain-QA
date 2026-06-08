from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from typing import Any

from app.db.models import ExploreMode, ExploreStatus


class ExploreStart(BaseModel):
    application_id: str
    mode: ExploreMode = ExploreMode.SMART
    selected_module_ids: list[str] | None = None

class ExploreDiscover(BaseModel):
    application_id: str


class ExploreSessionResponse(BaseModel):
    id: str
    application_id: str
    mode: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    pages_discovered: int
    modules_discovered: int
    workflows_discovered: int
    summary: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class ExploreLogResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    timestamp: datetime
    level: str
    category: str | None
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict, validation_alias="extra")


class HumanDecisionRequest(BaseModel):
    decision_id: str
    selected_option: dict[str, Any]
    save_as_preference: bool = True


class HumanDecisionResponse(BaseModel):
    id: str
    question: str
    context: str | None
    options: list[dict[str, Any]]
    selected_option: dict[str, Any] | None
    resolved_at: datetime | None
    is_saved_as_preference: bool

    class Config:
        from_attributes = True


class KnowledgeGraphResponse(BaseModel):
    id: str
    application_id: str
    version: int
    modules_count: int
    pages_count: int
    workflows_count: int
    graph_data: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True


class ModuleResponse(BaseModel):
    id: str
    name: str
    description: str | None
    url_pattern: str | None
    icon: str | None
    semantic_tags: list[str]
    pages_count: int = 0
    workflows_count: int = 0

    class Config:
        from_attributes = True
