"""
SentinelStream Worker Entrypoint
Run with: python run_worker.py
"""

import asyncio
import signal
import sys

from app.workers.event_worker import run_worker


async def main():
    await run_worker()


def shutdown_handler(*_):
    print("Shutting down SentinelStream worker...")
    sys.exit(0)


if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    asyncio.run(main())