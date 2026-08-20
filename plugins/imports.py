"""
plugins/imports.py — /importseason /importyear

Review UI:
  After import, shows a paginated message (10 per page).
  Each entry has a numbered button [1]..[10].
  Clicking a button DROPS that entry into the dropped DB.
  Dropped entries show a ❌ prefix and their button disappears.
  [◀ Prev] [Page N/T] [Next ▶] navigation.
  [✅ Save Remaining] saves everything not yet dropped.
  [🗑 Drop All] drops everything.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from typing import Dict, List

from pyrogram import Client, filters
from pyrogram.types import (CallbackQuery, InlineKeyboardButton,
                             InlineKeyboardMarkup, Message)

from helper import dashboard, sheets
from helper.aliases import owner_only, rate_limited
from helper.importer import ImportStats, confirm_import, import_season, import_year
import database.dropped as dropped_db

logger   = logging.getLogger(__name__)
PAGE_SZ  = 10

# {user_id: {"items": [...], "dropped": set(), "label": str}}
_sessions: Dict[int, dict] = {}


# ── Commands ──────────────────────────────────────────────────────────────

@Client.on_message(filters.command("importseason"))
@owner_only
@rate_limited
async def cmd_importseason(app: Client, msg: Message):
    args    = [a for a in msg.command[1:] if a != "--preview"]
    preview = "--preview" in msg.command[1:]
    if len(args) < 2:
        await msg.reply("Usage: `/importseason Spring 2026 [--preview]`")
        return
    season = args[0].lower()
    try:
        year = int(args[1])
    except ValueError:
        await msg.reply("❌ Invalid year.")
        return
    if season not in ("winter", "spring", "summer", "fall"):
        await msg.reply("❌ Invalid season. Use: winter / spring / summer / fall")
        return

    status_msg = await msg.reply(f"⏳ Importing **{season.title()} {year}**…")
    try:
        stats, items = await import_season(year, season, preview=preview)
    except Exception as e:
        await status_msg.edit(f"❌ Import failed: {e}")
        return

    await status_msg.edit(_format_stats(stats, f"{season.title()} {year}", preview))

    if not preview and items:
        await _start_review(app, msg, items, f"{season.title()} {year}")


@Client.on_message(filters.command("importyear"))
@owner_only
@rate_limited
async def cmd_importyear(app: Client, msg: Message):
    args    = [a for a in msg.command[1:] if a != "--preview"]
    preview = "--preview" in msg.command[1:]
    if not args:
        await msg.reply("Usage: `/importyear 2026 [--preview]`")
        return
    try:
        year = int(args[0])
    except ValueError:
        await msg.reply("❌ Invalid year.")
        return

    status_msg = await msg.reply(f"⏳ Importing all seasons for **{year}**…")
    try:
        stats, items = await import_year(year, preview=preview)
    except Exception as e:
        await status_msg.edit(f"❌ Import failed: {e}")
        return

    await status_msg.edit(_format_stats(stats, f"All Seasons {year}", preview))

    if not preview and items:
        await _start_review(app, msg, items, f"All Seasons {year}")


# ── Review session starter ────────────────────────────────────────────────

async def _start_review(app: Client, msg: Message, items: list, label: str):
    uid = msg.from_user.id
    _sessions[uid] = {
        "items":   items,
        "dropped": set(),   # anime_ids dropped by user
        "label":   label,
    }
    text, kb = _build_page(uid, page=0)
    await msg.reply(text, reply_markup=kb)


# ── Callbacks ─────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^ir_"))
async def cb_import_review(app: Client, query: CallbackQuery):
    try:
        await query.answer()
        uid  = query.from_user.id
        data = query.data  # ir_<action>_<uid>_<extra>

        parts = data.split("_")
        # parts[0] = "ir", parts[1] = action, parts[2] = owner_uid, parts[3+] = extra

        if len(parts) < 3:
            return

        action    = parts[1]
        owner_uid = int(parts[2])

        # Only the owner who started the import can interact
        if uid != owner_uid:
            await query.answer("❌ Not your import session.", show_alert=True)
            return

        sess = _sessions.get(owner_uid)
        if not sess:
            await query.edit_message_text("⚠️ Session expired. Run /importseason again.")
            return

        # ── Drop single entry ──────────────────────────────────────────────
        if action == "drop" and len(parts) >= 4:
            anime_id = parts[3]
            item     = next((i for i in sess["items"] if i["anime_id"] == anime_id), None)
            if item and anime_id not in sess["dropped"]:
                sess["dropped"].add(anime_id)
                # Save to dropped DB immediately
                await dropped_db.add(
                    anime_id=anime_id,
                    title=item["titles"]["display_title"],
                    reason="import_review_drop",
                    dropped_by=uid,
                    original_data=item,
                )
            page = int(parts[4]) if len(parts) >= 5 else 0
            text, kb = _build_page(owner_uid, page)
            await query.edit_message_text(text, reply_markup=kb)

        # ── Navigate pages ─────────────────────────────────────────────────
        elif action == "page" and len(parts) >= 4:
            page     = int(parts[3])
            text, kb = _build_page(owner_uid, page)
            await query.edit_message_text(text, reply_markup=kb)

        # ── Save remaining (not dropped) ───────────────────────────────────
        elif action == "save":
            items   = sess["items"]
            dropped = sess["dropped"]
            keep    = [i for i in items if i["anime_id"] not in dropped]
            _sessions.pop(owner_uid, None)

            if not keep:
                await query.edit_message_text("⚠️ No entries to save — all were dropped.")
                return

            saving_msg = await query.edit_message_text(
                f"💾 Saving **{len(keep)}** anime…"
            )
            saved = await confirm_import(keep, [i["anime_id"] for i in keep])
            await dashboard.update_all(app)
            await dashboard.log_event(
                app,
                f"📥 Import confirmed: **{saved}** anime saved, "
                f"**{len(dropped)}** dropped by @{query.from_user.username}",
            )
            await sheets.sync_pending()
            for anime in keep:
                await dashboard.upsert_anime_message(app, anime)
            await query.edit_message_text(
                f"✅ **Import complete!**\n\n"
                f"• Saved: **{saved}**\n"
                f"• Dropped: **{len(dropped)}**"
            )

        # ── Drop all ───────────────────────────────────────────────────────
        elif action == "dropall":
            items = sess["items"]
            _sessions.pop(owner_uid, None)
            for item in items:
                if item["anime_id"] not in sess["dropped"]:
                    await dropped_db.add(
                        anime_id=item["anime_id"],
                        title=item["titles"]["display_title"],
                        reason="import_drop_all",
                        dropped_by=uid,
                        original_data=item,
                    )
            await query.edit_message_text(
                f"🗑 **All {len(items)} entries dropped.** Nothing saved."
            )

        # ── Noop (page indicator button) ───────────────────────────────────
        elif action == "noop":
            pass

    except Exception as e:
        logger.exception("cb_import_review error: %s", e)


# ── Page builder ──────────────────────────────────────────────────────────

def _build_page(uid: int, page: int) -> tuple:
    sess        = _sessions.get(uid, {})
    items       = sess.get("items", [])
    dropped_ids = sess.get("dropped", set())
    label       = sess.get("label", "Import")

    total       = len(items)
    kept        = total - len(dropped_ids)
    total_pages = max(1, (total + PAGE_SZ - 1) // PAGE_SZ)
    page        = max(0, min(page, total_pages - 1))
    start       = page * PAGE_SZ
    page_items  = items[start: start + PAGE_SZ]

    # ── Text ──────────────────────────────────────────────────────────────
    lines = [
        f"📥 **Import Review: {label}**",
        f"━━━━━━━━━━━━━━━━━━━",
        f"Total: **{total}**  ·  Kept: **{kept}**  ·  Dropped: **{len(dropped_ids)}**",
        f"Page {page + 1}/{total_pages}",
        "",
    ]
    for i, item in enumerate(page_items, start=start + 1):
        aid     = item["anime_id"]
        title   = item["titles"]["display_title"]
        ep      = item.get("episode_count") or "?"
        fmt     = item.get("anime_type", "TV")
        country = item.get("country", "")
        dh_tag  = " 🇨🇳" if country == "CN" else ""
        if aid in dropped_ids:
            lines.append(f"~~{i}. {title}~~ ❌ dropped")
        else:
            lines.append(f"`{i}.` **{title}**  _{fmt} · {ep}ep{dh_tag}_")

    text = "\n".join(lines)

    # ── Keyboard ──────────────────────────────────────────────────────────
    buttons = []

    # Drop buttons — 5 per row, 2 rows max (10 per page)
    drop_row_1, drop_row_2 = [], []
    for i, item in enumerate(page_items):
        aid     = item["anime_id"]
        abs_num = start + i + 1
        if aid in dropped_ids:
            continue  # already dropped — no button
        btn = InlineKeyboardButton(
            str(abs_num),
            callback_data=f"ir_drop_{uid}_{aid}_{page}",
        )
        if len(drop_row_1) < 5:
            drop_row_1.append(btn)
        else:
            drop_row_2.append(btn)

    if drop_row_1:
        buttons.append(drop_row_1)
    if drop_row_2:
        buttons.append(drop_row_2)

    # Navigation row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀", callback_data=f"ir_page_{uid}_{page - 1}"))
    nav.append(InlineKeyboardButton(f"{page + 1}/{total_pages}", callback_data=f"ir_noop_{uid}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶", callback_data=f"ir_page_{uid}_{page + 1}"))
    if nav:
        buttons.append(nav)

    # Action row
    buttons.append([
        InlineKeyboardButton(f"✅ Save {kept} Remaining", callback_data=f"ir_save_{uid}"),
        InlineKeyboardButton("🗑 Drop All",               callback_data=f"ir_dropall_{uid}"),
    ])

    return text, InlineKeyboardMarkup(buttons)


# ── Stats formatter ───────────────────────────────────────────────────────

def _format_stats(stats: ImportStats, label: str, preview: bool) -> str:
    mode = "📋 PREVIEW" if preview else "📥 IMPORT"
    dups = "\n".join(
        f"  • {d.get('al_id','?')} — {d.get('title','?')}: `{d['reason']}`"
        for d in stats.duplicate_reasons[:5]
    ) or "  None"
    ign = "\n".join(
        f"  • {d.get('al_id','?')} — {d.get('title','?')}: `{d['reason']}`"
        for d in stats.ignored_reasons[:5]
    ) or "  None"
    return (
        f"{mode}: **{label}**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Total Found:  **{stats.total_found}**\n"
        f"🆕 New:         **{stats.new}**\n"
        f"🔁 Duplicates:  **{stats.duplicates}**\n"
        f"🚫 Ignored:     **{stats.ignored}**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"**Duplicates (first 5):**\n{dups}\n\n"
        f"**Ignored (first 5):**\n{ign}"
    )
