"""helper/sheets.py — Google Sheets sync logic."""
from __future__ import annotations
import asyncio
import csv
import io
import logging
from datetime import datetime
from functools import partial
from typing import Dict, List, Optional

from database.mongo import get_db
from database.settings import get_bool, get_str

logger = logging.getLogger(__name__)

TABS = {
    "overview":       "Overview",
    "pending":        "Pending",
    "assigned":       "Assigned",
    "completed":      "Completed",
    "dropped":        "Dropped",
    "admin_stats":    "Admin Stats",
    "season_reports": "Season Reports",
}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


async def is_enabled() -> bool:
    return await get_bool("sheets_enabled", False)


async def spreadsheet_url() -> Optional[str]:
    sid = await get_str("sheets_spreadsheet_id", "")
    return f"https://docs.google.com/spreadsheets/d/{sid}/edit" if sid else None


async def full_sync() -> bool:
    if not await is_enabled():
        return True
    try:
        await sync_overview()
        await sync_pending()
        await sync_assigned()
        await sync_completed()
        await sync_dropped()
        await sync_admin_stats()
        await sync_season_reports()
        logger.info("Google Sheets full sync complete")
        return True
    except Exception as e:
        logger.error("Sheets sync failed: %s", e)
        return False


async def ping() -> bool:
    try:
        ws = await _get_or_create_tab("Overview")
        return ws is not None
    except Exception:
        return False


async def export_tab_csv(tab_key: str) -> bytes:
    rows = await _read_tab(tab_key)
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


# ── Sync methods ──────────────────────────────────────────────────────────

async def sync_overview() -> None:
    from helper.stats import global_stats
    s = await global_stats()
    ws  = await _get_or_create_tab(TABS["overview"])
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    data = [
        ["Metric", "Count", "Last Updated"],
        ["Total Anime",  s["total"],     now],
        ["Pending",      s["pending"],   ""],
        ["Assigned",     s["assigned"],  ""],
        ["Encoded",      s["encoded"],   ""],
        ["Leeched",      s["leeched"],   ""],
        ["Completed",    s["completed"], ""],
        ["Dropped",      s["dropped"],   ""],
        ["Invalid",      s["invalid"],   ""],
    ]
    await _write(ws, data)


async def sync_pending() -> None:
    db = get_db()
    ws = await _get_or_create_tab(TABS["pending"])
    rows = [["Title", "MAL ID", "Type", "Year", "Season", "Priority", "Franchise", "Imported At"]]
    async for a in db.anime.find({"status": "pending", "deleted": {"$ne": True}}):
        rows.append([
            a["titles"].get("display_title", ""),
            str(a.get("mal_id", "")),
            a.get("anime_type", ""),
            str(a.get("year", "")),
            a.get("season", "").title(),
            a.get("priority", "medium").upper(),
            a.get("franchise_name", ""),
            a.get("imported_at", datetime.utcnow()).strftime("%Y-%m-%d"),
        ])
    await _write(ws, rows)


async def sync_assigned() -> None:
    db = get_db()
    ws = await _get_or_create_tab(TABS["assigned"])
    rows = [["Title", "Assigned To", "Status", "Year", "Season", "Assigned At", "Expires At"]]
    async for a in db.assignments.find({"status": {"$in": ["assigned", "encoded", "leeched"]}}):
        anime = await db.anime.find_one({"anime_id": a["anime_id"]})
        user  = await db.users.find_one({"telegram_id": a["user_id"]})
        if anime:
            rows.append([
                anime["titles"].get("display_title", ""),
                f"@{user['username']}" if user and user.get("username") else str(a["user_id"]),
                a.get("status", "").title(),
                str(anime.get("year", "")),
                anime.get("season", "").title(),
                a.get("assigned_at", datetime.utcnow()).strftime("%Y-%m-%d %H:%M"),
                a.get("expires_at", datetime.utcnow()).strftime("%Y-%m-%d") if a.get("expires_at") else "",
            ])
    await _write(ws, rows)


async def sync_completed() -> None:
    db = get_db()
    ws = await _get_or_create_tab(TABS["completed"])
    rows = [["Title", "Completed By", "Year", "Season", "MAL ID", "Completed At"]]
    async for a in db.assignments.find({"status": "completed"}, sort=[("completed_at", -1)]).limit(2000):
        anime = await db.anime.find_one({"anime_id": a["anime_id"]})
        user  = await db.users.find_one({"telegram_id": a["user_id"]})
        if anime:
            rows.append([
                anime["titles"].get("display_title", ""),
                f"@{user['username']}" if user and user.get("username") else str(a["user_id"]),
                str(anime.get("year", "")),
                anime.get("season", "").title(),
                str(anime.get("mal_id", "")),
                a.get("completed_at", datetime.utcnow()).strftime("%Y-%m-%d") if a.get("completed_at") else "",
            ])
    await _write(ws, rows)


async def sync_dropped() -> None:
    db = get_db()
    ws = await _get_or_create_tab(TABS["dropped"])
    rows = [["Title", "Reason", "Dropped At"]]
    async for d in db.dropped.find({}, sort=[("date", -1)]):
        rows.append([
            d.get("title", ""),
            d.get("reason", ""),
            d.get("date", datetime.utcnow()).strftime("%Y-%m-%d") if d.get("date") else "",
        ])
    await _write(ws, rows)


async def sync_admin_stats() -> None:
    db = get_db()
    ws = await _get_or_create_tab(TABS["admin_stats"])
    rows = [["Username", "Completed", "Encoded", "Leeched", "Invalid", "Active Tasks"]]
    async for user in db.users.find({}, sort=[("completed_count", -1)]):
        rows.append([
            user.get("username") or user.get("full_name", ""),
            user.get("completed_count", 0),
            user.get("encoded_count", 0),
            user.get("leeched_count", 0),
            user.get("invalid_count", 0),
            user.get("active_task_count", 0),
        ])
    await _write(ws, rows)


async def sync_season_reports() -> None:
    db = get_db()
    ws = await _get_or_create_tab(TABS["season_reports"])
    pipeline = [
        {"$match": {"deleted": {"$ne": True}}},
        {"$group": {
            "_id": {"year": "$year", "season": "$season"},
            "total":     {"$sum": 1},
            "completed": {"$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}},
            "pending":   {"$sum": {"$cond": [{"$eq": ["$status", "pending"]}, 1, 0]}},
        }},
        {"$sort": {"_id.year": -1, "_id.season": 1}},
    ]
    rows = [["Year", "Season", "Total", "Completed", "Pending", "Completion %"]]
    async for row in db.anime.aggregate(pipeline):
        total     = row["total"]
        completed = row["completed"]
        pct = round(completed / total * 100, 1) if total else 0
        rows.append([
            row["_id"]["year"], row["_id"]["season"].title(),
            total, completed, row["pending"], f"{pct}%",
        ])
    await _write(ws, rows)


# ── gspread helpers (run in executor) ────────────────────────────────────

async def _get_client():
    import gspread
    from google.oauth2.service_account import Credentials
    creds_file = await get_str("sheets_credentials_file", "credentials.json")
    loop = asyncio.get_event_loop()
    def _sync():
        creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
        return gspread.authorize(creds)
    return await loop.run_in_executor(None, _sync)


async def _get_or_create_tab(name: str):
    import gspread
    sheet_id = await get_str("sheets_spreadsheet_id", "")
    if not sheet_id:
        raise RuntimeError("Sheets spreadsheet ID not configured. Use /panel → Sheets.")
    client = await _get_client()
    loop = asyncio.get_event_loop()
    def _sync():
        sh = client.open_by_key(sheet_id)
        try:
            return sh.worksheet(name)
        except gspread.WorksheetNotFound:
            return sh.add_worksheet(title=name, rows=2000, cols=20)
    return await loop.run_in_executor(None, _sync)


async def _write(ws, rows: list) -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, ws.clear)
    await loop.run_in_executor(None, partial(ws.update, "A1", rows))


async def _read_tab(tab_key: str) -> List[List[str]]:
    if not await is_enabled():
        return []
    tab_name = TABS.get(tab_key, tab_key)
    try:
        ws = await _get_or_create_tab(tab_name)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, ws.get_all_values)
    except Exception as exc:
        logger.warning("read_tab(%s) failed: %s", tab_key, exc)
        return []
