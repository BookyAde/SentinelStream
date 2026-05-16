"""
SentinelStream Configuration
All settings loaded from environment variables with sensible defaults.
"""

from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Application ──────────────────────────────────────────────────────────

    APP_NAME: str = "SentinelStream"
    ENVIRONMENT: str = "development"
    DEBUG: bool = False

    APP_VERSION: str = "1.1.0"

    API_BASE_URL: str = "http://localhost:8000"

    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://www.omspglobal.org",
        "https://omspglobal.org",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",")]
        return value

    # ── PostgreSQL ───────────────────────────────────────────────────────────

    DATABASE_URL: str | None = None

    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "sentinel"
    POSTGRES_PASSWORD: str = "sentinel_secret"
    POSTGRES_DB: str = "sentinelstream"

    @property
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL

        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def database_url_sync(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL.replace(
                "postgresql+asyncpg://",
                "postgresql://",
            )

        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── Redis ────────────────────────────────────────────────────────────────

    REDIS_URL: str | None = None

    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""
    REDIS_DB: int = 0

    @property
    def redis_url(self) -> str:
        if self.REDIS_URL:
            return self.REDIS_URL

        if self.REDIS_PASSWORD:
            return (
                f"redis://:{self.REDIS_PASSWORD}"
                f"@{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
            )

        return (
            f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/{self.REDIS_DB}"
        )

    # ── Queue configuration ──────────────────────────────────────────────────

    EVENT_QUEUE_NAME: str = "sentinel:events"
    DLQ_NAME: str = "sentinel:dlq"
    PROCESSING_QUEUE_NAME: str = "sentinel:processing"

    MAX_RETRY_ATTEMPTS: int = 3
    RETRY_BACKOFF_BASE: float = 2.0

    QUEUE_BATCH_SIZE: int = 50
    WORKER_CONCURRENCY: int = 4

    # ── Auth / JWT ───────────────────────────────────────────────────────────

    JWT_SECRET: str = "change-this-in-production-use-a-long-random-string"

    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60 * 24 * 7

    # ── Monitoring ───────────────────────────────────────────────────────────

    METRICS_RETENTION_DAYS: int = 30
    ALERT_THRESHOLD_DLQ: int = 100

    # ── Railway / deployment ────────────────────────────────────────────────

    PORT: int = 8000

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()