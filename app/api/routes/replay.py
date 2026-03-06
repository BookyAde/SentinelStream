"""
SentinelStream Replay API
POST /api/v1/replay          – replay specific DLQ events
POST /api/v1/replay/all      – replay all pending DLQ events
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgres import get_db
from app.schemas.events import ReplayRequest, ReplayResponse
from app.services.replay import ReplayService

router = APIRouter()


@router.post("", response_model=ReplayResponse, status_code=status.HTTP_202_ACCEPTED)
async def replay_events(request: ReplayRequest, db: AsyncSession = Depends(get_db)):
    """Replay specific Dead Letter Queue events by ID."""
    service = ReplayService(db)
    return await service.replay(request)


@router.post("/all", response_model=ReplayResponse, status_code=status.HTTP_202_ACCEPTED)
async def replay_all(limit: int = 500, db: AsyncSession = Depends(get_db)):
    """Replay all un-replayed DLQ events (up to limit)."""
    service = ReplayService(db)
    return await service.replay_all_pending(limit=limit)
