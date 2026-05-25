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

## Ten engines (code map)

| Engine | Responsibility | Location |
|--------|----------------|----------|
| **Workspace** | Workspaces, envs, auth profiles, access | `src/app/api/v1/workspaces/*`, `src/lib/workspace-access.ts` |
| **Discovery** | Light scan: modules, routes, fields, APIs, page meta | `src/server/jobs/discovery-job.ts`, `src/server/intelligence/*` |
| **Scenario intelligence** | NLP expansion, module mapping, test types | `src/server/orchestration/scenario-expand-graph.ts`, `src/server/jobs/scenario-expand-job.ts` |
| **Field intelligence** | Types, validations, semantics, priority | `src/server/intelligence/field-classifier.ts`, `persist-field-intelligence.ts` |
| **Data generation** | Faker + profiles (positive/negative/BVA/security) | `src/server/data/smart-data-generator.ts` |
| **Execution planning** | Sanitize AI output → JSON plan only | `src/server/execution/plan-builder.ts` |
| **Execution** | Playwright, waits, asserts, API capture | `src/server/execution/run-execution.ts`, `stability.ts` |
| **Recovery** | Selector memory, ranked fallbacks | `src/server/execution/recovery.ts` |
| **AI memory** | Chunks, module embeddings (Supabase), graphs | `src/server/memory/*`, `AiMemoryChunk`, `ApplicationIntelGraph` |
| **Reporting** | Runs, steps, logs, timelines, RCA | `ExecutionReport`, `src/server/intelligence/rca-engine.ts` |

## Four runners (BullMQ)

| Runner | Queue | Processor |
|--------|-------|-----------|
| Discovery | `qaptain-discovery` | `processDiscoveryJob` |
| Scenario expansion | `qaptain-scenario-expand` | `processScenarioExpandJob` |
| Execution | `qaptain-execution` | `runExecutionJob` |
| Learning | `qaptain-learning` | `processLearningJob` |

Without `REDIS_URL`, jobs run **inline** in the API process (dev fallback).

## Execution modes

`smoke` | `functional` | `validation_heavy` | `regression` | `workflow_heavy`

(`deep_validation` aliases to `workflow_heavy`.)

Caps: `src/lib/execution-modes.ts`.

## Structured plan actions (only)

`navigate` | `click` | `fill` | `natural_language` | `assert_visible` | `wait_for_network` | `wait_ms`

Defined in `src/server/execution/plan-builder.ts`.

## Data model (Prisma)

- `Workspace`, `Environment`, `AuthProfile`
- `ApplicationModule`, `ApplicationRoute`, `DiscoveryRun`
- `Scenario`, `ExecutionPlan`, `ExecutionRun`, `ExecutionStep`, `ExecutionLog`, `ExecutionReport`
- `FieldDefinition`, `ValidationRule`, `SelectorMemory`
- `AiMemoryChunk`, `ScenarioModuleMapping`
- `ApplicationIntelGraph`, `WorkflowIntel`, `ApiEndpointIntel`

## Frontend (App Router)

- Dashboard, workspaces, discovery, modules, fields, scenarios, runs, reports, intel tab
- Live logs: Socket.IO (`server.ts` + `src/server/events/*`)

## Local infrastructure

```bash
docker compose up -d   # Postgres, Redis, Chroma (optional; memory uses Supabase if configured)
npm run dev            # Web + Socket.IO :3000
npm run worker         # BullMQ (requires REDIS_URL)
```
