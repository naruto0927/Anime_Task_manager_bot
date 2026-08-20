"""
plugins/assignments.py
Commands: /nexttask /mytask /reserve /away /back

Task button behaviour:
  encoded / leeched  → edit msg in-place (remove that button, show updated status)
  completed / invalid / note → delete task msg, send confirmation
  toggle_donghua     → toggle setting, refresh keyboard
"""
from __future__ import annotations
import logging

from pyrogram import Client, filters
from pyrogram.types import (CallbackQuery, InlineKeyboardButton,
                             InlineKeyboardMarkup, Message)

import database.anime as anime_db
import database.assignments as assign_db
import database.logs as logs_db
import database.users as users_db
from helper import assignment as asn
from helper import dashboard, sheets
from helper.aliases import admin_or_owner, rate_limited
from helper.theme import SEP_BOLD, STATUS, task_card

logger = logging.getLogger(__name__)

# {user_id: anime_id}  — waiting for note text
_pending_notes: dict[int, str] = {}


# ── /nexttask ─────────────────────────────────────────────────────────────

@Client.on_message(filters.command("nexttask"))
@admin_or_owner
@rate_limited
async def cmd_nexttask(app: Client, msg: Message):
    await users_db.upsert_on_start(
        msg.from_user.id, msg.from_user.username or "", msg.from_user.full_name or ""
    )
    anime, error = await asn.assign_next(msg.from_user.id)
    if error:
        await msg.reply(f"ℹ️ {error}")
        return

    await msg.reply(
        task_card(anime),
        reply_markup=_task_kb(anime["anime_id"]),
        disable_web_page_preview=True,
    )
    await dashboard.upsert_anime_message(app, anime)
    await dashboard.update_all(app)
    await dashboard.log_event(
        app,
        f"🎯 **Assigned:** {anime['titles']['display_title']}\n"
        f"👤 → @{msg.from_user.username or msg.from_user.first_name}",
    )
    await sheets.sync_assigned()


# ── /mytask ───────────────────────────────────────────────────────────────

@Client.on_message(filters.command("mytask"))
@admin_or_owner
@rate_limited
async def cmd_mytask(app: Client, msg: Message):
    tasks = await _get_user_tasks(msg.from_user.id)
    if not tasks:
        await msg.reply(
            "📋 **No active tasks.**\n\n"
            "Use /nexttask to get your next assignment."
        )
        return
    for task in tasks:
        anime  = task["anime"]
        assign = task["assignment"]
        exp    = assign.get("expires_at")
        exp_s  = f"\n⏳ Expires: {exp.strftime('%Y-%m-%d')}" if exp else ""
        notes  = assign.get("notes", [])
        note_s = f"\n📝 {notes[-1]}" if notes else ""
        await msg.reply(
            task_card(anime, extra_line=exp_s + note_s),
            reply_markup=_task_kb(anime["anime_id"]),
            disable_web_page_preview=True,
        )


# ── /reserve ──────────────────────────────────────────────────────────────

@Client.on_message(filters.command("reserve"))
@admin_or_owner
@rate_limited
async def cmd_reserve(app: Client, msg: Message):
    args = msg.command[1:]
    if not args:
        await msg.reply("Usage: `/reserve <anime_id>`")
        return
    ok, text = await asn.reserve_anime(args[0], msg.from_user.id)
    if ok:
        anime = await anime_db.get_by_id(args[0])
        title = (anime["titles"]["display_title"] if anime else args[0])
        await msg.reply(f"✅ Reserved: **{title}**\n{text}")
    else:
        await msg.reply(f"❌ {text}")


# ── /away  /back ──────────────────────────────────────────────────────────

@Client.on_message(filters.command("away"))
@admin_or_owner
@rate_limited
async def cmd_away(app: Client, msg: Message):
    await users_db.set_away(msg.from_user.id, True)
    await logs_db.log_audit(str(msg.from_user.id), "away")
    await msg.reply(
        "😴 **Away mode on.**\n"
        "No new tasks will be assigned.\n"
        "Use /back when you return."
    )


@Client.on_message(filters.command("back"))
@admin_or_owner
@rate_limited
async def cmd_back(app: Client, msg: Message):
    await users_db.set_away(msg.from_user.id, False)
    await logs_db.log_audit(str(msg.from_user.id), "back")
    await msg.reply("✅ **Welcome back!** Use /nexttask to get started.")


# ── Callbacks ─────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^task_"))
async def cb_task_action(app: Client, query: CallbackQuery):
    try:
        await query.answer()
        parts    = query.data.split("_")
        if len(parts) < 3:
            return
        action   = parts[1]
        anime_id = parts[-1]
        uid      = query.from_user.id
        uname    = query.from_user.username or query.from_user.first_name

        # ── encoded / leeched — EDIT message, remove that button ──────────
        if action in ("encoded", "leeched"):
            status_map = {"encoded": "encoded", "leeched": "leeched"}
            new_status = status_map[action]
            ok, err    = await asn.update_status(uid, anime_id, new_status)
            if not ok:
                await query.answer(f"❌ {err}", show_alert=True)
                return

            anime = await anime_db.get_by_id(anime_id)
            if anime:
                await dashboard.upsert_anime_message(app, anime)
            await dashboard.update_all(app)
            await dashboard.log_event(
                app,
                f"{'📦' if action=='encoded' else '🔗'} **{new_status.title()}:** "
                f"{(anime or {}).get('titles',{}).get('display_title', anime_id)}\n"
                f"👤 @{uname}",
            )
            await sheets.sync_assigned()

            # Edit the task message in-place — show updated status, rebuild kb
            from database.settings import get_bool
            dh = await get_bool("ignore_donghua", False)
            await query.edit_message_text(
                task_card(anime or {"anime_id": anime_id, "titles": {"display_title": anime_id}},
                          status=new_status),
                reply_markup=_task_kb(anime_id, ignore_donghua=dh,
                                      exclude={"encoded", "leeched"} if new_status == "leeched"
                                      else {"encoded"}),
                disable_web_page_preview=True,
            )

        # ── completed / invalid — DELETE task msg, send confirmation ──────
        elif action in ("complete", "invalid"):
            new_status = "completed" if action == "complete" else "invalid"
            ok, err    = await asn.update_status(uid, anime_id, new_status)
            if not ok:
                await query.answer(f"❌ {err}", show_alert=True)
                return

            anime = await anime_db.get_by_id(anime_id)
            title = (anime or {}).get("titles", {}).get("display_title", anime_id)

            if anime:
                await dashboard.upsert_anime_message(app, anime)
            await dashboard.update_all(app)
            await dashboard.log_event(
                app,
                f"{'✅' if new_status=='completed' else '⚠️'} **{new_status.title()}:** {title}\n"
                f"👤 @{uname}",
            )
            if new_status == "completed":
                await sheets.sync_completed()

            # Delete the task card
            try:
                await query.message.delete()
            except Exception:
                await query.edit_message_reply_markup(reply_markup=None)

            # Send clean confirmation
            if new_status == "completed":
                await app.send_message(
                    query.message.chat.id,
                    f"✅ **Completed!**\n{SEP_BOLD}\n🎬 **{title}**\n\nGreat work! 🎉"
                )
            else:
                await app.send_message(
                    query.message.chat.id,
                    f"⚠️ **Marked Invalid**\n{SEP_BOLD}\n🎬 **{title}**\n\nAdded to review queue."
                )

        # ── note — delete task card, prompt for note ──────────────────────
        elif action == "note":
            _pending_notes[uid] = anime_id
            try:
                await query.message.delete()
            except Exception:
                pass
            anime = await anime_db.get_by_id(anime_id)
            title = (anime or {}).get("titles", {}).get("display_title", anime_id)
            await app.send_message(
                query.message.chat.id,
                f"📝 **Add Note**\n{SEP_BOLD}\n🎬 **{title}**\n\n"
                "Type your note and send it.\n"
                "Examples: _Waiting for source · No subs · Bad quality_\n\n"
                "Send /cancel to abort."
            )

        # ── toggle donghua ────────────────────────────────────────────────
        elif action == "toggle" and len(parts) >= 4:
            setting = parts[2]
            cfg_key = f"ignore_{setting}"
            from database.config import cfg as _cfg
            current = await _cfg.get(cfg_key)
            new_val = not bool(current)
            await _cfg.set(cfg_key, new_val, updated_by=uid)
            from database.settings import get_bool
            dh = await get_bool("ignore_donghua", False)
            state = "✅ ON" if new_val else "🔴 OFF"
            await query.answer(f"Ignore {setting.title()}: {state}", show_alert=False)
            await query.edit_message_reply_markup(
                reply_markup=_task_kb(anime_id, ignore_donghua=dh)
            )

    except Exception as e:
        logger.exception("cb_task_action error: %s", e)


# ── Note reply handler ────────────────────────────────────────────────────

async def handle_note_reply(app: Client, msg: Message):
    uid      = msg.from_user.id
    anime_id = _pending_notes.get(uid)
    if not anime_id:
        return
    text = (msg.text or "").strip()
    if text.lower() == "/cancel":
        _pending_notes.pop(uid, None)
        await msg.reply("❌ Cancelled.")
        return
    assignment = await assign_db.get_active(anime_id)
    if assignment:
        await assign_db.add_note(assignment["assignment_id"], text)
        _pending_notes.pop(uid, None)
        anime = await anime_db.get_by_id(anime_id)
        title = (anime or {}).get("titles", {}).get("display_title", anime_id)
        await msg.reply(f"📝 Note saved for **{title}**\n_{text}_")
    else:
        _pending_notes.pop(uid, None)
        await msg.reply("❌ No active assignment found.")


# ── Helpers ───────────────────────────────────────────────────────────────

async def _get_user_tasks(user_id: int):
    tasks = []
    for a in await assign_db.get_user_active(user_id):
        anime = await anime_db.get_by_id(a["anime_id"])
        if anime:
            tasks.append({"assignment": a, "anime": anime})
    return tasks


asn.get_user_tasks = _get_user_tasks  # type: ignore[attr-defined]


def _task_kb(anime_id: str, ignore_donghua: bool = False,
             exclude: set = None) -> InlineKeyboardMarkup:
    """
    Build task keyboard. exclude = set of statuses already set
    (removes those buttons from the kb).
    """
    exclude = exclude or set()
    dh_label = "🐉 Donghua: ✅" if ignore_donghua else "🐉 Donghua: 🔴"

    rows = []

    # Row 1: complete + encoded (if not excluded)
    row1 = []
    if "completed" not in exclude:
        row1.append(InlineKeyboardButton("✅ Done",    callback_data=f"task_complete_{anime_id}"))
    if "encoded" not in exclude:
        row1.append(InlineKeyboardButton("📦 Encoded", callback_data=f"task_encoded_{anime_id}"))
    if row1:
        rows.append(row1)

    # Row 2: leeched + invalid
    row2 = []
    if "leeched" not in exclude:
        row2.append(InlineKeyboardButton("🔗 Leeched", callback_data=f"task_leeched_{anime_id}"))
    row2.append(InlineKeyboardButton("❌ Invalid",  callback_data=f"task_invalid_{anime_id}"))
    rows.append(row2)

    # Row 3: note + donghua toggle
    rows.append([
        InlineKeyboardButton("📝 Note",   callback_data=f"task_note_{anime_id}"),
        InlineKeyboardButton(dh_label,    callback_data=f"task_toggle_donghua_{anime_id}"),
    ])

    return InlineKeyboardMarkup(rows)
