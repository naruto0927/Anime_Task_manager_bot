"""helper/alerts.py — Owner alert helpers."""
from __future__ import annotations
import logging
import time
import uuid
from datetime import datetime

try:
    import psutil as _psutil
except ImportError:
    _psutil = None
from pyrogram import Client

from database.mongo import get_db, ping_db
from helper.aliases import _owner_ids

logger = logging.getLogger(__name__)
_start_time = time.time()


async def notify_owners(app: Client, message: str, emoji: str = "🚨") -> None:
    text = f"{emoji} **System Alert**\n\n{message}"
    for oid in _owner_ids:
        try:
            await app.send_message(oid, text)
        except Exception as e:
            logger.error("Failed to alert owner %s: %s", oid, e)


async def write_health_snapshot() -> None:
    db = get_db()
    try:
        mongo_ok = await ping_db()
        pending  = await db.anime.count_documents({"status": "pending"}) if mongo_ok else 0
        assigned = await db.anime.count_documents({"status": "assigned"}) if mongo_ok else 0
        bk = await db.backups.find_one({"status": "success"}, sort=[("created_at", -1)])
        last_bk = bk["created_at"] if bk else None
        cpu    = _psutil.cpu_percent(interval=None) if _psutil else 0
        mem    = _psutil.virtual_memory().percent if _psutil else 0
        uptime = time.time() - _start_time
        await db.health.insert_one({
            "snapshot_id":    str(uuid.uuid4()),
            "timestamp":      datetime.utcnow(),
            "bot_ok":         True,
            "mongo_ok":       mongo_ok,
            "pending_count":  pending,
            "assigned_count": assigned,
            "last_backup":    last_bk,
            "cpu_percent":    cpu,
            "memory_percent": mem,
            "uptime_seconds": uptime,
        })
        # Trim to last 1000
        count = await db.health.count_documents({})
        if count > 1000:
            oldest = await db.health.find_one({}, sort=[("timestamp", 1)])
            if oldest:
                await db.health.delete_one({"_id": oldest["_id"]})
    except Exception as e:
        logger.error("Health snapshot failed: %s", e)
