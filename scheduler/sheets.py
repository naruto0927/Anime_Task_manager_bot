"""scheduler/sheets.py — Periodic Google Sheets sync job."""
from __future__ import annotations
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client

from database.settings import get_bool, get_int
from helper.sheets import full_sync

logger = logging.getLogger(__name__)


def register(scheduler: AsyncIOScheduler, app: Client) -> None:
    scheduler.add_job(
        _job,
        trigger="interval",
        hours=1,
        id="sheets_sync",
        replace_existing=True,
        kwargs={"app": app},
    )
    logger.info("Scheduler: sheets_sync registered (1h interval)")


async def _job(app: Client) -> None:
    try:
        if not await get_bool("sheets_auto_sync", False):
            return
        interval = await get_int("sheets_sync_interval", 3600)
        ok = await full_sync()
        if not ok:
            logger.warning("Sheets auto-sync failed")
        else:
            logger.info("Sheets auto-sync complete")
    except Exception as e:
        logger.error("Sheets sync job error: %s", e)
