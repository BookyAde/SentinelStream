"""
SentinelStream Processing Worker
Drains the Redis event queue, calls the processor, persists results,
and routes failures to the Dead Letter Queue with exponential back-off.
"""

import asyncio
import json
import signal
import uuid
from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.db.postgres import init_db
from app.db.redis_client import init_redis, dequeue_events, enqueue_dlq, get_redis
from app.models.dlq import DeadLetterEvent
from app.models.event import Event, EventStatus
from app.services.processor import ProcessorService

logger = get_logger(__name__)
_shutdown = False


def _handle_signal(sig, frame):
    global _shutdown
    logger.info("Shutdown signal received", extra={"signal": sig})
    _shutdown = True


def _get_session():
    """Import AsyncSessionLocal fresh each time so we always get the live value."""
    from app.db.postgres import AsyncSessionLocal
    if AsyncSessionLocal is None:
        raise RuntimeError("DB not initialized — AsyncSessionLocal is None")
    return AsyncSessionLocal()


# ── Core worker loop ──────────────────────────────────────────────────────────

async def process_batch(events_json: list[str]) -> None:
    """Process a batch of serialised events inside a single DB session."""
    processor = ProcessorService()

    async with _get_session() as db:
        for raw in events_json:
            event_dict: dict = {}
            try:
                event_dict = json.loads(raw)
                await _process_single(event_dict, processor, db)
            except Exception as exc:
                logger.error(
                    "Fatal error in batch processing",
                    extra={"error": str(exc), "raw": raw[:200]},
                    exc_info=True,
                )
                await enqueue_dlq(raw)
        await db.commit()


async def _process_single(
    event_dict: dict,
    processor: ProcessorService,
    db: AsyncSession,
) -> None:
    event_id_str = event_dict.get("id")
    retry_count  = event_dict.get("retry_count", 0)

    if event_id_str:
        await db.execute(
            update(Event)
            .where(Event.id == uuid.UUID(event_id_str))
            .values(status=EventStatus.PROCESSING, processor_id=_worker_id())
        )

    try:
        await processor.process(event_dict)

        if event_id_str:
            await db.execute(
                update(Event)
                .where(Event.id == uuid.UUID(event_id_str))
                .values(
                    status=EventStatus.PROCESSED,
                    processed_at=datetime.now(timezone.utc),
                )
            )
        await get_redis().incr("sentinel:metrics:processed_total")

    except Exception as exc:
        error_msg = str(exc)
        logger.warning(
            "Event processing failed",
            extra={"event_id": event_id_str, "retry": retry_count, "error": error_msg},
        )

        if retry_count < settings.MAX_RETRY_ATTEMPTS:
            backoff = settings.RETRY_BACKOFF_BASE ** retry_count
            await asyncio.sleep(backoff)
            event_dict["retry_count"] = retry_count + 1
            from app.db.redis_client import enqueue_event
            await enqueue_event(json.dumps(event_dict))

            if event_id_str:
                await db.execute(
                    update(Event)
                    .where(Event.id == uuid.UUID(event_id_str))
                    .values(
                        status=EventStatus.QUEUED,
                        retry_count=retry_count + 1,
                        error_message=error_msg,
                    )
                )
        else:
            await _send_to_dlq(event_dict, error_msg, db)
            if event_id_str:
                await db.execute(
                    update(Event)
                    .where(Event.id == uuid.UUID(event_id_str))
                    .values(
                        status=EventStatus.FAILED,
                        retry_count=retry_count,
                        error_message=error_msg,
                    )
                )
            await get_redis().incr("sentinel:metrics:failed_total")


async def _send_to_dlq(event_dict: dict, error_msg: str, db: AsyncSession) -> None:
    original_id_str = event_dict.get("id")
    dlq_entry = DeadLetterEvent(
        original_event_id=uuid.UUID(original_id_str) if original_id_str else None,
        event_type=event_dict.get("event_type", "unknown"),
        source=event_dict.get("source", "unknown"),
        payload=event_dict.get("payload", {}),
        failure_reason="max_retries_exceeded",
        retry_count=event_dict.get("retry_count", 0),
        last_error=error_msg,
    )
    db.add(dlq_entry)
    await enqueue_dlq(json.dumps(event_dict))
    logger.error(
        "Event moved to DLQ",
        extra={"original_id": original_id_str, "error": error_msg},
    )


def _worker_id() -> str:
    import os, socket
    return f"{socket.gethostname()}:{os.getpid()}"


# ── Entry point ───────────────────────────────────────────────────────────────

async def run_worker() -> None:
    global _shutdown
    setup_logging()
    await init_db()
    await init_redis()

    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("SentinelStream worker started", extra={"worker_id": _worker_id()})

    while not _shutdown:
        try:
            batch = await dequeue_events(settings.QUEUE_BATCH_SIZE)
            if batch:
                logger.debug("Processing batch", extra={"size": len(batch)})
                await process_batch(batch)
            else:
                await asyncio.sleep(0.1)
        except Exception as e:
            logger.error(f"Worker loop error: {e}", exc_info=True)
            await asyncio.sleep(1)  # brief pause before retrying

    logger.info("Worker shut down cleanly")


if __name__ == "__main__":
    asyncio.run(run_worker())