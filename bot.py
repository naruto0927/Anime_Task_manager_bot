"""bot.py — Uses Bot().run() pattern, same as Kakashi bot."""
import asyncio
import logging
import os
import sys
from datetime import datetime

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
    _UVLOOP = True
except ImportError:
    _UVLOOP = False

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client, idle
from pyrogram.types import BotCommand
from config import API_HASH, API_ID, BOT_TOKEN, LOG_LEVEL, OWNER_ID

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("logs/bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

from helper.aliases import init_owners, _owner_ids
init_owners(OWNER_ID)

scheduler = AsyncIOScheduler(timezone="UTC")


class Bot(Client):
    def __init__(self):
        super().__init__(
            name="AnimeAssignBot",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=BOT_TOKEN,
            plugins={"root": "plugins"},
            workers=4,
        )
        self.uptime = None

    async def start(self):
        await super().start()
        self.uptime = datetime.now()
        me = await self.get_me()
        logger.info("uvloop: %s | Bot: @%s", _UVLOOP, me.username)

        # Connect DB
        from database.mongo import connect_db
        from database.config import cfg
        await connect_db()
        await cfg.initialize_defaults()

        db_owners = await cfg.get_owner_ids()
        if db_owners:
            init_owners(*db_owners)
        logger.info("Owner IDs: %s", list(_owner_ids))

        # Register scheduler
        from scheduler import backup, dashboard, expiry, health, sheets as sh_job
        backup.register(scheduler, self)
        dashboard.register(scheduler, self)
        expiry.register(scheduler, self)
        health.register(scheduler, self)
        sh_job.register(scheduler, self)
        scheduler.start()
        logger.info("Scheduler started — %d jobs.", len(scheduler.get_jobs()))

        # Health snapshot
        try:
            from helper.alerts import write_health_snapshot
            await write_health_snapshot()
        except Exception as e:
            logger.warning("Health snapshot failed: %s", e)

        # Health server (Koyeb only)
        port_str = os.environ.get("PORT", "")
        if port_str:
            try:
                from aiohttp import web
                async def handle(_req):
                    return web.Response(text="OK")
                srv = web.Application()
                srv.router.add_get("/", handle)
                srv.router.add_get("/health", handle)
                runner = web.AppRunner(srv)
                await runner.setup()
                await web.TCPSite(runner, "0.0.0.0", int(port_str)).start()
                logger.info("Health server on port %s", port_str)
            except Exception as e:
                logger.warning("Health server failed: %s", e)

        # Notify owners
        text = (
            f"✅ **{me.first_name} is online!**\n\n"
            f"• uvloop: {'✅' if _UVLOOP else '❌'}\n"
            f"• MongoDB connected\n"
            f"• {len(scheduler.get_jobs())} scheduler jobs active\n\n"
            "Use /health for system status.\n"
            "Use /help for commands."
        )
        for oid in _owner_ids:
            try:
                await self.send_message(oid, text)
            except Exception:
                pass

        logger.info("Bot startup complete.")

    async def stop(self, *args):
        scheduler.shutdown(wait=False)
        from database.mongo import disconnect_db
        await disconnect_db()
        await super().stop()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    Bot().run()
