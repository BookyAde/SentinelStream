"""
SentinelStream Redis Client
Connection pool and helpers for event queue, DLQ, and metrics counters.
"""

from typing import Optional
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis: Optional[aioredis.Redis] = None


async def init_redis() -> None:
    global _redis
    _redis = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )
    await _redis.ping()
    logger.info("Redis connection established", extra={"url": settings.REDIS_URL})


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        logger.info("Redis connection closed")


def get_redis() -> aioredis.Redis:
    """FastAPI dependency / direct accessor for the Redis client."""
    if _redis is None:
        raise RuntimeError("Redis not initialised — call init_redis() first")
    return _redis


# ── Queue helpers ──────────────────────────────────────────────────────────────

async def enqueue_event(payload: str) -> int:
    """Push a serialised event onto the main queue. Returns queue length."""
    r = get_redis()
    return await r.rpush(settings.EVENT_QUEUE_NAME, payload)


async def dequeue_events(count: int = 50) -> list[str]:
    """Pop up to *count* events from the main queue (non-blocking)."""
    r = get_redis()
    pipe = r.pipeline()
    for _ in range(count):
        pipe.lpop(settings.EVENT_QUEUE_NAME)
    results = await pipe.execute()
    return [item for item in results if item is not None]


async def enqueue_dlq(payload: str) -> int:
    """Push a failed event onto the Dead Letter Queue."""
    r = get_redis()
    return await r.rpush(settings.DLQ_NAME, payload)


async def get_dlq_events(start: int = 0, end: int = -1) -> list[str]:
    """Read DLQ events without removing them (LRANGE)."""
    r = get_redis()
    return await r.lrange(settings.DLQ_NAME, start, end)


async def remove_from_dlq(payload: str, count: int = 1) -> int:
    """Remove a specific event from the DLQ after successful replay."""
    r = get_redis()
    return await r.lrem(settings.DLQ_NAME, count, payload)


async def queue_lengths() -> dict[str, int]:
    """Return current lengths of main queue and DLQ."""
    r = get_redis()
    main_len = await r.llen(settings.EVENT_QUEUE_NAME)
    dlq_len = await r.llen(settings.DLQ_NAME)
    return {"main_queue": main_len, "dlq": dlq_len}
