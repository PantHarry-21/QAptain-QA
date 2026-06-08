from __future__ import annotations
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Any

from app.db.models import ScenarioPriority, ExecutionStatus, RiskLevel


class ScenarioCreate(BaseModel):
    application_id: str
    title: str = Field(..., min_length=3, max_length=512)
    description: str | None = None
    priority: ScenarioPriority = ScenarioPriority.MEDIUM
    tags: list[str] = []
    module_id: str | None = None


class ScenarioBulkImport(BaseModel):
    application_id: str
    scenarios: list[ScenarioCreate]


class ScenarioResponse(BaseModel):
    id: str
    application_id: str
    title: str
    description: str | None
    priority: str
    tags: list[str]
    module_id: str | None
    module_name: str | None = None
    module_url: str | None = None
    source: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class ExecutionPlanRequest(BaseModel):
    scenario_id: str
    execution_mode: str = "functional"
    force_regenerate: bool = False


class ExecutionPlanResponse(BaseModel):
    id: str
    scenario_id: str
    version: int
    execution_mode: str
    plan_data: dict[str, Any]
    ai_reasoning: str | None
    workflow_stages: list[dict[str, Any]]
    risk_score: float
    estimated_duration_seconds: int | None
    created_at: datetime

    class Config:
        from_attributes = True


class ExecutionTrigger(BaseModel):
    plan_id: str
    environment_id: str
    credential_id: str | None = None


class ExecutionRunResponse(BaseModel):
    id: str
    scenario_id: str
    plan_id: str
    status: str
    started_at: datetime | None
    completed_at: datetime | None
    total_steps: int
    passed_steps: int
    failed_steps: int
    healed_steps: int
    video_path: str | None

    class Config:
        from_attributes = True


class ExecutionStepResponse(BaseModel):
    id: str
    sequence: int
    action_type: str
    description: str | None
    status: str
    duration_ms: int | None
    healing_triggered: bool
    healing_attempts: list[dict[str, Any]]
    screenshot_path: str | None
    error_message: str | None

    class Config:
        from_attributes = True


class ReportResponse(BaseModel):
    id: str
    run_id: str
    risk_level: str
    quality_score: float | None
    summary: dict[str, Any]
    insights: list[dict[str, Any]]
    rca_analysis: dict[str, Any]
    recommendations: list[dict[str, Any]]
    timeline: list[dict[str, Any]]
    evidence: dict[str, Any]
    created_at: datetime

    class Config:
        from_attributes = True
