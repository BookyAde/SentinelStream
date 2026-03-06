"""SentinelStream Health Router"""
import time
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db.postgres import get_db
from app.db.redis_client import queue_lengths

router = APIRouter()
_start = time.monotonic()


@router.get("")
async def health(db: AsyncSession = Depends(get_db)):
    """Liveness + readiness probe used by k8s / load balancers."""
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    try:
        lengths = await queue_lengths()
        redis_ok = True
    except Exception:
        redis_ok = False
        lengths = {}

    overall = "healthy" if (db_ok and redis_ok) else "degraded"
    return {
        "status": overall,
        "uptime_seconds": round(time.monotonic() - _start, 1),
        "postgres": "ok" if db_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "queue_depths": lengths,
    }
