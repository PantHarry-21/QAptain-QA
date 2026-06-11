"""
from __future__ import annotations
QAptain Database Models
Complete entity schema for the AI-native automation platform.
"""
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean, Column, DateTime, Enum, Float, ForeignKey, Index,
    Integer, JSON, String, Text, UniqueConstraint, func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.db.session import Base
import enum


# ─── Enums ────────────────────────────────────────────────────────────────────

class WorkspaceRole(str, enum.Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"
    VIEWER = "VIEWER"


class ExploreMode(str, enum.Enum):
    FULL = "FULL"
    SMART = "SMART"
    SKIP = "SKIP"


class ExploreStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    WAITING_HUMAN = "WAITING_HUMAN"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    STOPPED = "STOPPED"


class ExecutionStatus(str, enum.Enum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    PARTIAL = "PARTIAL"


class StepStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    HEALED = "HEALED"


class EnvironmentType(str, enum.Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    CUSTOM = "custom"


class ScenarioPriority(str, enum.Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class MemoryKind(str, enum.Enum):
    MODULE = "module"
    PAGE = "page"
    WORKFLOW = "workflow"
    SELECTOR = "selector"
    FIELD = "field"
    EXECUTION_LEARNING = "execution_learning"
    DYNAMIC_BEHAVIOR = "dynamic_behavior"


class RiskLevel(str, enum.Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _uuid():
    return str(uuid.uuid4())

def _now():
    return datetime.utcnow()


# ─── Core Identity ────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    name = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_superuser = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    memberships = relationship("WorkspaceMember", back_populates="user")


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True, default=_uuid)
    name = Column(String(255), nullable=False)
    slug = Column(String(255), unique=True, nullable=False, index=True)
    description = Column(Text)
    created_by = Column(String, ForeignKey("users.id"), nullable=False)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    members = relationship("WorkspaceMember", back_populates="workspace")
    applications = relationship("Application", back_populates="workspace", cascade="all, delete-orphan")


class WorkspaceMember(Base):
    __tablename__ = "workspace_members"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"),)

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    role = Column(Enum(WorkspaceRole), default=WorkspaceRole.MEMBER)
    joined_at = Column(DateTime, default=_now)

    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="memberships")


# ─── Application & Configuration ──────────────────────────────────────────────

class Application(Base):
    __tablename__ = "applications"

    id = Column(String, primary_key=True, default=_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)  # Critical: AI guidance + business context
    base_url = Column(String(2048), nullable=False)
    app_type = Column(String(100), default="web")  # web, spa, hybrid
    explore_mode = Column(Enum(ExploreMode), default=ExploreMode.SMART)
    created_by = Column(String, ForeignKey("users.id"))
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)
    # Latest knowledge graph reference (use_alter breaks circular FK with knowledge_graphs)
    knowledge_graph_id = Column(String, ForeignKey("knowledge_graphs.id", use_alter=True, name="fk_app_knowledge_graph"), nullable=True)

    workspace = relationship("Workspace", back_populates="applications")
    environments = relationship("Environment", back_populates="application", cascade="all, delete-orphan")
    credentials = relationship("Credential", back_populates="application", cascade="all, delete-orphan")
    explore_sessions = relationship("ExploreSession", back_populates="application", cascade="all, delete-orphan")
    scenarios = relationship("Scenario", back_populates="application", cascade="all, delete-orphan")
    knowledge_graphs = relationship("KnowledgeGraph", back_populates="application",
                                    foreign_keys="[KnowledgeGraph.application_id]", cascade="all, delete-orphan")
    modules = relationship("ApplicationModule", back_populates="application", cascade="all, delete-orphan")
    memory_chunks = relationship("AIMemoryChunk", back_populates="application", cascade="all, delete-orphan")
    workspace_preferences = relationship("WorkspacePreference", back_populates="application", cascade="all, delete-orphan")
    rbac_scans = relationship("RBACScan", back_populates="application", cascade="all, delete-orphan")


class Environment(Base):
    __tablename__ = "environments"

    id = Column(String, primary_key=True, default=_uuid)
    application_id = Column(String, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(255), nullable=False)
    env_type = Column(Enum(EnvironmentType), default=EnvironmentType.DEVELOPMENT)
    base_url = Column(String(2048), nullable=False)
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_now)

    application = relationship("Application", back_populates="environments")
    credentials = relationship("Credential", back_populates="environment")


class Credential(Base):
    """Encrypted credentials for application authentication."""
    __tablename__ = "credentials"

    id = Column(String, primary_key=True, default=_uuid)
    application_id = Column(String, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    environment_id = Column(String, ForeignKey("environments.id"), nullable=True, index=True)
    label = Column(String(255), nullable=False)
    username = Column(String(512), nullable=False)
    password_encrypted = Column(Text, nullable=False)
    # JSON: multi-step auth blueprint (login URL, field selectors strategy, etc.)
    auth_blueprint = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    application = relationship("Application", back_populates="credentials")
    environment = relationship("Environment", back_populates="credentials")


class RBACScan(Base):
    """RBAC permission scan — logs in as each role and records accessible modules."""
    __tablename__ = "rbac_scans"

    id = Column(String, primary_key=True, default=_uuid)
    application_id = Column(String, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String(50), default="pending")  # pending, running, completed, failed
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    results = Column(JSON, default=dict)  # {modules, roles, scanned_at, progress}
    error_message = Column(Text)
    triggered_by = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_now)

    application = relationship("Application", back_populates="rbac_scans")


# ─── Explore Engine ───────────────────────────────────────────────────────────

class ExploreSession(Base):
    __tablename__ = "explore_sessions"

    id = Column(String, primary_key=True, default=_uuid)
    application_id = Column(String, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    mode = Column(Enum(ExploreMode), nullable=False)
    status = Column(Enum(ExploreStatus), default=ExploreStatus.PENDING)
    triggered_by = Column(String, ForeignKey("users.id"))
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    pages_discovered = Column(Integer, default=0)
    modules_discovered = Column(Integer, default=0)
    workflows_discovered = Column(Integer, default=0)
    discover_only = Column(Boolean, default=False)
    selected_module_ids = Column(JSON, default=None)  # Set by user after discovery, signals engine to continue
    error_message = Column(Text)
    summary = Column(JSON, default=dict)  # Explore summary stats
    created_at = Column(DateTime, default=_now)

    application = relationship("Application", back_populates="explore_sessions")
    logs = relationship("ExploreLog", back_populates="session", cascade="all, delete-orphan")
    human_decisions = relationship("HumanDecision", back_populates="session", cascade="all, delete-orphan")


class ExploreLog(Base):
    """Live semantic logs emitted during exploration — not technical logs."""
    __tablename__ = "explore_logs"
    __table_args__ = (
        Index("ix_explore_logs_session_timestamp", "session_id", "timestamp"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    session_id = Column(String, ForeignKey("explore_sessions.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime, default=_now)
    level = Column(String(20), default="INFO")  # INFO, SUCCESS, WARNING, MILESTONE
    category = Column(String(100))  # login, module, form, workflow, navigation
    message = Column(Text, nullable=False)  # Human-readable semantic message
    extra = Column("metadata", JSON, default=dict)  # Supporting data (URL, element, confidence)

    session = relationship("ExploreSession", back_populates="logs")


class HumanDecision(Base):
    """Human-in-the-loop decisions during exploration or execution."""
    __tablename__ = "human_decisions"

    id = Column(String, primary_key=True, default=_uuid)
    session_id = Column(String, ForeignKey("explore_sessions.id", ondelete="CASCADE"), nullable=True)
    execution_run_id = Column(String, ForeignKey("execution_runs.id", ondelete="CASCADE"), nullable=True)
    question = Column(Text, nullable=False)
    context = Column(Text)  # Why the AI is asking
    options = Column(JSON, nullable=False)  # List of option objects {label, value, description}
    selected_option = Column(JSON)  # The chosen option
    decided_by = Column(String, ForeignKey("users.id"))
    created_at = Column(DateTime, default=_now)
    resolved_at = Column(DateTime)
    is_saved_as_preference = Column(Boolean, default=False)

    session = relationship("ExploreSession", back_populates="human_decisions")
    execution_run = relationship("ExecutionRun", back_populates="human_decisions")


# ─── Application Knowledge ────────────────────────────────────────────────────

class KnowledgeGraph(Base):
    """Full semantic knowledge graph of a discovered application."""
    __tablename__ = "knowledge_graphs"

    id = Column(String, primary_key=True, default=_uuid)
    application_id = Column(String, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, default=1)
    explore_session_id = Column(String, ForeignKey("explore_sessions.id"), nullable=True)
    graph_data = Column(JSON, nullable=False)  # Full serialized graph
    modules_count = Column(Integer, default=0)
    pages_count = Column(Integer, default=0)
    workflows_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_now)

    application = relationship("Application", back_populates="knowledge_graphs",
                                foreign_keys=[application_id])


class ApplicationModule(Base):
    """A logical module/feature area of the application."""
    __tablename__ = "application_modules"

    id = Column(String, primary_key=True, default=_uuid)
    application_id = Column(String, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    url_pattern = Column(String(1024))
    icon = Column(String(100))  # Lucide icon name
    is_accordion = Column(Boolean, default=False)  # True = has sub-items, no direct URL
    parent_id = Column(String, ForeignKey("application_modules.id"), nullable=True, index=True)
    order_index = Column(Integer, default=0)
    semantic_tags = Column(JSON, default=list)  # AI-inferred tags: ["crud", "approval", "table"]
    created_at = Column(DateTime, default=_now)

    application = relationship("Application", back_populates="modules")
    pages = relationship("ApplicationPage", back_populates="module", cascade="all, delete-orphan")
    workflows = relationship("ApplicationWorkflow", back_populates="module", cascade="all, delete-orphan")
    children = relationship(
        "ApplicationModule",
        foreign_keys="[ApplicationModule.parent_id]",
        back_populates="parent",
    )
    parent = relationship(
        "ApplicationModule",
        foreign_keys="[ApplicationModule.parent_id]",
        back_populates="children",
        remote_side="ApplicationModule.id",
    )


class ApplicationPage(Base):
    """A discovered page within a module."""
    __tablename__ = "application_pages"

    id = Column(String, primary_key=True, default=_uuid)
    module_id = Column(String, ForeignKey("application_modules.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    url = Column(String(2048), nullable=False)
    url_pattern = Column(String(1024))  # Regex for dynamic routes
    page_type = Column(String(100))  # list, form, detail, dashboard, modal, wizard
    semantic_map = Column(JSON, default=dict)  # Compressed semantic UI state
    forms = Column(JSON, default=list)  # Discovered form structures
    tables = Column(JSON, default=list)  # Discovered table structures
    workflows = Column(JSON, default=list)  # Discovered workflows (also stored as ApplicationWorkflow rows)
    navigation_links = Column(JSON, default=list)
    dynamic_behaviors = Column(JSON, default=list)  # Conditional renders, progressive forms
    page_data = Column(JSON, default=dict)  # General-purpose storage (e.g. initial_state snapshot)
    discovered_at = Column(DateTime, default=_now)
    last_updated_at = Column(DateTime, default=_now)

    module = relationship("ApplicationModule", back_populates="pages")
    elements = relationship("SemanticElement", back_populates="page", cascade="all, delete-orphan")


class SemanticElement(Base):
    """A semantically understood UI element — never raw selectors."""
    __tablename__ = "semantic_elements"

    id = Column(String, primary_key=True, default=_uuid)
    page_id = Column(String, ForeignKey("application_pages.id", ondelete="CASCADE"), nullable=False, index=True)
    semantic_label = Column(String(512), nullable=False)  # "Username input field"
    element_type = Column(String(100))  # button, textbox, dropdown, checkbox, table, modal
    role = Column(String(100))  # aria role
    purpose = Column(Text)  # "Primary authentication button"
    workflow_stage = Column(String(255))  # "Credential Authentication"
    # Selector strategies: [{type: "css", value: "...", confidence: 0.9}, ...]
    selectors = Column(JSON, default=list)
    # Healing strategies ranked by success rate
    healing_strategies = Column(JSON, default=list)
    confidence = Column(Float, default=1.0)
    # Observed network actions triggered by this element
    network_triggers = Column(JSON, default=list)
    # Dynamic behavior: what appears after interaction
    dynamic_reveals = Column(JSON, default=list)
    last_validated_at = Column(DateTime)
    created_at = Column(DateTime, default=_now)

    page = relationship("ApplicationPage", back_populates="elements")


class ApplicationWorkflow(Base):
    """A multi-step business workflow within a module."""
    __tablename__ = "application_workflows"

    id = Column(String, primary_key=True, default=_uuid)
    module_id = Column(String, ForeignKey("application_modules.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    workflow_type = Column(String(100))  # crud_create, crud_read, crud_update, crud_delete, approval, search
    # Ordered stages: [{stage: 1, description: "...", url: "...", elements: [...]}]
    stages = Column(JSON, default=list)
    # Entry point: URL and trigger action
    entry_point = Column(JSON, default=dict)
    # Expected outcomes: what constitutes success
    success_indicators = Column(JSON, default=list)
    discovered_at = Column(DateTime, default=_now)

    module = relationship("ApplicationModule", back_populates="workflows")


class WorkspacePreference(Base):
    """Persisted human-in-loop decisions that become execution defaults."""
    __tablename__ = "workspace_preferences"

    id = Column(String, primary_key=True, default=_uuid)
    application_id = Column(String, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    preference_key = Column(String(512), nullable=False)  # e.g. "login.location_selection"
    preference_value = Column(JSON, nullable=False)  # Selected option
    description = Column(Text)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    application = relationship("Application", back_populates="workspace_preferences")


# ─── Test Cases & Scenarios ───────────────────────────────────────────────────

class Scenario(Base):
    """Business-level test scenario — natural language, not technical steps."""
    __tablename__ = "scenarios"

    id = Column(String, primary_key=True, default=_uuid)
    application_id = Column(String, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(512), nullable=False)
    description = Column(Text)  # Natural language description
    priority = Column(Enum(ScenarioPriority), default=ScenarioPriority.MEDIUM)
    tags = Column(JSON, default=list)
    module_id = Column(String, ForeignKey("application_modules.id"), nullable=True, index=True)
    source = Column(String(100), default="manual")  # manual, excel, csv, ai_generated, jira
    external_id = Column(String(512))  # Jira/TestRail ID
    is_active = Column(Boolean, default=True)
    is_smoke = Column(Boolean, default=False)  # smoke tests always run first as sanity checks
    created_by = Column(String, ForeignKey("users.id"))
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    application = relationship("Application", back_populates="scenarios")
    execution_plans = relationship("ExecutionPlan", back_populates="scenario", cascade="all, delete-orphan")
    runs = relationship("ExecutionRun", back_populates="scenario")


# ─── Execution Engine ─────────────────────────────────────────────────────────

class ExecutionPlan(Base):
    """Structured AI-generated execution plan for a scenario."""
    __tablename__ = "execution_plans"

    id = Column(String, primary_key=True, default=_uuid)
    scenario_id = Column(String, ForeignKey("scenarios.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, default=1)
    execution_mode = Column(String(100), default="functional")
    plan_data = Column(JSON, nullable=False)  # {workflow, steps: [{action, ...}]}
    ai_reasoning = Column(Text)  # Why the AI chose these steps
    semantic_intent = Column(JSON, default=dict)  # Inferred intent structure
    workflow_stages = Column(JSON, default=list)  # High-level workflow stages
    risk_score = Column(Float, default=0.0)
    estimated_duration_seconds = Column(Integer)
    created_by_model = Column(String(255))  # AI model used
    created_at = Column(DateTime, default=_now)

    scenario = relationship("Scenario", back_populates="execution_plans")
    runs = relationship("ExecutionRun", back_populates="plan")


class ExecutionRun(Base):
    """A single execution instance of an execution plan."""
    __tablename__ = "execution_runs"

    id = Column(String, primary_key=True, default=_uuid)
    scenario_id = Column(String, ForeignKey("scenarios.id"), nullable=False, index=True)
    plan_id = Column(String, ForeignKey("execution_plans.id"), nullable=False, index=True)
    environment_id = Column(String, ForeignKey("environments.id"), nullable=False, index=True)
    credential_id = Column(String, ForeignKey("credentials.id"), nullable=True)
    status = Column(Enum(ExecutionStatus), default=ExecutionStatus.PENDING)
    triggered_by = Column(String, ForeignKey("users.id"))
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    total_steps = Column(Integer, default=0)
    passed_steps = Column(Integer, default=0)
    failed_steps = Column(Integer, default=0)
    skipped_steps = Column(Integer, default=0)
    healed_steps = Column(Integer, default=0)
    error_message = Column(Text)
    # Screenshots of key moments
    screenshot_paths = Column(JSON, default=list)
    # Video recording path
    video_path = Column(String(2048))
    # Browser/environment metadata
    browser_metadata = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_now)

    scenario = relationship("Scenario", back_populates="runs")
    plan = relationship("ExecutionPlan", back_populates="runs")
    steps = relationship("ExecutionStep", back_populates="run", cascade="all, delete-orphan",
                         order_by="ExecutionStep.sequence")
    logs = relationship("ExecutionLog", back_populates="run", cascade="all, delete-orphan")
    report = relationship("ExecutionReport", back_populates="run", uselist=False, cascade="all, delete-orphan")
    human_decisions = relationship("HumanDecision", back_populates="execution_run")


class ExecutionStep(Base):
    """A single action step within an execution run."""
    __tablename__ = "execution_steps"

    id = Column(String, primary_key=True, default=_uuid)
    run_id = Column(String, ForeignKey("execution_runs.id", ondelete="CASCADE"), nullable=False)
    sequence = Column(Integer, nullable=False)
    action_type = Column(String(100), nullable=False)  # navigate, click, fill, assert, wait
    description = Column(Text)  # Human-readable semantic description
    # Original plan step data
    plan_step = Column(JSON, nullable=False)
    status = Column(Enum(StepStatus), default=StepStatus.PENDING)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)
    duration_ms = Column(Integer)
    # Evidence
    screenshot_path = Column(String(2048))
    # Self-healing info
    healing_triggered = Column(Boolean, default=False)
    healing_attempts = Column(JSON, default=list)  # [{strategy, selector, success, reason}]
    # AI reasoning for this step
    ai_reasoning = Column(Text)
    # Error details
    error_type = Column(String(255))
    error_message = Column(Text)
    error_screenshot_path = Column(String(2048))
    # Semantic state before/after
    state_before = Column(JSON)
    state_after = Column(JSON)

    run = relationship("ExecutionRun", back_populates="steps")


class ExecutionLog(Base):
    """Real-time log entries during execution."""
    __tablename__ = "execution_logs"
    __table_args__ = (
        Index("ix_execution_logs_run_timestamp", "run_id", "timestamp"),
    )

    id = Column(String, primary_key=True, default=_uuid)
    run_id = Column(String, ForeignKey("execution_runs.id", ondelete="CASCADE"), nullable=False)
    step_id = Column(String, ForeignKey("execution_steps.id"), nullable=True)
    timestamp = Column(DateTime, default=_now)
    level = Column(String(20), default="INFO")
    category = Column(String(100))  # action, healing, validation, navigation, ai_reasoning
    message = Column(Text, nullable=False)
    extra = Column("metadata", JSON, default=dict)

    run = relationship("ExecutionRun", back_populates="logs")


class ExecutionReport(Base):
    """AI-native post-execution report with insights and RCA."""
    __tablename__ = "execution_reports"

    id = Column(String, primary_key=True, default=_uuid)
    run_id = Column(String, ForeignKey("execution_runs.id", ondelete="CASCADE"), nullable=False, unique=True)
    risk_level = Column(Enum(RiskLevel), default=RiskLevel.LOW)
    quality_score = Column(Float)  # 0-100
    # Structured summary
    summary = Column(JSON, nullable=False)
    # AI-generated insights
    insights = Column(JSON, default=list)
    # Root cause analysis for failures
    rca_analysis = Column(JSON, default=dict)
    # Recommended actions
    recommendations = Column(JSON, default=list)
    # Execution timeline (semantic events)
    timeline = Column(JSON, default=list)
    # Evidence index: screenshots, DOM snapshots, network logs
    evidence = Column(JSON, default=dict)
    created_at = Column(DateTime, default=_now)

    run = relationship("ExecutionRun", back_populates="report")


# ─── Memory & Learning ────────────────────────────────────────────────────────

class AIMemoryChunk(Base):
    """Persisted semantic knowledge — indexed in ChromaDB, stored in Postgres."""
    __tablename__ = "ai_memory_chunks"

    id = Column(String, primary_key=True, default=_uuid)
    application_id = Column(String, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(Enum(MemoryKind), nullable=False, index=True)
    content = Column(Text, nullable=False)  # The knowledge text
    # ChromaDB document ID for vector retrieval
    chroma_doc_id = Column(String(512))
    extra = Column("metadata", JSON, default=dict)
    confidence = Column(Float, default=1.0)
    access_count = Column(Integer, default=0)
    last_accessed_at = Column(DateTime)
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    application = relationship("Application", back_populates="memory_chunks")


class SelectorMemory(Base):
    """Ranked selector strategies for semantic elements — improves over time."""
    __tablename__ = "selector_memories"

    id = Column(String, primary_key=True, default=_uuid)
    element_id = Column(String, ForeignKey("semantic_elements.id", ondelete="CASCADE"), nullable=False, unique=True)
    # Ordered list of selector strategies with scores
    strategies = Column(JSON, nullable=False)  # [{type, value, score, attempt_count, success_count}]
    best_strategy_index = Column(Integer, default=0)
    overall_confidence = Column(Float, default=1.0)
    # Rolling history of healing attempts
    healing_history = Column(JSON, default=list)  # Last 50 healing events
    updated_at = Column(DateTime, default=_now, onupdate=_now)


class TestDataset(Base):
    """
    Test data items uploaded or typed by the user for use during execution.

    Examples: invalid emails, oversized files, boundary numbers, SQL injection strings.
    The executor picks up matching items by category when running validation/edge-case scenarios.
    """
    __tablename__ = "test_datasets"

    id = Column(String, primary_key=True, default=_uuid)
    application_id = Column(String, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(100), nullable=False)   # invalid_email, invalid_file, boundary_number, etc.
    label = Column(String(512), nullable=False)       # "10 MB file (over limit)"
    data_type = Column(String(50), default="text")   # text | email | number | date | url | file
    text_value = Column(Text)                         # actual value for non-file types
    file_path = Column(String(2048))                  # stored path for file uploads
    file_name = Column(String(512))                   # original filename
    file_size = Column(Integer)                       # bytes
    description = Column(Text)                        # human-readable note
    created_at = Column(DateTime, default=_now)
    updated_at = Column(DateTime, default=_now, onupdate=_now)

    application = relationship("Application", backref="test_datasets")
