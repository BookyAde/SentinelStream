"""
SentinelStream Redis Client
Supports both REDIS_URL (Railway) and REDIS_HOST/PORT (local Docker).
"""

import os
from typing import Optional
import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_redis: Optional[aioredis.Redis] = None


async def init_redis() -> None:
    global _redis

    # Railway provides a full REDIS_URL — use it directly if present
    redis_url = os.environ.get("REDIS_URL") or os.environ.get("REDIS_PRIVATE_URL")

    if not redis_url:
        # Fall back to host/port for local Docker
        redis_url = settings.REDIS_URL

    _redis = aioredis.from_url(
        redis_url,
        encoding="utf-8",
        decode_responses=True,
        max_connections=20,
    )
    await _redis.ping()
    logger.info("Redis connection established", extra={"url": redis_url.split("@")[-1]})


async def close_redis() -> None:
    global _redis
    if _redis:
        await _redis.aclose()
        logger.info("Redis connection closed")


def get_redis() -> aioredis.Redis:
    if _redis is None:
        raise RuntimeError("Redis not initialised — call init_redis() first")
    return _redis


# ── Queue helpers ─────────────────────────────────────────────────────────────

async def enqueue_event(payload: str) -> int:
    r = get_redis()
    return await r.rpush(settings.EVENT_QUEUE_NAME, payload)


async def dequeue_events(count: int = 50) -> list[str]:
    r = get_redis()
    pipe = r.pipeline()
    for _ in range(count):
        pipe.lpop(settings.EVENT_QUEUE_NAME)
    results = await pipe.execute()
    return [item for item in results if item is not None]


async def enqueue_dlq(payload: str) -> int:
    r = get_redis()
    return await r.rpush(settings.DLQ_NAME, payload)


async def get_dlq_events(start: int = 0, end: int = -1) -> list[str]:
    r = get_redis()
    return await r.lrange(settings.DLQ_NAME, start, end)


async def remove_from_dlq(payload: str, count: int = 1) -> int:
    r = get_redis()
    return await r.lrem(settings.DLQ_NAME, count, payload)


async def queue_lengths() -> dict[str, int]:
    r = get_redis()
    main_len = await r.llen(settings.EVENT_QUEUE_NAME)
    dlq_len = await r.llen(settings.DLQ_NAME)
    return {"main_queue": main_len, "dlq": dlq_len}