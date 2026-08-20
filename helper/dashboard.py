"""helper/dashboard.py — Dashboard channel update logic."""
from __future__ import annotations
import logging
from datetime import datetime
from typing import Dict, Optional

from pyrogram import Client

from database.mongo import get_db
from database.settings import get as cfg_get
import helper.stats as stats_helper

logger = logging.getLogger(__name__)

DASH_KEY_GLOBAL      = "dashboard_msg_global"
DASH_KEY_TASKS       = "dashboard_msg_tasks"
DASH_KEY_COMPLETIONS = "dashboard_msg_completions"
DASH_KEY_INVALID     = "dashboard_msg_invalid"


async def _channel() -> Optional[int]:
    val = await cfg_get("dashboard_channel")
    return int(val) if val else None


async def rebuild(app: Client) -> None:
    ch = await _channel()
    if not ch:
        raise RuntimeError("Dashboard channel not configured. Use /setdashboard.")
    for key, renderer in _renderers():
        text = await renderer()
        await _init_message(app, ch, key, text)
    logger.info("Dashboard rebuilt")


async def update_all(app: Client) -> None:
    ch = await _channel()
    if not ch:
        return
    for key, renderer in _renderers():
        try:
            text = await renderer()
            await _update_message(app, ch, key, text)
        except Exception as e:
            logger.warning("Dashboard update for %s failed: %s", key, e)


async def upsert_anime_message(app: Client, anime: Dict) -> None:
    ch = await _channel()
    if not ch:
        return
    db   = get_db()
    text = _render_anime_card(anime)
    tracker = await db.telegram_messages.find_one({"anime_id": anime["anime_id"]})

    if tracker:
        try:
            await app.edit_message_text(ch, tracker["message_id"], text)
            await db.telegram_messages.update_one(
                {"anime_id": anime["anime_id"]},
                {"$set": {"updated_at": datetime.utcnow()}},
            )
            return
        except Exception:
            pass

    msg = await app.send_message(ch, text)
    await db.telegram_messages.update_one(
        {"anime_id": anime["anime_id"]},
        {"$set": {
            "anime_id":    anime["anime_id"],
            "message_id":  msg.id,
            "channel_id":  ch,
            "message_type": "tracking",
            "created_at":  datetime.utcnow(),
            "updated_at":  datetime.utcnow(),
        }},
        upsert=True,
    )


async def log_event(app: Client, message: str) -> None:
    val = await cfg_get("log_channel")
    if not val:
        return
    try:
        await app.send_message(int(val), message)
    except Exception as e:
        logger.warning("Log channel send failed: %s", e)


# ── Internal ──────────────────────────────────────────────────────────────

def _renderers():
    return [
        (DASH_KEY_GLOBAL,      _render_global),
        (DASH_KEY_TASKS,       _render_tasks),
        (DASH_KEY_COMPLETIONS, _render_completions),
        (DASH_KEY_INVALID,     _render_invalid),
    ]


async def _init_message(app: Client, ch: int, key: str, text: str) -> None:
    db = get_db()
    tracker = await db.config.find_one({"key": key})
    if tracker and tracker.get("value"):
        try:
            await app.edit_message_text(ch, tracker["value"], text)
            return
        except Exception:
            pass
    msg = await app.send_message(ch, text)
    await db.config.update_one(
        {"key": key},
        {"$set": {"value": msg.id, "updated_at": datetime.utcnow(),
                  "category": "internal", "type": "int"}},
        upsert=True,
    )
    try:
        await app.pin_message(ch, msg.id)
    except Exception:
        pass


async def _update_message(app: Client, ch: int, key: str, text: str) -> None:
    db = get_db()
    tracker = await db.config.find_one({"key": key})
    if not tracker or not tracker.get("value"):
        await _init_message(app, ch, key, text)
        return
    try:
        await app.edit_message_text(ch, tracker["value"], text)
    except Exception as e:
        if "MESSAGE_NOT_MODIFIED" not in str(e):
            await _init_message(app, ch, key, text)


async def _render_global() -> str:
    s = await stats_helper.global_stats()
    lb = await stats_helper.leaderboard(5)
    top = "\n".join(
        f"  {i+1}. @{u['username']} — {u['completed']} ✅"
        for i, u in enumerate(lb)
    ) or "  No completions yet."
    bk = s["last_backup"].strftime("%Y-%m-%d %H:%M UTC") if s["last_backup"] else "Never"
    return (
        "📊 **GLOBAL DASHBOARD**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Total:       **{s['total']}**\n\n"
        f"⏳ Pending:     **{s['pending']}**\n"
        f"🎯 Assigned:    **{s['assigned']}**\n"
        f"📤 Encoded:     **{s['encoded']}**\n"
        f"🔗 Leeched:     **{s['leeched']}**\n"
        f"✅ Completed:   **{s['completed']}**\n"
        f"❌ Dropped:     **{s['dropped']}**\n"
        f"⚠️  Invalid:     **{s['invalid']}**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 **Top Admins**\n{top}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💾 Last Backup: {bk}\n"
        f"🕐 Updated: {datetime.utcnow().strftime('%H:%M UTC')}"
    )


async def _render_tasks() -> str:
    board = await stats_helper.active_tasks_board()
    if not board:
        return "📋 **ACTIVE TASKS BOARD**\n\nNo active assignments."
    rows = "".join(
        f"  @{e['username']} — {e['task_count']} tasks | "
        f"{e['last_active'].strftime('%m-%d %H:%M') if e['last_active'] else '—'}\n"
        for e in board[:15]
    )
    return (
        f"📋 **ACTIVE TASKS BOARD**\n"
        f"━━━━━━━━━━━━━━━━━━━\n{rows}"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {datetime.utcnow().strftime('%H:%M UTC')}"
    )


async def _render_completions() -> str:
    completions = await stats_helper.recent_completions(10)
    if not completions:
        return "🏁 **RECENT COMPLETIONS**\n\nNo completions yet."
    rows = "".join(
        f"  ✅ {c['title'][:40]} — @{c['completed_by']} "
        f"({c['completed_at'].strftime('%m-%d') if c.get('completed_at') else '—'})\n"
        for c in completions
    )
    return (
        f"🏁 **RECENT COMPLETIONS**\n"
        f"━━━━━━━━━━━━━━━━━━━\n{rows}"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🕐 {datetime.utcnow().strftime('%H:%M UTC')}"
    )


async def _render_invalid() -> str:
    queue = await stats_helper.invalid_queue()
    if not queue:
        return "⚠️ **INVALID / REVIEW QUEUE**\n\nNothing to review. ✨"
    rows = "\n".join(
        f"  ⚠️ {a['title'][:40]} ({a['year']} {a['season'].title()})"
        for a in queue
    )
    return (
        f"⚠️ **INVALID / REVIEW QUEUE**\n"
        f"━━━━━━━━━━━━━━━━━━━\n{rows}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"Total: {len(queue)} | 🕐 {datetime.utcnow().strftime('%H:%M UTC')}"
    )


def _render_anime_card(anime: Dict) -> str:
    emoji = {
        "pending": "⏳", "assigned": "🎯", "encoded": "📤",
        "leeched": "🔗", "completed": "✅", "invalid": "⚠️", "dropped": "❌",
    }.get(anime.get("status", ""), "❓")
    title   = anime["titles"].get("display_title", "Unknown")
    mal_url = anime.get("mal_url", "")
    link    = f"[{title}]({mal_url})" if mal_url else f"**{title}**"
    return (
        f"🎬 {link}\n"
        f"📅 {anime.get('year', '?')} {anime.get('season', '').title()}\n"
        f"🎭 {anime.get('anime_type', 'TV')}\n"
        f"{emoji} Status: **{anime.get('status', 'pending').title()}**\n"
        f"🆔 `{anime.get('anime_id', '')[:8]}`"
    )
