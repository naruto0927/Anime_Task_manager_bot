"""
plugins/panel.py — Interactive config panel.

Changes:
- Bool keys show 🔘 Toggle button — one tap, no text input needed
- After text input for non-bool keys, bot EDITS the prompt message in-place
- Per-user state now tracks the message_id to edit back
"""
from __future__ import annotations
import logging
from typing import Any

from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from database.config import CATEGORIES, CATEGORY_LABELS, CONFIG_SCHEMA, SCHEMA_MAP, cfg
import database.logs as logs_db
from helper.aliases import is_owner, owner_only

logger = logging.getLogger(__name__)

# {user_id: {"edit_key": str, "chat_id": int, "msg_id": int}}
_state: dict[int, dict] = {}


# ── /panel ────────────────────────────────────────────────────────────────

@Client.on_message(filters.command("panel"))
@owner_only
async def cmd_panel(app: Client, msg: Message):
    text, kb = await _main_menu()
    await msg.reply(text, reply_markup=kb)


# ── Callbacks ─────────────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^panel_"))
async def cb_panel(app: Client, query: CallbackQuery):
    try:
        await query.answer()
        uid  = query.from_user.id
        data = query.data

        if not is_owner(uid):
            await query.answer("⛔ Owner only.", show_alert=True)
            return

        # ── Main menu ─────────────────────────────────────────────────────
        if data == "panel_main":
            _state.pop(uid, None)
            text, kb = await _main_menu()
            await query.edit_message_text(text, reply_markup=kb)

        # ── Category view ─────────────────────────────────────────────────
        elif data.startswith("panel_cat_"):
            _state.pop(uid, None)
            category = data[len("panel_cat_"):]
            text, kb = await _category_view(category)
            await query.edit_message_text(text, reply_markup=kb)

        # ── Bool toggle — instant, no text input ──────────────────────────
        elif data.startswith("panel_toggle_"):
            key    = data[len("panel_toggle_"):]
            schema = SCHEMA_MAP.get(key)
            if not schema or schema["type"] != "bool":
                return
            current = await cfg.get(key)
            new_val = not bool(current)
            await cfg.set(key, new_val, updated_by=uid)
            await logs_db.log_audit(
                str(uid), "config_toggled",
                target=key,
                old_value=str(current),
                new_value=str(new_val),
            )
            # Refresh category view in-place
            category = schema["category"]
            text, kb = await _category_view(category)
            await query.edit_message_text(text, reply_markup=kb)

        # ── Edit non-bool key — prompt for text input ──────────────────────
        elif data.startswith("panel_edit_"):
            key    = data[len("panel_edit_"):]
            schema = SCHEMA_MAP.get(key)
            if not schema:
                await query.answer("Unknown key.", show_alert=True)
                return
            # Store chat+message so we can edit it back after input
            _state[uid] = {
                "edit_key": key,
                "chat_id":  query.message.chat.id,
                "msg_id":   query.message.id,
            }
            current = await cfg.get(key)
            display = cfg.mask(current) if schema.get("secret") else _disp(current)
            text = (
                f"✏️ **Edit: {schema['label']}**\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"**Key:** `{key}`\n"
                f"**Type:** {_type_hint(schema['type'])}\n"
                f"**Current:** `{display}`\n\n"
                f"ℹ️ {schema['description']}\n"
                f"━━━━━━━━━━━━━━━━━━━\n"
                f"{_example_for(key)}"
                f"**Reply with the new value** or tap Back to cancel."
            )
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🔙 Back", callback_data=f"panel_cat_{schema['category']}")
            ]])
            await query.edit_message_text(text, reply_markup=kb)

    except Exception as e:
        logger.exception("cb_panel error: %s", e)


# ── Text input handler (called from text_router) ──────────────────────────

async def handle_panel_input(app: Client, msg: Message):
    """Receives plain-text reply when owner is editing a config key."""
    if not msg.from_user:
        return
    uid   = msg.from_user.id
    state = _state.get(uid)
    if not state or "edit_key" not in state:
        return
    if not is_owner(uid):
        _state.pop(uid, None)
        return

    text = (msg.text or "").strip()
    if text.lower() in ("/cancel", "cancel"):
        _state.pop(uid, None)
        await msg.reply("❌ Edit cancelled.")
        return

    key    = state["edit_key"]
    schema = SCHEMA_MAP.get(key, {})
    ok, coerced, err = _validate(text, schema.get("type", "str"))

    if not ok:
        await msg.reply(
            f"❌ Invalid value: {err}\n"
            f"Expected: {_type_hint(schema.get('type','str'))}\n\n"
            "Try again or send /cancel."
        )
        return

    old_val = await cfg.get(key)
    await cfg.set(key, coerced, updated_by=uid)
    await logs_db.log_audit(
        str(uid), "config_updated",
        target=key, old_value=str(old_val), new_value=str(coerced),
    )

    chat_id = state.get("chat_id")
    msg_id  = state.get("msg_id")
    _state.pop(uid, None)

    display = cfg.mask(coerced) if schema.get("secret") else _disp(coerced)
    success_text = (
        f"✅ **{schema.get('label', key)}** updated!\n\n"
        f"**New value:** `{display}`"
    )

    # Edit the original prompt message in-place
    try:
        if chat_id and msg_id:
            category = schema.get("category", "")
            _, kb    = await _category_view(category)
            await app.edit_message_text(chat_id, msg_id, success_text, reply_markup=kb)
    except Exception:
        pass

    # Also delete the user's reply to keep chat clean
    try:
        await msg.delete()
    except Exception:
        pass


# ── Builders ──────────────────────────────────────────────────────────────

async def _main_menu():
    all_cfg = await cfg.get_all()
    total   = len(CONFIG_SCHEMA)
    set_cnt = sum(
        1 for s in CONFIG_SCHEMA
        if all_cfg.get(s["key"]) not in (None, "", [], s["default"])
    )
    text = (
        "⚙️ **Configuration Panel**\n"
        "━━━━━━━━━━━━━━━━━━━\n"
        f"📦 {set_cnt}/{total} variables configured\n\n"
        "Select a category to view and edit settings."
    )
    buttons, row = [], []
    for cat in CATEGORIES:
        keys_in = [s for s in CONFIG_SCHEMA if s["category"] == cat]
        filled  = sum(1 for s in keys_in
                      if all_cfg.get(s["key"]) not in (None, "", [], s["default"]))
        status  = "✅" if filled == len(keys_in) else ("⚠️" if filled > 0 else "❌")
        row.append(InlineKeyboardButton(
            f"{status} {CATEGORY_LABELS[cat]}",
            callback_data=f"panel_cat_{cat}",
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return text, InlineKeyboardMarkup(buttons)


async def _category_view(category: str):
    label   = CATEGORY_LABELS.get(category, category)
    keys    = [s for s in CONFIG_SCHEMA if s["category"] == category]
    all_cfg = await cfg.get_all()

    lines   = []
    buttons = []
    for s in keys:
        val     = all_cfg.get(s["key"])
        display = cfg.mask(val) if s.get("secret") and val else _disp(val)
        dot     = "⚪" if val in (None, "", [], s["default"]) else "🟢"
        lines.append(f"{dot} **{s['label']}**: `{display}`")

        if s["type"] == "bool":
            # Toggle button — shows current state
            state_label = "✅ ON" if val else "🔴 OFF"
            buttons.append([InlineKeyboardButton(
                f"🔘 {s['label']}: {state_label}",
                callback_data=f"panel_toggle_{s['key']}",
            )])
        else:
            buttons.append([InlineKeyboardButton(
                f"✏️ {s['label']}",
                callback_data=f"panel_edit_{s['key']}",
            )])

    text = (
        f"{label}\n━━━━━━━━━━━━━━━━━━━\n"
        + "\n".join(lines)
        + "\n\nBool settings toggle instantly. Tap others to edit:"
    )
    buttons.append([InlineKeyboardButton("🔙 Back to Menu", callback_data="panel_main")])
    return text, InlineKeyboardMarkup(buttons)


# ── Helpers ───────────────────────────────────────────────────────────────

def _disp(val: Any) -> str:
    if val is None or val == "":
        return "❌ Not set"
    if isinstance(val, list):
        return ", ".join(str(x) for x in val) or "❌ Not set"
    if isinstance(val, bool):
        return "✅ ON" if val else "🔴 OFF"
    return str(val)


def _type_hint(t: str) -> str:
    return {
        "str":  "Text",
        "int":  "Integer number",
        "bool": "on / off",
        "list": "Comma-separated values",
    }.get(t, "Text")


def _example_for(key: str) -> str:
    ex = {
        "owner_ids":                "Example: `123456789,987654321`\n",
        "dashboard_channel":        "Example: `-1001234567890`\n",
        "log_channel":              "Example: `-1001234567891`\n",
        "backup_channel":           "Example: `-1001234567892`\n",
        "sheets_spreadsheet_id":    "Example: `1BxiMVs0XRA5nFMdKvBdBZjg`\n",
        "sheets_credentials_file":  "Example: `credentials.json`\n",
        "task_limit":               "Example: `5`\n",
        "expiry_days":              "Example: `7`\n",
        "reservation_hours":        "Example: `24`\n",
        "rapidfuzz_threshold":      "Example: `90`\n",
        "dashboard_update_interval":"Example: `300` (seconds)\n",
        "backup_hour":              "Example: `3` (3 AM UTC)\n",
        "backup_minute":            "Example: `0`\n",
        "log_level":                "Options: `DEBUG` | `INFO` | `WARNING` | `ERROR`\n",
    }
    return ex.get(key, "")


def _validate(raw: str, type_str: str):
    try:
        if type_str == "int":
            return True, int(raw), None
        if type_str == "bool":
            if raw.lower() in ("on", "true", "1", "yes"):
                return True, True, None
            if raw.lower() in ("off", "false", "0", "no"):
                return True, False, None
            return False, None, "Use: on / off"
        if type_str == "list":
            return True, [x.strip() for x in raw.split(",") if x.strip()], None
        return True, raw.strip(), None
    except (ValueError, TypeError) as e:
        return False, None, str(e)
