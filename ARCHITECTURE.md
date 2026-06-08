# QAptain v2 Architecture

**AI-native enterprise workflow intelligence platform.**

```
Core Principle:  AI = Brain    |    Selenium + CDP = Hands
```

## Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Next.js 15 + React 19 + TypeScript + Tailwind |
| Backend | FastAPI (Python) — `backend/` |
| Execution | Selenium + Chrome DevTools Protocol |
| AI | Claude/OpenAI abstraction (`app/intelligence/ai_client.py`) |
| Vector Memory | ChromaDB (`app/memory/chroma_store.py`) |
| Database | PostgreSQL + SQLAlchemy async |
| Real-time | WebSocket (FastAPI native) |
| Infrastructure | Docker Compose: Postgres + Redis + ChromaDB |

## Product Flow

```
Workspace Creation → Application Configuration → Agent Explore → Knowledge Graph →
Scenario Selection → Scenario Understanding → Execution Planning →
Smart Execution → AI Validation → Reporting → Memory Improvement
```

## Backend Structure (`backend/`)

```
backend/
├── main.py                          # FastAPI app, routers, WebSocket
├── config.py                        # Settings (pydantic-settings)
├── requirements.txt
└── app/
    ├── api/v1/                      # REST API routes
    │   ├── auth.py                  # Signup, login, JWT
    │   ├── workspaces.py            # Workspace + application CRUD
    │   ├── applications.py          # Application details, environments, modules
    │   ├── scenarios.py             # Scenario CRUD, plan generation, execution
    │   ├── explore.py               # Explore session lifecycle, human decisions
    │   ├── executions.py            # Run status, steps, logs, reports
    │   ├── knowledge.py             # Module/page/workflow knowledge queries
    │   └── reports.py               # AI-native report access
    ├── db/
    │   ├── session.py               # AsyncSession, engine
    │   └── models.py                # All SQLAlchemy models
    ├── schemas/                     # Pydantic request/response schemas
    ├── core/
    │   ├── security.py              # JWT, password hashing, credential encryption
    │   └── dependencies.py          # FastAPI Depends (auth, workspace access)
    ├── intelligence/                # AI Brain
    │   ├── ai_client.py             # Claude/OpenAI/Azure abstraction
    │   ├── semantic_extractor.py    # DOM → compressed semantic state (NO raw HTML to LLM)
    │   ├── scenario_planner.py      # Natural language → execution plan
    │   └── failure_analyzer.py      # Technical errors → business explanations + RCA
    ├── execution/                   # Selenium + CDP Hands
    │   ├── browser_manager.py       # Chrome + CDP setup, DOM snapshots, network
    │   ├── plan_runner.py           # Deterministic step execution
    │   ├── self_healing.py          # Ranked healing strategies (semantic → label → text)
    │   └── executor.py              # Full run orchestration (login → execute → report)
    ├── explore/
    │   └── explore_engine.py        # Application learning: login → modules → pages → knowledge
    ├── memory/
    │   └── chroma_store.py          # ChromaDB vector memory (modules, workflows, selectors)
    ├── jobs/
    │   ├── execution_job.py         # Enqueue + run executions (asyncio tasks)
    │   └── learning_job.py          # Post-run memory improvement
    └── realtime/
        ├── manager.py               # WebSocket connection manager + broadcast
        └── websocket.py             # WS endpoint, subscribe protocol
```

## Database Models (SQLAlchemy)

| Entity | Purpose |
|--------|---------|
| User, Workspace, WorkspaceMember | Identity and multi-tenancy |
| Application, Environment, Credential | Application configuration (credentials encrypted) |
| ExploreSession, ExploreLog, HumanDecision | Exploration lifecycle + human-in-loop |
| KnowledgeGraph, ApplicationModule, ApplicationPage | Semantic application knowledge |
| SemanticElement, ApplicationWorkflow | Element + workflow understanding |
| WorkspacePreference | Persisted human decisions (e.g., login location) |
| Scenario, ExecutionPlan | Business test cases + AI-generated plans |
| ExecutionRun, ExecutionStep, ExecutionLog | Execution tracking |
| ExecutionReport | AI-native report with RCA |
| AIMemoryChunk, SelectorMemory | Learning and memory |

## Core Design Rules

1. **AI plans once — Selenium executes deterministically**
2. **Never send raw HTML to LLM** — use compressed semantic UI state
3. **Explore = Learning, not Testing** — ExploreEngine builds knowledge, never runs assertions
4. **Semantic healing first** — aria-label → label[for] → placeholder → text → role → fallback
5. **Failures explained in business terms** — no `NoSuchElementException` in reports
6. **Human-in-loop for ambiguous decisions** — saves as workspace preferences
7. **Memory improves over time** — ChromaDB + Postgres learning after every run

## Execution Modes

| Mode | Max Steps | Depth |
|------|-----------|-------|
| smoke | 8 | minimal |
| functional | 20 | standard |
| validation_heavy | 40 | thorough |
| regression | 60 | comprehensive |
| workflow_heavy | 80 | exhaustive |

## Running Locally

```bash
# 1. Start infrastructure
docker compose up -d

# 2. Backend
cd backend
pip install -r requirements.txt
cp .env.example .env   # Fill in API keys
uvicorn main:app --reload --port 8000

# 3. Frontend
npm install
npm run dev   # Runs on port 3000
```

## Core workflow

```
Workspace → Discovery → Scenarios → Expansion → Execution Plan (JSON)
    → Playwright Execution → Recovery → Learning → Reporting
```

## Code organization

The repository is split between the frontend and backend.

- `backend/` contains the FastAPI backend service, REST API routes, AI integrations, Selenium execution engine, memory store, and database schema definitions.
- `src/` contains the Next.js frontend application with pages, components, hooks, and UI utilities.
- `docker-compose.yml` provides local PostgreSQL, Redis, and ChromaDB.

Backend API routes are defined under `backend/app/api/v1/`. Database models use SQLAlchemy and Pydantic.

## Execution modes

`smoke` | `functional` | `validation_heavy` | `regression` | `workflow_heavy`

(`deep_validation` aliases to `workflow_heavy`.)

## Structured plan actions

`navigate` | `click` | `fill` | `natural_language` | `assert_visible` | `wait_for_network` | `wait_ms`

These are implemented in the backend execution planner and action runners.

## Data model

The backend uses SQLAlchemy models and Pydantic schemas to represent the data model.

- `Workspace`, `Application`, `Scenario`, `ExecutionRun`, `ExecutionStep`, `ExecutionLog`, `ExecutionReport`
- `ExploreSession`, `ExploreLog`, `HumanDecision`
- `AIMemoryChunk`, `SelectorMemory`, `ApplicationWorkflow`

## Frontend/App

- Next.js App Router pages for login, workspaces, dashboards, executions, explore sessions, and settings.
- The frontend consumes backend REST APIs and connects to the FastAPI WebSocket endpoint for realtime updates.

## Local infrastructure

```bash
docker compose up -d   # Postgres, Redis, ChromaDB
npm run dev            # Frontend + backend in development
```
