# QAptain

AI-native QA automation platform. Explores your web app, generates test scenarios, and executes them via Playwright with self-healing selectors.

## Project Structure

```
QAptain-QA/
├── frontend/          # Next.js 15 (React 19, TypeScript, Tailwind)
├── backend/           # FastAPI (Python 3.11, Playwright, Selenium)
├── docker-compose.yml          # Local dev infra (Postgres + Redis)
└── docker-compose.prod.yml     # Full production stack
```

---

## Local Development

### Prerequisites
- Node.js 20+
- Python 3.11
- Docker (for Postgres + Redis)

### 1. Start infra

```bash
docker compose up -d
```

### 2. Backend

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

cp .env.example .env   # fill in your values
alembic upgrade head
uvicorn main:app --reload --port 8000
```

### 3. Frontend

```bash
cd frontend
npm ci --legacy-peer-deps

cp .env.example .env   # fill in your values
npm run dev            # starts on http://localhost:3000
```

---

## Production Deployment

### Recommended stack

| Component | Service |
|-----------|---------|
| Frontend | **Vercel** (zero-config Next.js) |
| Backend | **Railway** (Docker, persistent processes) |
| Database | **Neon PostgreSQL** (serverless, free tier) |
| Redis | **Upstash Redis** (serverless, free tier) |

---

### Deploy the backend to Railway

1. [railway.app](https://railway.app) → New Project → Deploy from GitHub
2. Set **Root Directory** to `backend`
3. Railway will use `backend/Dockerfile` and `backend/railway.toml` automatically
4. Add environment variables (copy from `backend/.env.example`):

| Variable | Value |
|----------|-------|
| `DATABASE_URL` | `postgresql+asyncpg://...` from Neon |
| `REDIS_URL` | `rediss://...` from Upstash |
| `LLM_PROVIDER` | `azure` |
| `AZURE_OPENAI_API_KEY` | your key |
| `AZURE_OPENAI_ENDPOINT` | your endpoint |
| `AZURE_OPENAI_DEPLOYMENT` | `gpt-5-mini` |
| `SECRET_KEY` | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `ENCRYPTION_KEY` | `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `ENVIRONMENT` | `production` |
| `CORS_ORIGINS` | `["https://your-app.vercel.app"]` |
| `SELENIUM_HEADLESS` | `true` |

5. Note the Railway URL: `https://qaptain-api.up.railway.app`

---

### Deploy the frontend to Vercel

1. [vercel.com](https://vercel.com) → New Project → Import repo
2. Set **Root Directory** to `frontend`
3. Framework: **Next.js** (auto-detected)
4. Add environment variables:

| Variable | Value |
|----------|-------|
| `NEXT_PUBLIC_API_URL` | `https://qaptain-api.up.railway.app/api/v1` |
| `NEXT_PUBLIC_WS_URL` | `wss://qaptain-api.up.railway.app/ws` |

5. Deploy.

---

### Run database migrations (once, before first deploy)

```bash
cd backend
export DATABASE_URL="postgresql+asyncpg://..."   # your Neon URL
source .venv/bin/activate
alembic upgrade head
```

---

### Self-hosted (full Docker)

```bash
# Fill in real values first
cp backend/.env.example backend/.env
cp frontend/.env.example frontend/.env

# Build and start everything
docker compose -f docker-compose.prod.yml up --build -d
```

Access at `http://localhost:3000`.
