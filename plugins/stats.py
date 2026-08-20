"""
plugins/stats.py — /stats /userstats

/stats navigation:
  1. Season picker: [Spring][Summer][Fall][Winter][All]
  2. Year picker:   [2026][2025][2024]…
  3. Paginated list of anime in that season/year
"""
from __future__ import annotations
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import (CallbackQuery, InlineKeyboardButton,
                             InlineKeyboardMarkup, Message)
from helper.aliases import admin_or_owner, owner_only, rate_limited

logger  = logging.getLogger(__name__)
PAGE_SZ = 10
STATUS_EMOJI = {
    "pending": "⏳", "assigned": "🔄", "completed": "✅",
    "encoded": "📦", "leeched": "🔗", "dropped": "🗑️", "invalid": "⚠️",
}
SEASONS = ["spring", "summer", "fall", "winter"]


# ── /stats entry point ─────────────────────────────────────────────────────

@Client.on_message(filters.command("stats"))
@owner_only
@rate_limited
async def cmd_stats(app: Client, msg: Message):
    try:
        text, kb = await _season_menu()
        await msg.reply(text, reply_markup=kb)
    except Exception as e:
        logger.exception("/stats error")
        await msg.reply(f"⚠️ `{e}`")


# ── Callbacks ──────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^st_"))
async def cb_stats(app: Client, query: CallbackQuery):
    try:
        await query.answer()
        parts = query.data.split("_")   # st_<action>_...
        action = parts[1]

        if action == "season":
            text, kb = await _season_menu()
            await query.edit_message_text(text, reply_markup=kb)

        elif action == "year":
            season = parts[2]           # st_year_spring
            text, kb = await _year_menu(season)
            await query.edit_message_text(text, reply_markup=kb)

        elif action == "list":
            season = parts[2]           # st_list_spring_2026_0
            year   = int(parts[3])
            page   = int(parts[4])
            text, kb = await _list_page(season, year, page)
            await query.edit_message_text(text, reply_markup=kb)

        elif action == "noop":
            pass

    except Exception as e:
        logger.exception("cb_stats error: %s", e)


# ── Menu builders ──────────────────────────────────────────────────────────

async def _season_menu() -> tuple:
    db    = get_db()
    total = await db.anime.count_documents({"deleted": {"$ne": True}})
    text  = f"📊 **Statistics** — {total} total anime\n\nPick a season:"
    rows  = []
    row   = []
    for s in SEASONS:
        count = await db.anime.count_documents({"season": s, "deleted": {"$ne": True}})
        row.append(InlineKeyboardButton(
            f"{s.title()} ({count})", callback_data=f"st_year_{s}"
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("📋 All Seasons", callback_data="st_list_all_0_0")])
    return text, InlineKeyboardMarkup(rows)


async def _year_menu(season: str) -> tuple:
    db = get_db()
    # Get distinct years for this season
    years = await asyncio.to_thread(
        lambda: sorted(set(
            doc["year"] for doc in get_db()._db["anime"].find(
                {"season": season, "deleted": {"$ne": True}},
                {"year": 1}
            )
            if isinstance(doc.get("year"), int)
        ), reverse=True)
    )

    if not years:
        return (f"No anime found for **{season.title()}**.", None)

    text = f"📊 **{season.title()}** — Pick a year:"
    rows = []
    row  = []
    for yr in years:
        count = await db.anime.count_documents(
            {"season": season, "year": yr, "deleted": {"$ne": True}}
        )
        row.append(InlineKeyboardButton(
            f"{yr} ({count})", callback_data=f"st_list_{season}_{yr}_0"
        ))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="st_season")])
    return text, InlineKeyboardMarkup(rows)


async def _list_page(season: str, year: int, page: int) -> tuple:
    db = get_db()

    # Build filter
    filt: dict = {"deleted": {"$ne": True}}
    if season != "all":
        filt["season"] = season
    if year != 0:
        filt["year"] = year

    total       = await db.anime.count_documents(filt)
    total_pages = max(1, (total + PAGE_SZ - 1) // PAGE_SZ)
    page        = max(0, min(page, total_pages - 1))
    skip        = page * PAGE_SZ

    docs = await asyncio.to_thread(
        lambda: list(
            get_db()._db["anime"]
            .find(filt, {"anime_id": 1, "titles": 1, "status": 1,
                         "season": 1, "year": 1, "anilist_id": 1})
            .sort([("year", -1), ("season", 1), ("imported_at", -1)])
            .skip(skip)
            .limit(PAGE_SZ)
        )
    )

    label = f"{season.title()} {year}" if year else season.title()
    if season == "all":
        label = "All Seasons"

    lines = [f"📊 **{label}** `({total} anime)`\n"]
    for i, doc in enumerate(docs, start=skip + 1):
        titles = doc.get("titles") or {}
        title  = titles.get("display_title", "Unknown")
        status = doc.get("status", "pending")
        emoji  = STATUS_EMOJI.get(status, "•")
        al_id  = doc.get("anilist_id") or "—"
        sid    = (doc.get("season") or "?").title()[:3]
        yr     = doc.get("year", "?")
        aid    = doc["anime_id"][:8]
        lines.append(
            f"`{i}.` {emoji} **{title}**\n"
            f"    `{aid}` · AL:`{al_id}` · {sid} {yr}"
        )

    text = "\n".join(lines)
    text += f"\n\n_Page {page + 1}/{total_pages}_"

    # Navigation
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"st_list_{season}_{year}_{page-1}"))
    nav.append(InlineKeyboardButton(f"{page+1}/{total_pages}", callback_data="st_noop"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"st_list_{season}_{year}_{page+1}"))

    rows = []
    if nav:
        rows.append(nav)

    # Back button
    back = f"st_year_{season}" if season != "all" else "st_season"
    rows.append([InlineKeyboardButton("🔙 Back", callback_data=back)])

    return text, InlineKeyboardMarkup(rows)


def get_db():
    from database.mongo import get_db as _get
    return _get()


# ── /userstats ─────────────────────────────────────────────────────────────

@Client.on_message(filters.command("userstats"))
@admin_or_owner
@rate_limited
async def cmd_userstats(app: Client, msg: Message):
    try:
        db    = get_db()
        uid   = msg.from_user.id
        total = await db.assignments.count_documents({"user_id": uid})
        done  = await db.assignments.count_documents({"user_id": uid, "status": "completed"})
        wip   = await db.assignments.count_documents(
            {"user_id": uid, "status": {"$in": ["assigned", "encoded", "leeched"]}}
        )
        rate = round(done / total * 100) if total else 0
        await msg.reply(
            f"📊 **Your Statistics**\n\n"
            f"Total Assignments: **{total}**\n"
            f"Completed:         **{done}**\n"
            f"In Progress:       **{wip}**\n"
            f"Success Rate:      **{rate}%**"
        )
    except Exception as e:
        logger.exception("/userstats error")
        await msg.reply(f"⚠️ `{e}`")
