"""
plugins/dashboard.py
Commands: /rebuilddashboard /setdashboard /setlogchannel /setbackupchannel
"""
from pyrogram import Client, filters
from pyrogram.types import Message

import database.settings as settings_db
from helper import dashboard as dash
from helper.aliases import owner_only, rate_limited


@Client.on_message(filters.command("rebuilddashboard"))
@owner_only
@rate_limited
async def cmd_rebuilddashboard(app: Client, msg: Message):
    """Force rebuild all pinned dashboard messages."""
    status_msg = await msg.reply("🔨 Rebuilding dashboard messages…")
    try:
        await dash.rebuild(app)
        await status_msg.edit("✅ Dashboard rebuilt and pinned.")
    except RuntimeError as e:
        await status_msg.edit(f"❌ {e}")
    except Exception as e:
        await status_msg.edit(f"❌ Failed: `{e}`")


@Client.on_message(filters.command("setdashboard"))
@owner_only
@rate_limited
async def cmd_setdashboard(app: Client, msg: Message):
    """
    /setdashboard <channel_id>
    Set the channel where dashboard messages are posted.
    """
    args = msg.command[1:]
    if not args:
        current = await settings_db.get("dashboard_channel")
        if current:
            await msg.reply(f"📊 Dashboard channel: `{current}`\nUse `/setdashboard <channel_id>` to change.")
        else:
            await msg.reply(
                "No dashboard channel set.\n\n"
                "Usage: `/setdashboard -1001234567890`\n\n"
                "Make sure the bot is an admin in that channel."
            )
        return

    try:
        channel_id = int(args[0])
    except ValueError:
        await msg.reply("❌ Invalid channel ID. Must be a number like `-1001234567890`")
        return

    await settings_db.set("dashboard_channel", channel_id, msg.from_user.id)
    await msg.reply(
        f"✅ Dashboard channel set to `{channel_id}`.\n\n"
        "Use /rebuilddashboard to post the initial messages."
    )


@Client.on_message(filters.command("setlogchannel"))
@owner_only
@rate_limited
async def cmd_setlogchannel(app: Client, msg: Message):
    """
    /setlogchannel <channel_id>
    Set the channel for event logs.
    """
    args = msg.command[1:]
    if not args:
        current = await settings_db.get("log_channel")
        if current:
            await msg.reply(f"📋 Log channel: `{current}`")
        else:
            await msg.reply("Usage: `/setlogchannel <channel_id>`")
        return

    try:
        channel_id = int(args[0])
    except ValueError:
        await msg.reply("❌ Invalid channel ID.")
        return

    await settings_db.set("log_channel", channel_id, msg.from_user.id)
    await msg.reply(f"✅ Log channel set to `{channel_id}`.")
    await dash.log_event(app, "📋 Log channel configured.")


@Client.on_message(filters.command("setbackupchannel"))
@owner_only
@rate_limited
async def cmd_setbackupchannel(app: Client, msg: Message):
    """
    /setbackupchannel <channel_id>
    Set the channel where backup archives are sent.
    """
    args = msg.command[1:]
    if not args:
        current = await settings_db.get("backup_channel")
        if current:
            await msg.reply(f"💾 Backup channel: `{current}`")
        else:
            await msg.reply("Usage: `/setbackupchannel <channel_id>`")
        return

    try:
        channel_id = int(args[0])
    except ValueError:
        await msg.reply("❌ Invalid channel ID.")
        return

    await settings_db.set("backup_channel", channel_id, msg.from_user.id)
    await msg.reply(
        f"✅ Backup channel set to `{channel_id}`.\n"
        "Daily backups will be sent there automatically."
    )
