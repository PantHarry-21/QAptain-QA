<![CDATA[# 🧭 QAPtain

**AI-native quality engineering platform** — progressive discovery, scenario intelligence, structured Playwright execution, and workspace-scoped memory.

QAPtain automatically discovers your web application's modules, generates intelligent test scenarios, and executes them via Playwright with self-healing selectors, AI-powered form filling, and detailed execution reports — all within a collaborative workspace model.

---

## ✨ Key Features

| Feature | Description |
| --- | --- |
| **Progressive Discovery** | Crawls your application to map modules, routes, forms, fields, and API endpoints automatically |
| **Scenario Intelligence** | AI-generated test scenarios with support for manual entry, Excel import, and natural-language expansion |
| **Playwright Execution** | Structured test execution with multiple modes — smoke, functional, validation-heavy, regression, deep validation |
| **Self-Healing Selectors** | Selector memory with confidence scoring and automatic healing when elements change |
| **AI Form Filling** | Context-aware fake data generation for form fields based on semantic classification |
| **Field Validation Inference** | Automatically detects validation rules from HTML, API responses, and observed behavior |
| **Workspace Collaboration** | Multi-workspace, multi-member model with owner/admin/member roles |
| **Real-time Execution Logs** | Live test progress via FastAPI WebSocket or polling with step-by-step screenshots and video recording |
| **PDF Reports** | Auto-generated executive test reports with risk assessment and recommendations |
| **Background Job Queue** | In-process async task handling with optional Redis coordination |
| **Vector Memory** | ChromaDB-backed vector storage for AI memory chunks (modules, workflows, selectors) |

---

## 🏗️ Tech Stack

| Layer | Technology |
| --- | --- |
| **Frontend** | Next.js 15 + React 19 + TypeScript + Tailwind CSS |
| **Backend** | FastAPI + Python 3 + async SQLAlchemy |
| **Styling** | Tailwind CSS 4, Radix UI primitives |
| **Database** | PostgreSQL |
| **ORM** | SQLAlchemy async |
| **Authentication** | FastAPI auth with JWT and credential management |
| **AI / LLM** | Anthropic / OpenAI / Azure OpenAI |
| **Test Execution** | Selenium + Chrome DevTools Protocol |
| **Job Handling** | In-process async jobs with optional Redis coordination |
| **Vector Store** | ChromaDB |
| **Real-time** | FastAPI WebSocket |
| **PDF Generation** | jsPDF + jspdf-autotable |
| **State Management** | TanStack React Query |
| **Charts** | Recharts |
| **Animations** | Framer Motion |

---

## 📁 Project Structure

```
QAptain/
├── backend/                   # FastAPI backend service
│   ├── main.py                # FastAPI app and WebSocket entrypoint
│   ├── config.py              # Pydantic settings
│   ├── requirements.txt       # Python dependencies
│   └── app/                   # Backend application modules
├── src/                       # Next.js frontend application
├── public/                    # Static assets
├── docker-compose.yml         # Local Postgres / Redis / ChromaDB stack
├── README.md
├── ARCHITECTURE.md
├── package.json
├── tsconfig.json
└── .env.example
```

---

## 🚀 Getting Started

### Prerequisites

- **Node.js** ≥ 18
- **npm** (comes with Node.js)
- **Docker & Docker Compose** (for local PostgreSQL + Redis)
- **Git**

### 1. Clone the Repository

```bash
git clone https://github.com/your-org/QAptain.git
cd QAptain
```

### 2. Install Dependencies

Frontend dependencies:
```bash
npm install
```

Backend dependencies:
```bash
cd backend
python -m pip install -r requirements.txt
```

> This repository uses a separate FastAPI backend and a Next.js frontend.

### 3. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and fill in the required values:

| Variable | Required | Description |
| --- | --- | --- |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `AI_PROVIDER` | ✅ | `anthropic`, `openai`, or `azure_openai` |
| `ANTHROPIC_API_KEY` | Optional | Required when `AI_PROVIDER=anthropic` |
| `OPENAI_API_KEY` | Optional | Required when `AI_PROVIDER=openai` |
| `AZURE_OPENAI_API_KEY` | Optional | Required when `AI_PROVIDER=azure_openai` |
| `AZURE_OPENAI_ENDPOINT` | Optional | Required when `AI_PROVIDER=azure_openai` |
| `AZURE_OPENAI_DEPLOYMENT` | Optional | Azure deployment/model name |
| `REDIS_URL` | Optional | Redis URL for optional async coordination |
| `CHROMA_HOST` | Optional | ChromaDB host |
| `CHROMA_PORT` | Optional | ChromaDB port |
| `SECRET_KEY` | ✅ | JWT and auth secret |
| `ENCRYPTION_KEY` | Optional | Encryption key for stored credentials |

### 4. Start Local Infrastructure (PostgreSQL + Redis + ChromaDB)

```bash
docker compose up -d
```

This starts:
- **PostgreSQL 16** on port `5432` (user: `qaptain`, password: `qaptain`, db: `qaptain`)
- **Redis 7** on port `6379`
- **ChromaDB** on port `8001`

### 5. Start the Backend

In a new terminal:

```bash
cd backend
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### 6. Start the Frontend

In another terminal:

```bash
npm run dev:fe
```

### 7. Start frontend and backend together

```bash
npm run dev
```

### Production Build

```bash
npm run build
npm start
```

---

## 📋 All Available Commands

| Command | Description |
| --- | --- |
| `npm run dev` | Start the frontend and backend together in development |
| `npm run dev:fe` | Start only the frontend development server |
| `npm run dev:be` | Start only the backend FastAPI service |
| `npm run build` | Build the Next.js frontend for production |
| `npm start` | Start the production frontend server |
| `npm run lint` | Run ESLint |
| `python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000` | Start the backend directly from `backend/` |
| `docker compose up -d` | Start local PostgreSQL, Redis, and ChromaDB containers |
| `docker compose down` | Stop local infrastructure containers |
| `docker compose down -v` | Stop containers and remove volumes (⚠️ deletes data) |

---

## 🔌 Backend API

Backend routes are defined under `backend/app/api/v1/`. The frontend communicates with the FastAPI service through REST and WebSocket endpoints.
| `/api/history` | Execution history |
| `/api/saved-scenarios` | Saved scenario CRUD |
| `/api/import-excel` | Excel scenario import |
| `/api/generate-pdf` | PDF report generation |
| `/api/videos` | Test execution video recordings |
| `/api/health` | Health check |
| `/api/v1/` | Versioned API namespace |

---

## 🗄️ Database

QAPtain uses a **workspace-centric data model** with PostgreSQL. Key entities include:

- **Users & Workspaces** — Multi-tenant isolation with role-based access (Owner, Admin, Member)
- **Environments** — Multiple target URLs per workspace (staging, production, etc.)
- **Auth Profiles** — Encrypted credential storage for authenticated testing
- **Discovery Runs** — Application crawl sessions that map modules and routes
- **Application Modules & Routes** — Discovered application structure
- **Scenarios & Execution Plans** — Test scenarios with versioned execution plans
- **Execution Runs, Steps & Logs** — Full test execution history with step-level detail
- **Field Definitions & Validation Rules** — Inferred form field metadata
- **Selector Memory** — Self-healing selector strategies with confidence scoring
- **AI Memory Chunks** — Vector-stored context for intelligent test generation
- **Application Intel Graphs** — Navigation and workflow intelligence

---

## 🧪 Execution Modes

| Mode | Description |
| --- | --- |
| `smoke` | Quick surface-level checks |
| `functional` | Standard CRUD workflow validation (default) |
| `validation_heavy` | Focused on form validation and edge cases |
| `regression` | Full regression across known scenarios |
| `deep_validation` | Exhaustive field-level validation with boundary testing |

---

## 🛡️ Environment Notes

- **Local development**: Use `docker compose up -d` for PostgreSQL + Redis
- **Hosted databases**: Neon (Postgres) + Upstash (Redis) are supported out of the box
- **Vector memory**: Supabase replaces the legacy ChromaDB integration
- **AI provider**: Configure either Azure OpenAI or OpenAI via the `LLM_PROVIDER` env var

---

## 📄 License

Private — All rights reserved.
]]>
