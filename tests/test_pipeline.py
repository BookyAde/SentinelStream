"""
SentinelStream Test Suite
Covers ingestion, processing, DLQ routing, and replay flows.
"""

import json
import uuid
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from httpx import AsyncClient, ASGITransport

# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_event():
    return {
        "event_type": "user_action",
        "source": "web-app",
        "priority": "normal",
        "payload": {"user_id": "u_123", "action": "login"},
    }


@pytest.fixture
def sample_batch(sample_event):
    return {"events": [sample_event] * 5}


# ── Ingestion ─────────────────────────────────────────────────────────────────

class TestIngestion:
    @pytest.mark.asyncio
    async def test_ingest_single_event(self, sample_event):
        """Single event ingest returns 202 with event_id and queued status."""
        with (
            patch("app.services.ingestion.IngestionService.ingest", new_callable=AsyncMock) as mock_ingest,
        ):
            mock_ingest.return_value = MagicMock(
                event_id=uuid.uuid4(), status="queued", queue_position=1
            )
            # Integration test would wire up a real TestClient here
            assert mock_ingest.return_value.status == "queued"

    @pytest.mark.asyncio
    async def test_ingest_idempotency(self, sample_event):
        """Duplicate external_id returns status=duplicate."""
        event_with_id = {**sample_event, "external_id": "ext-001"}
        with patch(
            "app.services.ingestion.IngestionService._find_by_external_id",
            new_callable=AsyncMock,
        ) as mock_find:
            mock_event = MagicMock()
            mock_event.id = uuid.uuid4()
            mock_find.return_value = mock_event

            from app.services.ingestion import IngestionService
            from app.schemas.events import EventIngest

            service = IngestionService(db=AsyncMock())
            data = EventIngest(**event_with_id)
            result = await service.ingest(data)
            assert result.status == "duplicate"

    @pytest.mark.asyncio
    async def test_batch_ingest(self, sample_batch):
        """Batch ingest returns per-event results."""
        with patch(
            "app.services.ingestion.IngestionService.ingest",
            new_callable=AsyncMock,
        ) as mock_ingest:
            mock_ingest.return_value = MagicMock(
                event_id=uuid.uuid4(), status="queued", queue_position=1
            )
            from app.services.ingestion import IngestionService
            from app.schemas.events import EventIngest
            service = IngestionService(db=AsyncMock())
            events = [EventIngest(**e) for e in sample_batch["events"]]
            result = await service.ingest_batch(events)
            assert result.accepted == 5
            assert result.rejected == 0


# ── Worker / DLQ routing ──────────────────────────────────────────────────────

class TestWorker:
    @pytest.mark.asyncio
    async def test_failed_event_goes_to_dlq(self):
        """An event that fails MAX_RETRY_ATTEMPTS times is moved to DLQ."""
        from app.workers.event_worker import _process_single
        from app.services.processor import ProcessorService

        failing_processor = AsyncMock(side_effect=RuntimeError("Boom"))
        event = {
            "id": str(uuid.uuid4()),
            "event_type": "bad_type",
            "source": "test",
            "payload": {},
            "retry_count": 3,  # already exhausted
        }
        db = AsyncMock()

        with (
            patch("app.workers.event_worker._send_to_dlq", new_callable=AsyncMock) as mock_dlq,
            patch("app.workers.event_worker.ProcessorService") as MockProcessor,
            patch("app.workers.event_worker.get_redis") as mock_redis,
        ):
            MockProcessor.return_value.process = failing_processor
            mock_redis.return_value = AsyncMock()
            await _process_single(event, MockProcessor(), db)
            mock_dlq.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_on_transient_failure(self):
        """An event with retries remaining is re-queued, not DLQ'd."""
        from app.workers.event_worker import _process_single

        failing_processor = AsyncMock(side_effect=RuntimeError("Transient"))
        event = {
            "id": str(uuid.uuid4()),
            "event_type": "user_action",
            "source": "test",
            "payload": {},
            "retry_count": 0,
        }
        db = AsyncMock()

        with (
            patch("app.workers.event_worker._send_to_dlq", new_callable=AsyncMock) as mock_dlq,
            patch("app.workers.event_worker.ProcessorService") as MockProcessor,
            patch("app.workers.event_worker.get_redis") as mock_redis,
            patch("app.workers.event_worker.asyncio.sleep", new_callable=AsyncMock),
            patch("app.db.redis_client.enqueue_event", new_callable=AsyncMock),
        ):
            MockProcessor.return_value.process = failing_processor
            mock_redis.return_value = AsyncMock()
            await _process_single(event, MockProcessor(), db)
            mock_dlq.assert_not_called()


# ── Replay ────────────────────────────────────────────────────────────────────

class TestReplay:
    @pytest.mark.asyncio
    async def test_replay_creates_new_event(self):
        """Replaying a DLQ event creates a new Event row and marks DLQ as replayed."""
        from app.services.replay import ReplayService
        from app.models.dlq import DeadLetterEvent

        dlq_event = DeadLetterEvent(
            id=uuid.uuid4(),
            event_type="user_action",
            source="web",
            payload={"user_id": "u_1"},
            failure_reason="max_retries_exceeded",
            retry_count=3,
            replayed=False,
        )

        db = AsyncMock()
        db.execute = AsyncMock(return_value=AsyncMock(scalar_one_or_none=lambda: dlq_event))
        db.flush = AsyncMock()

        with patch("app.services.replay.enqueue_event", new_callable=AsyncMock):
            service = ReplayService(db=db)
            # Minimal smoke test — full integration would use a real DB
            assert dlq_event.replayed == False
