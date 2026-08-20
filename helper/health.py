"""helper/health.py — System health check."""
from __future__ import annotations
import time
from typing import Any, Dict

try:
    import psutil as _psutil
except ImportError:
    _psutil = None

from database.mongo import get_db, ping_db
from database.settings import get as cfg_get
from helper.sheets import is_enabled as sheets_enabled, ping as sheets_ping

_start_time = time.time()


async def get_health() -> Dict[str, Any]:
    mongo_ok = await ping_db()

    sheets_ok = False
    sheets_status = "Disabled"
    try:
        if await sheets_enabled():
            sheets_ok = await sheets_ping()
            sheets_status = "OK" if sheets_ok else "FAILED"
        else:
            sheets_ok = True
            sheets_status = "Disabled"
    except Exception:
        sheets_status = "ERROR"

    db = get_db()
    pending = assigned = 0
    active_admins = away_admins = 0
    last_backup_str = "Never"

    if mongo_ok:
        pending  = await db.anime.count_documents({"status": "pending", "deleted": {"$ne": True}})
        assigned = await db.anime.count_documents({"status": "assigned"})
        active_admins = await db.users.count_documents({"role": "admin", "is_away": False})
        away_admins   = await db.users.count_documents({"role": "admin", "is_away": True})
        bk = await db.backups.find_one({"status": "success"}, sort=[("created_at", -1)])
        if bk:
            last_backup_str = bk["created_at"].strftime("%Y-%m-%d %H:%M UTC")

    dash_ch   = await cfg_get("dashboard_channel")
    log_ch    = await cfg_get("log_channel")
    backup_ch = await cfg_get("backup_channel")

    cpu = _psutil.cpu_percent(interval=1) if _psutil else 0
    mem_obj = _psutil.virtual_memory() if _psutil else None
    uptime_s = time.time() - _start_time

    return {
        "mongo_ok":       mongo_ok,
        "sheets_ok":      sheets_ok,
        "sheets_status":  sheets_status,
        "pending":        pending,
        "assigned":       assigned,
        "active_admins":  active_admins,
        "away_admins":    away_admins,
        "last_backup":    last_backup_str,
        "dash_ch":        dash_ch,
        "log_ch":         log_ch,
        "backup_ch":      backup_ch,
        "cpu":            cpu,
        "mem_used_mb":    mem_obj.used // (1024 * 1024) if mem_obj else 0,
        "mem_total_mb":   mem_obj.total // (1024 * 1024) if mem_obj else 0,
        "mem_pct":        mem_obj.percent if mem_obj else 0,
        "uptime_s":       uptime_s,
    }
