"""
SentinelStream Processor Service
Core business logic executed for each event.
Add your domain-specific handlers in the REGISTRY dict.
"""

import asyncio
from datetime import datetime, timezone
from typing import Callable, Awaitable

from app.core.logging import get_logger

logger = get_logger(__name__)

# Type alias for a processor function
EventProcessor = Callable[[dict], Awaitable[dict]]


# ── Handlers ──────────────────────────────────────────────────────────────────

async def _handle_default(event: dict) -> dict:
    """Fallback handler — logs and passes through."""
    logger.debug("Default handler", extra={"event_type": event.get("event_type")})
    await asyncio.sleep(0)  # yield control
    return {"result": "passthrough"}


async def _handle_user_action(event: dict) -> dict:
    """Example: user-action events."""
    payload = event["payload"]
    return {
        "result": "processed",
        "user_id": payload.get("user_id"),
        "action": payload.get("action"),
    }


async def _handle_system_alert(event: dict) -> dict:
    """Example: system-alert events — could fan out to PagerDuty etc."""
    payload = event["payload"]
    severity = payload.get("severity", "unknown")
    logger.warning("System alert received", extra={"severity": severity})
    return {"result": "alerted", "severity": severity}


async def _handle_payment(event: dict) -> dict:
    """Example: payment events."""
    payload = event["payload"]
    return {
        "result": "payment_processed",
        "amount": payload.get("amount"),
    }


# ── Handler registry ──────────────────────────────────────────────────────────
# Register your domain handlers here. Each must be an async callable that
# accepts the raw event dict and returns an enriched/result dict.

HANDLER_REGISTRY: dict[str, EventProcessor] = {
    "user_action": _handle_user_action,
    "system_alert": _handle_system_alert,
    "payment": _handle_payment,
    # Add more event types here
}


# ── Processor ─────────────────────────────────────────────────────────────────

class ProcessorService:
    """Routes an event to the appropriate handler and returns the outcome."""

    async def process(self, event: dict) -> dict:
        event_type = event.get("event_type", "unknown")
        handler = HANDLER_REGISTRY.get(event_type, _handle_default)

        start = datetime.now(timezone.utc)
        result = await handler(event)
        elapsed_ms = (datetime.now(timezone.utc) - start).total_seconds() * 1000

        logger.info(
            "Event processed",
            extra={
                "event_id": event.get("id"),
                "event_type": event_type,
                "elapsed_ms": round(elapsed_ms, 2),
            },
        )
        return {**result, "processing_ms": elapsed_ms}