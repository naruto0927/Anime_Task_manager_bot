"""scheduler/expiry.py — Assignment expiry checker (runs every hour)."""
from __future__ import annotations
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client

from helper.alerts import notify_owners
from helper.assignment import expire_old_assignments

logger = logging.getLogger(__name__)


def register(scheduler: AsyncIOScheduler, app: Client) -> None:
    scheduler.add_job(
        _job,
        trigger="interval",
        hours=1,
        id="assignment_expiry",
        replace_existing=True,
        kwargs={"app": app},
    )
    logger.info("Scheduler: assignment_expiry registered (1h interval)")


async def _job(app: Client) -> None:
    try:
        expired = await expire_old_assignments()
        if expired:
            logger.info("Expired %d assignments", len(expired))
            lines = "\n".join(
                f"  • {e['title'][:40]} (user_id: {e['user_id']})"
                for e in expired[:10]
            )
            await notify_owners(
                app,
                f"⏰ **{len(expired)} assignment(s) expired:**\n{lines}",
                emoji="⏰",
            )
    except Exception as e:
        logger.error("Expiry job error: %s", e)
