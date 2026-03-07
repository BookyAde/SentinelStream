"""
SentinelStream PostgreSQL Database
Supports both DATABASE_URL (Railway) and individual vars (local Docker).
"""

import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _get_database_url() -> str:
    # Railway provides DATABASE_URL directly — convert to asyncpg format
    url = os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_PRIVATE_URL")
    if url:
        # Railway uses postgres:// — SQLAlchemy needs postgresql+asyncpg://
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url
    # Fall back to constructed URL for local Docker
    return settings.DATABASE_URL


engine = create_async_engine(
    _get_database_url(),
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=settings.DEBUG,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def init_db() -> None:
    from app.models import event, dlq  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
    logger.info("Database initialized")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()