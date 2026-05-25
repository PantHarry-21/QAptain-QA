import asyncio
import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import settings
from app.api.v1 import (
    auth,
    workspaces,
    applications,
    scenarios,
    executions,
    explore,
    knowledge,
    reports,
    health,
)
from app.db.session import engine, Base
from app.realtime.manager import connection_manager

logging.basicConfig(level=logging.INFO)
log = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("QAptain starting", version=settings.APP_VERSION, env=settings.ENVIRONMENT)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    import os
    os.makedirs(settings.SCREENSHOTS_DIR, exist_ok=True)
    os.makedirs(settings.VIDEOS_DIR, exist_ok=True)
    # Give execution worker threads a reference to the main event loop
    # so they can post WebSocket broadcasts back to it.
    from app.jobs.execution_job import set_main_loop
    set_main_loop(asyncio.get_running_loop())
    log.info("QAptain ready")
    yield
    log.info("QAptain shutting down")


app = FastAPI(
    title="QAptain API",
    description="AI-native enterprise workflow intelligence platform",
    version=settings.APP_VERSION,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# REST API routers
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(workspaces.router, prefix="/api/v1/workspaces", tags=["workspaces"])
app.include_router(applications.router, prefix="/api/v1/applications", tags=["applications"])
app.include_router(scenarios.router, prefix="/api/v1/scenarios", tags=["scenarios"])
app.include_router(executions.router, prefix="/api/v1/executions", tags=["executions"])
app.include_router(explore.router, prefix="/api/v1/explore", tags=["explore"])
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["knowledge"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["reports"])

# WebSocket endpoint
from app.realtime.websocket import websocket_endpoint
from fastapi import WebSocket

@app.websocket("/ws/{client_id}")
async def websocket_route(websocket: WebSocket, client_id: str):
    await websocket_endpoint(websocket, client_id)

# Static file serving for artifacts
import os
if os.path.exists(settings.ARTIFACTS_DIR):
    app.mount("/artifacts", StaticFiles(directory=settings.ARTIFACTS_DIR), name="artifacts")
