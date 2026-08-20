"""
plugins/drops.py
Commands: /dropanime /restoreanime /dropped /deleteanime
          /dropseason /deleteseason /reassignseason /restoreseason /exportseason
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

import database.logs as logs_db
from database.mongo import get_db
from database.settings import get as cfg_get, get_bool
from helper import dashboard
from helper.aliases import owner_only, rate_limited
from helper.sheets import full_sync as sheets_full_sync, is_enabled as sheets_on

logger = logging.getLogger(__name__)


# ── /dropanime ────────────────────────────────────────────────────────────

@Client.on_message(filters.command("dropanime"))
@owner_only
@rate_limited
async def cmd_dropanime(app: Client, msg: Message):
    """/dropanime <anime_id> [reason]"""
    args = msg.command[1:]
    if not args:
        await msg.reply(
            "Usage: `/dropanime <anime_id> [reason]`\n"
            "Example: `/dropanime abc12345 No subtitles available`"
        )
        return

    anime_id = args[0]
    reason   = " ".join(args[1:]) if len(args) > 1 else "Manually dropped"
    db       = get_db()
    anime    = await db.anime.find_one({"anime_id": anime_id, "deleted": {"$ne": True}})
    if not anime:
        await msg.reply("❌ Anime not found.")
        return

    now   = datetime.utcnow()
    title = anime["titles"].get("display_title", "Unknown")

    await db.anime.update_one(
        {"anime_id": anime_id},
        {"$set": {"status": "dropped", "updated_at": now}},
    )
    await db.dropped.update_one(
        {"anime_id": anime_id},
        {"$set": {
            "anime_id":     anime_id,
            "title":        title,
            "reason":       reason,
            "dropped_by":   msg.from_user.id,
            "date":         now,
            "original_data": anime,
        }},
        upsert=True,
    )

    # Release franchise lock
    if anime.get("franchise_id"):
        from database.franchises import set_lock
        await set_lock(anime["franchise_id"], False)

    await logs_db.log_audit(str(msg.from_user.id), "dropped", target=anime_id, new_value=reason)

    updated = await db.anime.find_one({"anime_id": anime_id})
    if updated:
        await dashboard.upsert_anime_message(app, updated)
    await dashboard.update_all(app)
    await dashboard.log_event(app, f"❌ **Dropped:** {title}\n📝 Reason: {reason}")

    from helper.sheets import sync_dropped
    await sync_dropped()

    await msg.reply(f"❌ Dropped: **{title}**\nReason: {reason}")


# ── /restoreanime ─────────────────────────────────────────────────────────

@Client.on_message(filters.command("restoreanime"))
@owner_only
@rate_limited
async def cmd_restoreanime(app: Client, msg: Message):
    """/restoreanime <anime_id>"""
    args = msg.command[1:]
    if not args:
        await msg.reply("Usage: `/restoreanime <anime_id>`")
        return

    anime_id = args[0]
    db       = get_db()
    dropped  = await db.dropped.find_one({"anime_id": anime_id})
    anime    = await db.anime.find_one({"anime_id": anime_id})

    if not anime and not dropped:
        await msg.reply("❌ Anime not found.")
        return

    now = datetime.utcnow()
    await db.anime.update_one(
        {"anime_id": anime_id},
        {"$set": {"status": "pending", "deleted": False, "updated_at": now}},
    )
    if dropped:
        await db.dropped.delete_one({"anime_id": anime_id})

    title = (
        (dropped or {}).get("title")
        or ((anime or {}).get("titles") or {}).get("display_title", anime_id)
    )

    await logs_db.log_audit(str(msg.from_user.id), "restored", target=anime_id)

    restored = await db.anime.find_one({"anime_id": anime_id})
    if restored:
        await dashboard.upsert_anime_message(app, restored)
    await dashboard.update_all(app)
    await dashboard.log_event(app, f"♻️ **Restored:** {title}")

    from helper.sheets import sync_pending
    await sync_pending()

    await msg.reply(f"♻️ Restored: **{title}**")


# ── /dropped ──────────────────────────────────────────────────────────────

@Client.on_message(filters.command("dropped"))
@owner_only
@rate_limited
async def cmd_dropped(app: Client, msg: Message):
    """List the 20 most recently dropped anime."""
    db    = get_db()
    lines = []
    async for d in db.dropped.find({}, sort=[("date", -1)]).limit(20):
        date = d.get("date", datetime.utcnow()).strftime("%m-%d")
        lines.append(
            f"❌ **{d.get('title', '?')[:40]}**\n"
            f"   Reason: {d.get('reason', '?')[:50]} ({date})\n"
            f"   ID: `{d.get('anime_id', '')}`"
        )

    if not lines:
        await msg.reply("✅ No dropped anime.")
        return

    count = await db.dropped.count_documents({})
    await msg.reply(
        f"❌ **Dropped Anime ({count} total, latest 20)**\n\n" + "\n\n".join(lines)
    )


# ── /deleteanime ──────────────────────────────────────────────────────────

@Client.on_message(filters.command("deleteanime"))
@owner_only
@rate_limited
async def cmd_deleteanime(app: Client, msg: Message):
    """/deleteanime <anime_id> confirm — soft delete"""
    args = msg.command[1:]
    if len(args) < 2 or args[1].lower() != "confirm":
        await msg.reply(
            "Usage: `/deleteanime <anime_id> confirm`\n"
            "⚠️ This is a soft delete. Use /restoreanime to undo."
        )
        return

    anime_id = args[0]
    db       = get_db()
    anime    = await db.anime.find_one({"anime_id": anime_id})
    if not anime:
        await msg.reply("❌ Anime not found.")
        return

    title = anime["titles"].get("display_title", "Unknown")
    await db.anime.update_one(
        {"anime_id": anime_id},
        {"$set": {"deleted": True, "deleted_at": datetime.utcnow()}},
    )
    await logs_db.log_audit(str(msg.from_user.id), "soft_deleted", target=anime_id)

    await dashboard.update_all(app)
    await msg.reply(
        f"🗑️ Soft-deleted: **{title}**\n"
        f"Use `/restoreanime {anime_id}` to undo."
    )


# ── /dropseason ───────────────────────────────────────────────────────────

@Client.on_message(filters.command("dropseason"))
@owner_only
@rate_limited
async def cmd_dropseason(app: Client, msg: Message):
    """/dropseason <Season> <Year> — drop all pending in a season"""
    args = msg.command[1:]
    if len(args) < 2:
        await msg.reply("Usage: `/dropseason Spring 2024`")
        return
    season = args[0].lower()
    try:
        year = int(args[1])
    except ValueError:
        await msg.reply("❌ Invalid year.")
        return

    db      = get_db()
    now     = datetime.utcnow()
    pending = [a async for a in db.anime.find(
        {"season": season, "year": year, "status": "pending", "deleted": {"$ne": True}}
    )]
    if not pending:
        await msg.reply(f"No pending anime in {season.title()} {year}.")
        return

    for anime in pending:
        await db.anime.update_one(
            {"anime_id": anime["anime_id"]},
            {"$set": {"status": "dropped", "updated_at": now}},
        )
        await db.dropped.update_one(
            {"anime_id": anime["anime_id"]},
            {"$set": {
                "anime_id":   anime["anime_id"],
                "title":      anime["titles"].get("display_title", "Unknown"),
                "reason":     f"Season drop: {season.title()} {year}",
                "dropped_by": msg.from_user.id,
                "date":       now,
                "original_data": anime,
            }},
            upsert=True,
        )

    await logs_db.log_audit(
        str(msg.from_user.id), "season_dropped",
        target=f"{season}_{year}", new_value=str(len(pending)),
    )
    await dashboard.update_all(app)
    await dashboard.log_event(
        app, f"❌ **Season Drop:** {season.title()} {year} — {len(pending)} anime dropped"
    )
    from helper.sheets import sync_dropped
    await sync_dropped()

    await msg.reply(f"❌ Dropped **{len(pending)}** anime from **{season.title()} {year}**.")


# ── /deleteseason ─────────────────────────────────────────────────────────

@Client.on_message(filters.command("deleteseason"))
@owner_only
@rate_limited
async def cmd_deleteseason(app: Client, msg: Message):
    """/deleteseason <Season> <Year> confirm"""
    args = msg.command[1:]
    if len(args) < 3 or args[2].lower() != "confirm":
        await msg.reply(
            "Usage: `/deleteseason Spring 2024 confirm`\n"
            "⚠️ Soft-deletes ALL anime in the season."
        )
        return
    season = args[0].lower()
    try:
        year = int(args[1])
    except ValueError:
        await msg.reply("❌ Invalid year.")
        return

    db  = get_db()
    res = await db.anime.update_many(
        {"season": season, "year": year, "deleted": {"$ne": True}},
        {"$set": {"deleted": True, "deleted_at": datetime.utcnow()}},
    )
    await logs_db.log_audit(
        str(msg.from_user.id), "season_deleted",
        target=f"{season}_{year}", new_value=str(res.modified_count),
    )
    await dashboard.update_all(app)
    await dashboard.log_event(
        app,
        f"🗑️ **Season Delete:** {season.title()} {year} — {res.modified_count} soft-deleted"
    )
    await msg.reply(
        f"🗑️ Soft-deleted **{res.modified_count}** anime from **{season.title()} {year}**.\n"
        f"Use `/restoreseason {season.title()} {year}` to undo."
    )


# ── /reassignseason ───────────────────────────────────────────────────────

@Client.on_message(filters.command("reassignseason"))
@owner_only
@rate_limited
async def cmd_reassignseason(app: Client, msg: Message):
    """/reassignseason <Season> <Year> — return assigned anime to pool"""
    args = msg.command[1:]
    if len(args) < 2:
        await msg.reply("Usage: `/reassignseason Spring 2024`")
        return
    season = args[0].lower()
    try:
        year = int(args[1])
    except ValueError:
        await msg.reply("❌ Invalid year.")
        return

    db    = get_db()
    count = 0
    from helper.assignment import _unassign

    async for anime in db.anime.find({
        "season": season, "year": year,
        "status": {"$in": ["assigned", "encoded", "leeched"]},
    }):
        await _unassign(anime["anime_id"])
        count += 1

    await dashboard.update_all(app)
    await dashboard.log_event(
        app, f"🔄 **Season Reassign:** {season.title()} {year} — {count} anime returned to pool"
    )
    await msg.reply(
        f"🔄 Returned **{count}** anime from **{season.title()} {year}** back to the pool."
    )


# ── /restoreseason ────────────────────────────────────────────────────────

@Client.on_message(filters.command("restoreseason"))
@owner_only
@rate_limited
async def cmd_restoreseason(app: Client, msg: Message):
    """/restoreseason <Season> <Year>"""
    args = msg.command[1:]
    if len(args) < 2:
        await msg.reply("Usage: `/restoreseason Spring 2024`")
        return
    season = args[0].lower()
    try:
        year = int(args[1])
    except ValueError:
        await msg.reply("❌ Invalid year.")
        return

    db  = get_db()
    now = datetime.utcnow()

    soft = await db.anime.update_many(
        {"season": season, "year": year, "deleted": True},
        {"$set": {"deleted": False, "status": "pending", "updated_at": now}},
    )

    # Restore from dropped collection
    from_dropped = 0
    async for d in db.dropped.find({}):
        orig = d.get("original_data", {})
        if orig.get("season") == season and orig.get("year") == year:
            await db.anime.update_one(
                {"anime_id": d["anime_id"]},
                {"$set": {"status": "pending", "deleted": False, "updated_at": now}},
            )
            await db.dropped.delete_one({"anime_id": d["anime_id"]})
            from_dropped += 1

    total = soft.modified_count + from_dropped
    await logs_db.log_audit(
        str(msg.from_user.id), "season_restored",
        target=f"{season}_{year}", new_value=str(total),
    )
    await dashboard.update_all(app)
    await dashboard.log_event(
        app, f"♻️ **Season Restore:** {season.title()} {year} — {total} anime restored"
    )
    from helper.sheets import sync_pending
    await sync_pending()

    await msg.reply(
        f"♻️ Restored **{total}** anime from **{season.title()} {year}** back to pending."
    )


# ── /exportseason ─────────────────────────────────────────────────────────

@Client.on_message(filters.command("exportseason"))
@owner_only
@rate_limited
async def cmd_exportseason(app: Client, msg: Message):
    """/exportseason <Season> <Year>"""
    args = msg.command[1:]
    if len(args) < 2:
        await msg.reply("Usage: `/exportseason Spring 2024`")
        return
    season = args[0].lower()
    try:
        year = int(args[1])
    except ValueError:
        await msg.reply("❌ Invalid year.")
        return

    status_msg = await msg.reply(f"⏳ Exporting {season.title()} {year}…")

    if not await sheets_on():
        await status_msg.edit(
            "❌ Google Sheets is disabled.\n"
            "Enable with: `/set sheets_enabled on`"
        )
        return

    try:
        from helper.sheets import _get_or_create_tab, _write
        import asyncio as _asyncio

        db       = get_db()
        tab_name = f"{season.title()} {year}"
        ws       = await _get_or_create_tab(tab_name)

        rows = [["Title", "MAL ID", "Type", "Status", "Priority", "Assigned To", "Franchise", "Imported At"]]
        async for anime in db.anime.find({"season": season, "year": year, "deleted": {"$ne": True}}):
            assignee   = ""
            assignment = await db.assignments.find_one(
                {"anime_id": anime["anime_id"],
                 "status": {"$nin": ["completed", "dropped", "expired"]}},
                sort=[("assigned_at", -1)],
            )
            if assignment:
                user     = await db.users.find_one({"telegram_id": assignment["user_id"]})
                assignee = f"@{user['username']}" if user and user.get("username") else str(assignment["user_id"])

            rows.append([
                anime["titles"].get("display_title", ""),
                str(anime.get("mal_id", "")),
                anime.get("anime_type", ""),
                anime.get("status", "").title(),
                anime.get("priority", "medium").upper(),
                assignee,
                anime.get("franchise_name", ""),
                anime.get("imported_at", now := datetime.utcnow()).strftime("%Y-%m-%d"),
            ])

        await _write(ws, rows)
        count = len(rows) - 1

        send_link = await get_bool("sheets_send_link_on_export", True)
        from database.settings import get_str
        sheet_id  = await get_str("sheets_spreadsheet_id", "")
        sheet_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}" if sheet_id else None

        kb = None
        if send_link and sheet_url:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(f"📊 Open {tab_name}", url=sheet_url)
            ]])

        await status_msg.edit(
            f"✅ Exported **{count}** anime from **{season.title()} {year}** → `{tab_name}` tab.",
            reply_markup=kb,
        )

        # Optional CSV to backup channel
        send_files = await get_bool("sheets_send_file_on_export", False)
        if send_files and count > 0:
            bk_ch = await cfg_get("backup_channel")
            if bk_ch:
                buf = io.StringIO()
                csv.writer(buf).writerows(rows)
                raw = buf.getvalue().encode("utf-8-sig")
                bio = io.BytesIO(raw)
                bio.name = f"{season}_{year}.csv"
                await app.send_document(
                    int(bk_ch), bio,
                    file_name=f"{season}_{year}.csv",
                    caption=f"📋 **{tab_name}** season export — {count} anime",
                )

    except Exception as e:
        await status_msg.edit(f"❌ Export failed: `{e}`")
        logger.exception("exportseason error")
