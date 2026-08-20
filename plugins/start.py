"""plugins/start.py — /start"""
import logging
from pyrogram import Client, filters
from pyrogram.types import Message
from helper.aliases import is_owner
from helper.theme import SEP_BOLD

logger = logging.getLogger(__name__)

@Client.on_message(filters.command("start") & filters.private)
async def cmd_start(app: Client, msg: Message):
    try:
        import database.users as users_db
        user = msg.from_user
        await users_db.upsert_on_start(user.id, user.username or "", user.full_name or "")

        if is_owner(user.id):
            text = (
                f"🌊 **Welcome, {user.first_name}**\n"
                f"{SEP_BOLD}\n"
                "👑 **Owner Access**\n\n"
                "🔧 `/importseason Spring 2026` — Import anime\n"
                "📊 `/stats` — Browse library\n"
                "🔍 `/find <title>` — Search\n"
                "⚙️ `/panel` — Settings\n"
                "💡 `/help` — All commands"
            )
        else:
            text = (
                f"🌊 **Welcome, {user.first_name}**\n"
                f"{SEP_BOLD}\n"
                "🛡️ **Admin Access**\n\n"
                "🎯 `/nexttask` — Get assignment\n"
                "📋 `/mytask` — Active tasks\n"
                "📊 `/mystats` — Your stats\n"
                "💡 `/help` — All commands"
            )
        await msg.reply(text)
    except Exception as e:
        logger.exception("/start error")
        await msg.reply(f"⚠️ `{e}`")
