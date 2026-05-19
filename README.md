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
| **Real-time Execution Logs** | Live test progress via Socket.IO with step-by-step screenshots and video recording |
| **PDF Reports** | Auto-generated executive test reports with risk assessment and recommendations |
| **Background Job Queue** | BullMQ-powered async processing for discovery, execution, and scenario expansion |
| **Vector Memory** | Supabase-backed vector storage for AI memory chunks (module, workflow, selector, field context) |

---

## 🏗️ Tech Stack

| Layer | Technology |
| --- | --- |
| **Framework** | [Next.js 15](https://nextjs.org/) (App Router, React 19) |
| **Language** | TypeScript |
| **Styling** | Tailwind CSS 4, shadcn/ui (Radix primitives) |
| **Database** | PostgreSQL (Neon / local Docker) |
| **ORM** | Prisma 5 |
| **Authentication** | NextAuth.js (credentials provider) |
| **AI / LLM** | Azure OpenAI / OpenAI (GPT-5-mini), LangChain |
| **Test Execution** | Playwright |
| **Job Queue** | BullMQ + Redis (Upstash / local Docker) |
| **Vector Store** | Supabase (replaces ChromaDB) |
| **Real-time** | Socket.IO |
| **PDF Generation** | jsPDF + jspdf-autotable |
| **State Management** | Zustand, TanStack React Query |
| **Charts** | Recharts |
| **Animations** | Framer Motion |

---

## 📁 Project Structure

```
QAptain/
├── prisma/
│   └── schema.prisma          # Database schema (workspace-centric model)
├── scripts/
│   └── download-chromium.mjs  # Chromium binary downloader for Playwright
├── src/
│   ├── app/                   # Next.js App Router pages
│   │   ├── (platform)/        # Authenticated pages (dashboard, workspaces, settings)
│   │   ├── api/               # API routes (19 endpoint groups)
│   │   ├── login/             # Login page
│   │   ├── signup/            # Signup page
│   │   ├── scenarios/         # Scenario management
│   │   ├── test-execution/    # Test execution UI
│   │   ├── results/           # Test results viewer
│   │   ├── history/           # Execution history
│   │   └── url-input/         # URL input for discovery
│   ├── components/            # React components
│   │   ├── ui/                # shadcn/ui primitives
│   │   └── platform/          # Platform-specific components
│   ├── hooks/                 # Custom React hooks
│   ├── lib/                   # Shared utilities & services
│   │   ├── auth.ts            # NextAuth configuration
│   │   ├── openai.ts          # LLM client setup
│   │   ├── prompts.ts         # AI prompt templates
│   │   ├── test-executor.ts   # Core Playwright execution engine
│   │   ├── prisma.ts          # Prisma client singleton
│   │   ├── socket.ts          # Socket.IO event handlers
│   │   ├── supabase.ts        # Supabase client
│   │   └── pdf-generator.ts   # Report PDF generation
│   └── server/                # Server-side modules
│       ├── data/              # Data access layer
│       ├── events/            # Socket.IO event bridge
│       ├── execution/         # Test run execution engine
│       ├── intelligence/      # App intelligence (field classification, graph building, workflow inference)
│       ├── jobs/              # Background job processors (discovery, scenario expansion)
│       ├── memory/            # Vector memory (Supabase)
│       ├── orchestration/     # Execution orchestration
│       └── queues/            # BullMQ queue definitions
├── docker-compose.yml         # Local PostgreSQL + Redis
├── server.ts                  # Custom Next.js + Socket.IO server
├── worker.ts                  # BullMQ worker process
├── schema.sql                 # Legacy SQL schema (reference)
├── supabase-setup.sql         # Supabase vector store setup
└── package.json
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

```bash
npm install
```

> This automatically downloads a Chromium binary for Playwright and generates the Prisma client (`postinstall` hook).

### 3. Configure Environment Variables

```bash
cp .env.example .env
```

Edit `.env` and fill in the required values:

| Variable | Required | Description |
| --- | --- | --- |
| `DATABASE_URL` | ✅ | PostgreSQL connection string |
| `NEXTAUTH_SECRET` | ✅ | Random secret for session encryption |
| `NEXTAUTH_URL` | ✅ | App URL (default: `http://localhost:3000`) |
| `REDIS_URL` | Recommended | Redis connection string (BullMQ workers) |
| `NEXT_PUBLIC_SUPABASE_URL` | Optional | Supabase project URL (vector memory) |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Optional | Supabase anon/public key |
| `LLM_PROVIDER` | ✅ | `azure` or `openai` |
| `AZURE_OPENAI_API_KEY` | If Azure | Azure OpenAI API key |
| `AZURE_OPENAI_ENDPOINT` | If Azure | Azure OpenAI endpoint URL |
| `AZURE_OPENAI_DEPLOYMENT` | If Azure | Deployment/model name |

### 4. Start Local Infrastructure (PostgreSQL + Redis)

```bash
docker compose up -d
```

This starts:
- **PostgreSQL 16** on port `5432` (user: `qaptain`, password: `qaptain`, db: `qaptain`)
- **Redis 7** on port `6379`

### 5. Push Database Schema

```bash
npx prisma db push
```

### 6. Generate Prisma Client (if not already done)

```bash
npx prisma generate
```

---

## 🖥️ Running the Application

### Development Server (Web App)

```bash
npm run dev
```

This starts the custom server (Next.js + Socket.IO) at **http://localhost:3000**.

### Background Worker (Job Queue)

Open a **second terminal** and run:

```bash
npm run worker
```

This starts BullMQ workers that process:
- **Discovery jobs** — crawl and map your application
- **Execution jobs** — run Playwright test scenarios
- **Scenario expansion jobs** — AI-powered scenario generation

### Production Build

```bash
npm run build
npm start
```

---

## 📋 All Available Commands

| Command | Description |
| --- | --- |
| `npm run dev` | Start the development server (Next.js + Socket.IO on port 3000) |
| `npm run build` | Generate Prisma client and build the Next.js production bundle |
| `npm start` | Start the production server |
| `npm run worker` | Start BullMQ background workers (discovery, execution, scenario-expand) |
| `npm run lint` | Run ESLint |
| `npm run db:push` | Push Prisma schema changes to the database |
| `npm run db:generate` | Regenerate the Prisma client |
| `docker compose up -d` | Start local PostgreSQL + Redis containers |
| `docker compose down` | Stop local infrastructure containers |
| `docker compose down -v` | Stop containers and remove volumes (⚠️ deletes data) |

---

## 🔌 API Endpoints

The application exposes the following API route groups under `/api/`:

| Endpoint | Purpose |
| --- | --- |
| `/api/auth` | NextAuth.js authentication |
| `/api/analyze-url` | URL analysis and page inspection |
| `/api/generate-scenarios` | AI-powered scenario generation |
| `/api/interpret-scenario` | Natural-language scenario interpretation |
| `/api/translate-scenarios` | Scenario format translation |
| `/api/ai-generate-steps` | AI step generation for scenarios |
| `/api/ai-fill-form` | AI-powered form data generation |
| `/api/ai-test-form-validations` | Form validation test generation |
| `/api/execute-workflow` | Workflow execution trigger |
| `/api/run-test` | Test execution trigger |
| `/api/results` | Test results retrieval |
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
