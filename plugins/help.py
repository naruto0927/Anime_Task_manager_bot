"""plugins/help.py — /help"""
import logging
from pyrogram import Client, filters
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from helper.aliases import is_owner
import database.users as users_db

logger = logging.getLogger(__name__)


@Client.on_message(filters.command("help"))
async def cmd_help(app: Client, msg: Message):
    try:
        if not msg.from_user:
            return
        await users_db.upsert_on_start(
            msg.from_user.id, msg.from_user.username or "", msg.from_user.full_name or ""
        )
        owner = is_owner(msg.from_user.id)
        intro = (
            "🎬 **Anime Workflow Platform**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "Choose a category:"
        )
        if owner:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("👑 Owner", callback_data="help_owner"),
                InlineKeyboardButton("🛡️ Admin", callback_data="help_admin"),
            ]])
        else:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🛡️ Admin Commands", callback_data="help_admin"),
            ]])
        await msg.reply(intro, reply_markup=kb)
    except Exception as e:
        logger.exception("/help error: %s", e)
        await msg.reply(f"⚠️ Error: `{type(e).__name__}: {e}`")


@Client.on_callback_query(filters.regex(r"^help_"))
async def cb_help(app: Client, query: CallbackQuery):
    try:
        await query.answer()
        owner = is_owner(query.from_user.id)

        if query.data == "help_owner":
            if not owner:
                await query.answer("⛔ Owner only.", show_alert=True)
                return
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("🛡️ Admin", callback_data="help_admin"),
                InlineKeyboardButton("🔙 Back",  callback_data="help_back"),
            ]])
            await query.edit_message_text(_owner_help(), reply_markup=kb)

        elif query.data == "help_admin":
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("👑 Owner", callback_data="help_owner") if owner else
                InlineKeyboardButton("🔙 Back",  callback_data="help_back"),
            ]])
            await query.edit_message_text(_admin_help(), reply_markup=kb)

        elif query.data == "help_back":
            intro = "🎬 **Anime Workflow Platform**\n━━━━━━━━━━━━━━━━━━━━━━━━━\nChoose a category:"
            if owner:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("👑 Owner", callback_data="help_owner"),
                    InlineKeyboardButton("🛡️ Admin", callback_data="help_admin"),
                ]])
            else:
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton("🛡️ Admin Commands", callback_data="help_admin"),
                ]])
            await query.edit_message_text(intro, reply_markup=kb)
    except Exception as e:
        logger.exception("cb_help error: %s", e)


def _owner_help() -> str:
    return (
        "👑 **OWNER COMMANDS**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📥 **Import**\n"
        "/importseason `<Season> <Year>` — Import from MAL\n"
        "/importseason `<Season> <Year> --preview` — Preview\n"
        "/importyear `<Year>` — Import all 4 seasons\n\n"
        "👥 **Admin Management**\n"
        "/addadmin `@username` — Grant access\n"
        "/removeadmin `@username` — Revoke access\n"
        "/listadmins — List all admins\n"
        "/maxtasks `@username <limit>` — Set task limit\n"
        "/forceassign `<id> @user` — Force-assign\n"
        "/reassign `<id> @user` — Reassign\n"
        "/priority `<id> <high|medium|low>` — Set priority\n\n"
        "🗑️ **Drop / Restore**\n"
        "/dropanime `<id> [reason]`\n"
        "/restoreanime `<id>`\n"
        "/dropped — List dropped\n"
        "/deleteanime `<id> confirm`\n\n"
        "📦 **Bulk Season**\n"
        "/dropseason `<Season> <Year>`\n"
        "/deleteseason `<Season> <Year> confirm`\n"
        "/reassignseason `<Season> <Year>`\n"
        "/restoreseason `<Season> <Year>`\n"
        "/exportseason `<Season> <Year>`\n\n"
        "📊 **Dashboard & Channels**\n"
        "/setdashboard `/setlogchannel` `/setbackupchannel`\n"
        "/rebuilddashboard\n\n"
        "⚙️ **Settings**\n"
        "/panel — Interactive config editor\n"
        "/set `<key> <value>`\n\n"
        "💾 **Backup & Reports**\n"
        "/backup /exportsheet /report\n\n"
        "📈 **Stats**\n"
        "/stats /health"
    )


def _admin_help() -> str:
    return (
        "🛡️ **ADMIN COMMANDS**\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎯 **Tasks**\n"
        "/nexttask — Get next assignment\n"
        "/mytask — View active tasks\n"
        "/reserve `<anime_id>` — Reserve for 24h\n\n"
        "🟢 **Availability**\n"
        "/away — Mark unavailable\n"
        "/back — Mark available\n\n"
        "🔍 **Search**\n"
        "/find `<title>` — Search by title\n"
        "/franchise `<name>` — View franchise\n\n"
        "📊 **Stats**\n"
        "/mystats — Your stats\n"
        "/leaderboard — Top performers"
    )
