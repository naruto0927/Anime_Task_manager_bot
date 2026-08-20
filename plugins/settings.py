"""
plugins/settings.py
Commands: /maxtasks /priority /set
Note: /panel is handled by plugins/panel.py
"""
from pyrogram import Client, filters
from pyrogram.types import Message

import database.settings as settings_db
from helper.aliases import owner_only, rate_limited
from helper.settings import coerce, update_setting


@Client.on_message(filters.command("maxtasks"))
@owner_only
@rate_limited
async def cmd_maxtasks(app: Client, msg: Message):
    """
    /maxtasks <limit>            — Set global task limit
    /maxtasks @username <limit>  — Set per-user task limit
    """
    args = msg.command[1:]
    if not args:
        current = await settings_db.get_int("task_limit", 5)
        await msg.reply(
            f"Current global task limit: **{current}**\n\n"
            "Usage:\n"
            "`/maxtasks 5` — Set global limit\n"
            "`/maxtasks @username 3` — Set per-user limit"
        )
        return

    if len(args) == 1:
        ok, value, err = coerce("task_limit", args[0])
        if not ok:
            await msg.reply(f"❌ {err}")
            return
        await update_setting("task_limit", value, msg.from_user.id)
        await msg.reply(f"✅ Global task limit set to **{value}**.")
    else:
        username = args[0].lstrip("@")
        ok, value, err = coerce("task_limit", args[1])
        if not ok:
            await msg.reply(f"❌ {err}")
            return
        from database.mongo import get_db
        result = await get_db().users.update_one(
            {"username": username}, {"$set": {"task_limit": value}}
        )
        if result.matched_count:
            await msg.reply(f"✅ @{username} task limit set to **{value}**.")
        else:
            await msg.reply(f"❌ User @{username} not found.")


@Client.on_message(filters.command("priority"))
@owner_only
@rate_limited
async def cmd_priority(app: Client, msg: Message):
    """/priority <anime_id> <high|medium|low>"""
    args = msg.command[1:]
    if len(args) < 2:
        await msg.reply("Usage: `/priority <anime_id> <high|medium|low>`")
        return

    anime_id = args[0]
    prio     = args[1].lower()
    if prio not in ("high", "medium", "low"):
        await msg.reply("❌ Priority must be: high / medium / low")
        return

    from database.mongo import get_db
    from datetime import datetime
    result = await get_db().anime.update_one(
        {"anime_id": anime_id},
        {"$set": {"priority": prio, "updated_at": datetime.utcnow()}},
    )
    if result.matched_count:
        import database.logs as logs_db
        await logs_db.log_audit(
            str(msg.from_user.id), "priority_changed",
            target=anime_id, new_value=prio,
        )
        prio_emoji = {"high": "🔴", "medium": "🟡", "low": "🟢"}[prio]
        await msg.reply(f"{prio_emoji} Priority for `{anime_id}` → **{prio.upper()}**")
    else:
        await msg.reply(f"❌ Anime `{anime_id}` not found.")


@Client.on_message(filters.command("set"))
@owner_only
@rate_limited
async def cmd_set(app: Client, msg: Message):
    """/set <key> <value> — Update any config key directly."""
    args = msg.command[1:]
    if len(args) < 2:
        all_keys = await settings_db.get_all()
        preview  = "\n".join(
            f"  `{k}` = `{v}`"
            for k, v in list(all_keys.items())[:20]
        )
        await msg.reply(
            "Usage: `/set <key> <value>`\n\n"
            f"**Current settings (first 20):**\n{preview}\n\n"
            "Use /panel for the full interactive editor."
        )
        return

    key   = args[0]
    value = " ".join(args[1:])
    ok, coerced, err = coerce(key, value)
    if not ok:
        await msg.reply(f"❌ {err}")
        return

    await update_setting(key, coerced, msg.from_user.id)
    await msg.reply(f"✅ `{key}` → `{coerced}`")
