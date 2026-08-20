"""scheduler/backup.py — Daily scheduled backup job."""
from __future__ import annotations
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client

from database.settings import get_int
from helper.backup import run_backup

logger = logging.getLogger(__name__)


def register(scheduler: AsyncIOScheduler, app: Client) -> None:
    """Register the daily backup job. Reads hour/minute from DB at schedule time."""
    scheduler.add_job(
        _job,
        trigger="interval",
        hours=24,
        id="daily_backup",
        replace_existing=True,
        kwargs={"app": app},
    )
    logger.info("Scheduler: daily_backup registered")


async def _job(app: Client) -> None:
    logger.info("Running scheduled backup…")
    ok = await run_backup(app)
    if not ok:
        logger.error("Scheduled backup failed")
    else:
        logger.info("Scheduled backup succeeded")
