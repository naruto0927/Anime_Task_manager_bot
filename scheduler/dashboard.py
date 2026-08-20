"""scheduler/dashboard.py — Periodic dashboard refresh job."""
from __future__ import annotations
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client

from database.settings import get_int
from helper.dashboard import update_all

logger = logging.getLogger(__name__)


def register(scheduler: AsyncIOScheduler, app: Client) -> None:
    # Store scheduler ref on the function so _job can reschedule without importing bot
    _job._scheduler = scheduler
    scheduler.add_job(
        _job,
        trigger="interval",
        seconds=300,
        id="dashboard_refresh",
        replace_existing=True,
        kwargs={"app": app},
    )
    logger.info("Scheduler: dashboard_refresh registered (300s interval)")


async def _job(app: Client) -> None:
    try:
        interval = await get_int("dashboard_update_interval", 300)
        sched = getattr(_job, "_scheduler", None)
        if sched:
            job = sched.get_job("dashboard_refresh")
            if job and job.trigger.interval.total_seconds() != interval:
                sched.reschedule_job(
                    "dashboard_refresh",
                    trigger="interval",
                    seconds=interval,
                )
                logger.info("Dashboard interval updated to %ds", interval)
        await update_all(app)
    except Exception as e:
        logger.warning("Dashboard refresh error: %s", e)
