"""
SentinelStream Events API
POST /api/v1/events          – ingest single event
POST /api/v1/events/batch    – ingest batch
GET  /api/v1/events          – list/filter events
GET  /api/v1/events/{id}     – fetch single event
GET  /api/v1/events/dlq      – list DLQ events
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
import uuid

from app.db.postgres import get_db
from app.models.event import Event, EventStatus, EventPriority
from app.models.dlq import DeadLetterEvent
from app.schemas.events import (
    EventIngest, BatchEventIngest,
    EventResponse, IngestResponse, BatchIngestResponse,
    DLQEventResponse, PaginatedEvents, EventFilter,
)
from app.services.ingestion import IngestionService

router = APIRouter()


@router.post("", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_event(data: EventIngest, db: AsyncSession = Depends(get_db)):
    """Ingest a single event into the pipeline."""
    service = IngestionService(db)
    return await service.ingest(data)


@router.post("/batch", response_model=BatchIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_batch(data: BatchEventIngest, db: AsyncSession = Depends(get_db)):
    """Ingest a batch of events (max 500 per request)."""
    service = IngestionService(db)
    return await service.ingest_batch(data.events)


@router.get("", response_model=PaginatedEvents)
async def list_events(
    status: Optional[EventStatus] = Query(None),
    event_type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    priority: Optional[EventPriority] = Query(None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """List events with optional filtering and pagination."""
    stmt = select(Event)
    count_stmt = select(func.count()).select_from(Event)

    if status:
        stmt = stmt.where(Event.status == status)
        count_stmt = count_stmt.where(Event.status == status)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
        count_stmt = count_stmt.where(Event.event_type == event_type)
    if source:
        stmt = stmt.where(Event.source == source)
        count_stmt = count_stmt.where(Event.source == source)
    if priority:
        stmt = stmt.where(Event.priority == priority)
        count_stmt = count_stmt.where(Event.priority == priority)

    total = (await db.execute(count_stmt)).scalar_one()
    offset = (page - 1) * page_size
    stmt = stmt.order_by(Event.created_at.desc()).offset(offset).limit(page_size)
    items = (await db.execute(stmt)).scalars().all()

    return PaginatedEvents(total=total, page=page, page_size=page_size, items=items)


@router.get("/dlq", response_model=list[DLQEventResponse])
async def list_dlq(
    replayed: Optional[bool] = Query(None),
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """List Dead Letter Queue events."""
    stmt = select(DeadLetterEvent).order_by(DeadLetterEvent.created_at.desc()).limit(limit)
    if replayed is not None:
        stmt = stmt.where(DeadLetterEvent.replayed == replayed)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/{event_id}", response_model=EventResponse)
async def get_event(event_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    """Fetch a single event by ID."""
    result = await db.execute(select(Event).where(Event.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Event not found")
    return event
