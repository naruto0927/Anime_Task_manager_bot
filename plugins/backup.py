"""
plugins/backup.py
Commands: /backup /backupstatus
"""
from pyrogram import Client, filters
from pyrogram.types import Message

import database.backups as backup_db
from helper.aliases import owner_only, rate_limited
from helper.backup import run_backup


@Client.on_message(filters.command("backup"))
@owner_only
@rate_limited
async def cmd_backup(app: Client, msg: Message):
    """Trigger an immediate manual backup to the backup channel."""
    status_msg = await msg.reply("⏳ Starting backup…")
    ok = await run_backup(app)
    if ok:
        latest = await backup_db.get_latest_success()
        size   = (latest["size_bytes"] // 1024) if latest else 0
        await status_msg.edit(
            f"✅ **Backup complete!**\n"
            f"Size: {size} KB\n"
            f"Sent to backup channel."
        )
    else:
        await status_msg.edit(
            "❌ **Backup failed.**\nCheck error log or /health for details."
        )


@Client.on_message(filters.command("backupstatus"))
@owner_only
@rate_limited
async def cmd_backupstatus(app: Client, msg: Message):
    """Show the last 5 backup records."""
    from database.mongo import get_db
    db = get_db()

    records = [b async for b in db.backups.find(
        {}, sort=[("created_at", -1)]
    ).limit(5)]

    if not records:
        await msg.reply("No backups recorded yet.")
        return

    lines = []
    for b in records:
        status_emoji = {"success": "✅", "failed": "❌", "pending": "⏳"}.get(b["status"], "❓")
        ts   = b["created_at"].strftime("%Y-%m-%d %H:%M UTC")
        size = f"{b.get('size_bytes', 0) // 1024} KB"
        lines.append(f"{status_emoji} `{b['backup_id']}` — {ts} — {size}")

    await msg.reply(
        "💾 **Recent Backups**\n" + "\n".join(lines)
    )
