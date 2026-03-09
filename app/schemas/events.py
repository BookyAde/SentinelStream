"""
SentinelStream Pydantic Schemas
Request validation and response serialisation for all API endpoints.
"""

import uuid
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator

from app.models.event import EventStatus, EventPriority


# ── Inbound event ingestion ────────────────────────────────────────────────────

class EventIngest(BaseModel):
    """Payload sent by a producer to enqueue a new event."""
    event_type: str = Field(..., min_length=1, max_length=100)
    source: str = Field(..., min_length=1, max_length=100)
    priority: EventPriority = EventPriority.NORMAL
    payload: dict[str, Any] = Field(..., description="Arbitrary event data")
    metadata: Optional[dict[str, Any]] = None
    external_id: Optional[str] = Field(None, max_length=255)

    @field_validator("event_type", "source")
    @classmethod
    def no_whitespace(cls, v: str) -> str:
        return v.strip()


class BatchEventIngest(BaseModel):
    """Batch ingestion — up to 500 events per call."""
    events: list[EventIngest] = Field(..., min_length=1, max_length=500)


# ── Responses ─────────────────────────────────────────────────────────────────

class EventResponse(BaseModel):
    id: uuid.UUID
    external_id: Optional[str] = None
    event_type: str
    source: str
    priority: EventPriority
    payload: dict[str, Any]
    metadata: Optional[dict[str, Any]] = Field(None, alias="metadata_")
    status: EventStatus
    retry_count: int
    error_message: Optional[str] = None
    processor_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    processed_at: Optional[datetime] = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class IngestResponse(BaseModel):
    event_id: uuid.UUID
    status: str = "queued"
    queue_position: int


class BatchIngestResponse(BaseModel):
    accepted: int
    rejected: int
    event_ids: list[uuid.UUID]
    errors: list[str]


# ── DLQ ───────────────────────────────────────────────────────────────────────

class DLQEventResponse(BaseModel):
    id: uuid.UUID
    original_event_id: Optional[uuid.UUID]
    event_type: str
    source: str
    payload: dict[str, Any]
    failure_reason: str
    retry_count: int
    last_error: Optional[str]
    replayed: bool
    replayed_at: Optional[datetime]
    replay_event_id: Optional[uuid.UUID]
    created_at: datetime

    model_config = {"from_attributes": True}


class ReplayRequest(BaseModel):
    dlq_event_ids: list[uuid.UUID] = Field(..., min_length=1, max_length=100)
    priority_override: Optional[EventPriority] = None


class ReplayResponse(BaseModel):
    replayed: int
    failed: int
    new_event_ids: list[uuid.UUID]
    errors: list[str]


# ── Metrics / monitoring ──────────────────────────────────────────────────────

class QueueMetrics(BaseModel):
    main_queue_depth: int
    dlq_depth: int
    timestamp: datetime


class ProcessingMetrics(BaseModel):
    total_events: int
    processed_last_hour: int
    failed_last_hour: int
    avg_processing_ms: float
    p99_processing_ms: float
    throughput_per_second: float


class PipelineHealth(BaseModel):
    status: str  # "healthy" | "degraded" | "unhealthy"
    queue: QueueMetrics
    processing: ProcessingMetrics
    worker_count: int
    uptime_seconds: float


# ── Filtering / pagination ────────────────────────────────────────────────────

class EventFilter(BaseModel):
    status: Optional[EventStatus] = None
    event_type: Optional[str] = None
    source: Optional[str] = None
    priority: Optional[EventPriority] = None
    from_dt: Optional[datetime] = None
    to_dt: Optional[datetime] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=500)


class PaginatedEvents(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[EventResponse]