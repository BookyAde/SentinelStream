"""
SentinelStream - Event Processing Pipeline
FastAPI Application Entry Point
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app.api.routes import events, health, metrics, replay
from app.core.config import settings
from app.core.logging import setup_logging
from app.db.postgres import init_db
from app.db.redis_client import init_redis, close_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown lifecycle."""
    setup_logging()
    await init_db()
    await init_redis()
    yield
    await close_redis()


app = FastAPI(
    title="SentinelStream API",
    description="High-throughput event processing pipeline with dead-letter queue and replay",
    version="1.0.0",
    lifespan=lifespan,
)

# Middleware
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # Allow all origins
    allow_credentials=False,  # MUST be False when allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(health.router,   prefix="/health",          tags=["Health"])
app.include_router(events.router,   prefix="/api/v1/events",   tags=["Events"])
app.include_router(metrics.router,  prefix="/api/v1/metrics",  tags=["Metrics"])
app.include_router(replay.router,   prefix="/api/v1/replay",   tags=["Replay"])