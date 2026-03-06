"""
SentinelStream Replay Service
Re-enqueues failed events from the Dead Letter Queue.
Supports bulk replay and per-event targeting.
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.db.redis_client import enqueue_event, remove_from_dlq
from app.models.dlq import DeadLetterEvent
from app.models.event import Event, EventStatus, EventPriority
from app.schemas.events import ReplayRequest, ReplayResponse

logger = get_logger(__name__)


class ReplayService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def replay(self, request: ReplayRequest) -> ReplayResponse:
        """
        Replay a list of DLQ events by re-ingesting them into the main queue.
        Each replayed event creates a fresh Event row and marks the DLQ entry
        as replayed.
        """
        new_ids: list[uuid.UUID] = []
        errors: list[str] = []

        for dlq_id in request.dlq_event_ids:
            try:
                new_event_id = await self._replay_one(dlq_id, request.priority_override)
                new_ids.append(new_event_id)
            except Exception as exc:
                msg = f"DLQ[{dlq_id}] replay failed: {exc}"
                errors.append(msg)
                logger.error(msg, exc_info=True)

        return ReplayResponse(
            replayed=len(new_ids),
            failed=len(errors),
            new_event_ids=new_ids,
            errors=errors,
        )

    async def replay_all_pending(self, limit: int = 500) -> ReplayResponse:
        """Replay every un-replayed DLQ entry (up to *limit*)."""
        stmt = (
            select(DeadLetterEvent)
            .where(DeadLetterEvent.replayed == False)  # noqa: E712
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        dlq_events = result.scalars().all()

        new_ids: list[uuid.UUID] = []
        errors: list[str] = []

        for dlq_event in dlq_events:
            try:
                new_id = await self._replay_one(dlq_event.id)
                new_ids.append(new_id)
            except Exception as exc:
                errors.append(f"DLQ[{dlq_event.id}]: {exc}")

        logger.info(
            "Bulk replay complete",
            extra={"replayed": len(new_ids), "errors": len(errors)},
        )
        return ReplayResponse(
            replayed=len(new_ids),
            failed=len(errors),
            new_event_ids=new_ids,
            errors=errors,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _replay_one(
        self,
        dlq_id: uuid.UUID,
        priority_override: EventPriority | None = None,
    ) -> uuid.UUID:
        stmt = select(DeadLetterEvent).where(DeadLetterEvent.id == dlq_id)
        result = await self.db.execute(stmt)
        dlq_event = result.scalar_one_or_none()

        if not dlq_event:
            raise ValueError(f"DLQ event {dlq_id} not found")
        if dlq_event.replayed:
            raise ValueError(f"DLQ event {dlq_id} already replayed")

        priority = priority_override or EventPriority.NORMAL

        # Create a fresh event
        new_event = Event(
            id=uuid.uuid4(),
            event_type=dlq_event.event_type,
            source=dlq_event.source,
            priority=priority,
            payload=dlq_event.payload,
            status=EventStatus.QUEUED,
        )
        self.db.add(new_event)
        await self.db.flush()

        # Mark DLQ entry as replayed
        dlq_event.replayed = True
        dlq_event.replayed_at = datetime.now(timezone.utc)
        dlq_event.replay_event_id = new_event.id

        # Enqueue
        import json
        await enqueue_event(
            json.dumps(
                {
                    "id": str(new_event.id),
                    "event_type": new_event.event_type,
                    "source": new_event.source,
                    "priority": new_event.priority.value,
                    "payload": new_event.payload,
                    "retry_count": 0,
                    "replayed_from": str(dlq_id),
                }
            )
        )

        logger.info(
            "DLQ event replayed",
            extra={"dlq_id": str(dlq_id), "new_event_id": str(new_event.id)},
        )
        return new_event.id
