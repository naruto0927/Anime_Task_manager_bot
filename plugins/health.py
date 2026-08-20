"""
plugins/health.py
Commands: /health /ping
Note: /set is handled by plugins/settings.py
"""
from pyrogram import Client, filters
from pyrogram.types import Message

from helper.aliases import admin_or_owner, owner_only, rate_limited
from helper.health import get_health


@Client.on_message(filters.command("health"))
@owner_only
@rate_limited
async def cmd_health(app: Client, msg: Message):
    """Full system health and status check."""
    status_msg = await msg.reply("🔍 Running health check…")
    h = await get_health()

    mongo_str   = "🟢 OK" if h["mongo_ok"]  else "🔴 FAILED"
    sheets_str  = f"🟢 {h['sheets_status']}" if h["sheets_ok"] else f"🔴 {h['sheets_status']}"
    uptime_str  = _fmt_uptime(h["uptime_s"])
    dash_str    = f"`{h['dash_ch']}`"   if h["dash_ch"]   else "❌ Not set"
    log_str     = f"`{h['log_ch']}`"    if h["log_ch"]    else "❌ Not set"
    backup_str  = f"`{h['backup_ch']}`" if h["backup_ch"] else "❌ Not set"

    await status_msg.edit(
        f"🏥 **System Health**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🍃 MongoDB:       {mongo_str}\n"
        f"📊 Google Sheets: {sheets_str}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Pending:       **{h['pending']}**\n"
        f"🎯 Assigned:      **{h['assigned']}**\n"
        f"👥 Active Admins: **{h['active_admins']}**\n"
        f"😴 Away Admins:   **{h['away_admins']}**\n"
        f"💾 Last Backup:   {h['last_backup']}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📺 Dashboard Ch:  {dash_str}\n"
        f"📋 Log Channel:   {log_str}\n"
        f"💾 Backup Ch:     {backup_str}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🖥️ CPU:           {h['cpu']}%\n"
        f"🧠 Memory:        {h['mem_used_mb']} / {h['mem_total_mb']} MB ({h['mem_pct']}%)\n"
        f"⏱ Uptime:        {uptime_str}"
    )


@Client.on_message(filters.command("ping"))
@admin_or_owner
@rate_limited
async def cmd_ping(app: Client, msg: Message):
    """Quick latency check."""
    import time, logging as _log
    _log.getLogger(__name__).info(">>> /ping HANDLER FIRED from %s", msg.from_user.id)
    t0 = time.time()
    reply = await msg.reply("🏓 Pong!")
    ms = round((time.time() - t0) * 1000)
    await reply.edit(f"🏓 **Pong!** `{ms}ms`")


def _fmt_uptime(seconds: float) -> str:
    s   = int(seconds)
    d   = s // 86400
    s  %= 86400
    h   = s // 3600
    s  %= 3600
    m   = s // 60
    s  %= 60
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m {s}s"
    return f"{m}m {s}s"
