"""
SentinelStream PostgreSQL Database
Async SQLAlchemy engine, session factory, and initialization.
"""

from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
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
    """Create all tables on startup. Uses checkfirst=True so re-runs are safe."""
    from app.models import event, dlq  # noqa: F401 – ensures models are registered

    async with engine.begin() as conn:
        # checkfirst=True makes CREATE TABLE and CREATE TYPE idempotent —
        # they are skipped if the object already exists in the database.
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)
    logger.info("Database initialized")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()