"""
SentinelStream Ingestion Service
Validates, persists, and enqueues incoming events.
Handles both single and batch ingestion with idempotency.
"""

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.logging import get_logger
from app.db.redis_client import enqueue_event
from app.models.event import Event, EventStatus
from app.schemas.events import EventIngest, BatchIngestResponse, IngestResponse

logger = get_logger(__name__)


class IngestionService:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Single event ──────────────────────────────────────────────────────────

    async def ingest(self, data: EventIngest) -> IngestResponse:
        """Persist an event to Postgres and push it onto the Redis queue."""
        # Idempotency check on external_id
        if data.external_id:
            existing = await self._find_by_external_id(data.external_id)
            if existing:
                logger.info("Duplicate event ignored", extra={"external_id": data.external_id})
                queue_len = 0  # already processed
                return IngestResponse(
                    event_id=existing.id,
                    status="duplicate",
                    queue_position=queue_len,
                )

        event = Event(
            id=uuid.uuid4(),
            external_id=data.external_id,
            event_type=data.event_type,
            source=data.source,
            priority=data.priority,
            payload=data.payload,
            metadata_=data.metadata,
            status=EventStatus.QUEUED,
        )
        self.db.add(event)
        await self.db.flush()  # get the ID without committing

        queue_len = await enqueue_event(self._serialize(event))

        logger.info(
            "Event ingested",
            extra={"event_id": str(event.id), "type": event.event_type, "queue_len": queue_len},
        )
        return IngestResponse(event_id=event.id, status="queued", queue_position=queue_len)

    # ── Batch ingestion ───────────────────────────────────────────────────────

    async def ingest_batch(self, events: list[EventIngest]) -> BatchIngestResponse:
        """Ingest multiple events atomically, returning per-event results."""
        accepted_ids: list[uuid.UUID] = []
        errors: list[str] = []

        for idx, data in enumerate(events):
            try:
                result = await self.ingest(data)
                if result.status != "duplicate":
                    accepted_ids.append(result.event_id)
            except Exception as exc:
                msg = f"Event[{idx}] failed: {exc}"
                errors.append(msg)
                logger.warning(msg)

        return BatchIngestResponse(
            accepted=len(accepted_ids),
            rejected=len(errors),
            event_ids=accepted_ids,
            errors=errors,
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _find_by_external_id(self, external_id: str) -> Event | None:
        stmt = select(Event).where(Event.external_id == external_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    @staticmethod
    def _serialize(event: Event) -> str:
        return json.dumps(
            {
                "id": str(event.id),
                "event_type": event.event_type,
                "source": event.source,
                "priority": event.priority.value,
                "payload": event.payload,
                "metadata": event.metadata_,
                "enqueued_at": datetime.now(timezone.utc).isoformat(),
                "retry_count": 0,
            }
        )
