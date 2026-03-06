"""
SentinelStream Metrics API
GET /api/v1/metrics          – pipeline processing stats
GET /health                  – liveness + readiness probe
"""

import time
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.db.redis_client import queue_lengths, get_redis
from app.models.event import Event, EventStatus
from app.schemas.events import ProcessingMetrics, PipelineHealth, QueueMetrics

router = APIRouter()
_start_time = time.monotonic()


@router.get("", response_model=ProcessingMetrics)
async def get_metrics(db: AsyncSession = Depends(get_db)):
    """Return processing statistics for the pipeline."""
    r = get_redis()
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    total = (await db.execute(select(func.count()).select_from(Event))).scalar_one()

    processed_hour = (
        await db.execute(
            select(func.count()).select_from(Event).where(
                Event.status == EventStatus.PROCESSED,
                Event.processed_at >= one_hour_ago,
            )
        )
    ).scalar_one()

    failed_hour = (
        await db.execute(
            select(func.count()).select_from(Event).where(
                Event.status == EventStatus.FAILED,
                Event.updated_at >= one_hour_ago,
            )
        )
    ).scalar_one()

    throughput = processed_hour / 3600.0

    return ProcessingMetrics(
        total_events=total,
        processed_last_hour=processed_hour,
        failed_last_hour=failed_hour,
        avg_processing_ms=0.0,   # wire up Prometheus/StatsD for real histograms
        p99_processing_ms=0.0,
        throughput_per_second=round(throughput, 4),
    )


@router.get("/queue", response_model=QueueMetrics)
async def get_queue_metrics():
    """Current queue depths."""
    lengths = await queue_lengths()
    return QueueMetrics(
        main_queue_depth=lengths["main_queue"],
        dlq_depth=lengths["dlq"],
        timestamp=datetime.now(timezone.utc),
    )
