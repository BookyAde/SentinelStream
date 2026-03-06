"""Standalone worker entrypoint — run with: python run_worker.py"""
import asyncio
from app.workers.event_worker import run_worker

if __name__ == "__main__":
    asyncio.run(run_worker())
