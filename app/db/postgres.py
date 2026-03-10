"""
SentinelStream PostgreSQL Database
"""

import os
from typing import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.core.logging import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    pass


# Lazily initialized — NOT created at import time
engine = None
AsyncSessionLocal = None


def _get_database_url() -> str:
    url = (
        os.environ.get("DATABASE_URL") or
        os.environ.get("DATABASE_PRIVATE_URL")
    )
    if not url:
        # Build from parts
        host     = os.environ.get("POSTGRES_HOST", "localhost")
        port     = os.environ.get("POSTGRES_PORT", "5432")
        user     = os.environ.get("POSTGRES_USER", "postgres")
        password = os.environ.get("POSTGRES_PASSWORD", "postgres")
        db       = os.environ.get("POSTGRES_DB", "sentinelstream")
        url = f"postgresql+asyncpg://{user}:{password}@{host}:{port}/{db}"
        logger.info(f"Built DB URL from parts: host={host} port={port} db={db}")
        return url

    # Normalize scheme for asyncpg
    url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    if "postgresql+asyncpg+asyncpg://" in url:
        url = url.replace("postgresql+asyncpg+asyncpg://", "postgresql+asyncpg://", 1)

    logger.info(f"Using DATABASE_URL from environment")
    return url


async def init_db() -> None:
    global engine, AsyncSessionLocal

    db_url = _get_database_url()
    logger.info(f"Initializing DB engine...")

    engine = create_async_engine(
        db_url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        echo=False,
    )

    AsyncSessionLocal = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autoflush=False,
    )

    from app.models import event, dlq, workspace  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all, checkfirst=True)

    logger.info("Database initialized successfully")


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    if AsyncSessionLocal is None:
        raise RuntimeError("Database not initialized — call init_db() first")
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()