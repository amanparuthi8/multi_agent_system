"""
api/main.py
FastAPI application — production-grade API layer wrapping the ADK multi-agent system.
Endpoints follow RESTful conventions with ADK agent invocation for /query.
"""
from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

import google.cloud.logging
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api.routers import events, notes, tasks, workflows, query
from tools.mcp_tools import health_check

# ── Cloud Logging setup (Lab 1 pattern) ──────────────────────────────────────
if os.getenv("GOOGLE_CLOUD_PROJECT"):
    try:
        google.cloud.logging.Client().setup_logging()
    except Exception:
        pass  # fall back to stdlib logging outside GCP

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan: startup / shutdown ──────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Multi-Agent System API...")

    # Verify MCP Toolbox is reachable
    if not health_check():
        logger.warning(
            "MCP Toolbox unreachable at %s — tool calls will fail. "
            "Start it with: ./toolbox --tools-file=mcp_toolbox/tools.yaml",
            os.getenv("MCP_TOOLBOX_URL", "http://127.0.0.1:5000"),
        )
    else:
        logger.info("MCP Toolbox is healthy ✅")

    yield
    logger.info("Shutting down Multi-Agent System API")


# ── App factory ───────────────────────────────────────────────────────────────
def create_app() -> FastAPI:
    app = FastAPI(
        title="Multi-Agent AI System",
        description=(
            "Production-ready multi-agent AI system built with Google ADK, "
            "AlloyDB, MCP Toolbox, and Gemini 2.5 Flash. "
            "Manages tasks, schedules, and knowledge via coordinated AI agents."
        ),
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS — restrict in production via env var
    origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Request ID + timing middleware ────────────────────────────────────────
    @app.middleware("http")
    async def request_middleware(request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()

        response: Response = await call_next(request)

        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers["X-Request-ID"]    = request_id
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
        logger.info(
            "%s %s → %d (%.1fms) [%s]",
            request.method, request.url.path,
            response.status_code, elapsed_ms, request_id,
        )
        return response

    # ── Global error handler ──────────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(
            "Unhandled exception for %s %s: %s",
            request.method, request.url.path, exc, exc_info=True,
        )
        return JSONResponse(
            status_code=500,
            content={
                "error": "internal_server_error",
                "message": str(exc),
                "request_id": getattr(request.state, "request_id", None),
            },
        )

    # ── Health / readiness endpoints ──────────────────────────────────────────
    @app.get("/health", tags=["System"])
    async def health():
        return {
            "status":  "ok",
            "version": "1.0.0",
            "model":   os.getenv("MODEL", "gemini-2.5-flash"),
            "mcp_toolbox": "healthy" if health_check() else "unreachable",
        }

    @app.get("/", tags=["System"])
    async def root():
        return {
            "service": "Multi-Agent AI System",
            "docs":    "/docs",
            "health":  "/health",
        }

    # ── Mount routers ─────────────────────────────────────────────────────────
    app.include_router(query.router,     prefix="/api/v1",          tags=["Agent Query"])
    app.include_router(tasks.router,     prefix="/api/v1/tasks",    tags=["Tasks"])
    app.include_router(events.router,    prefix="/api/v1/events",   tags=["Events"])
    app.include_router(notes.router,     prefix="/api/v1/notes",    tags=["Notes"])
    app.include_router(workflows.router, prefix="/api/v1/workflows", tags=["Workflows"])

    return app


app = create_app()
