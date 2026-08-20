"""scheduler/health.py — Periodic health snapshot job."""
from __future__ import annotations
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client

from helper.alerts import write_health_snapshot

logger = logging.getLogger(__name__)


def register(scheduler: AsyncIOScheduler, app: Client) -> None:
    scheduler.add_job(
        _job,
        trigger="interval",
        minutes=15,
        id="health_snapshot",
        replace_existing=True,
        kwargs={"app": app},
    )
    logger.info("Scheduler: health_snapshot registered (15m interval)")


async def _job(app: Client) -> None:
    try:
        await write_health_snapshot()
    except Exception as e:
        logger.error("Health snapshot error: %s", e)
