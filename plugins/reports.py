"""
plugins/reports.py
Commands: /report /exportsheet /audio_stats /leaderboard
"""
import csv
import io
from datetime import datetime

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from database.mongo import get_db
from database.settings import get_bool, get_str
from helper import sheets, stats as stats_helper
from helper.aliases import admin_or_owner, owner_only, rate_limited


def _progress_bar(value: int, maximum: int, width: int = 8) -> str:
    if maximum <= 0:
        return "░" * width
    filled = round((min(value, maximum) / maximum) * width)
    return "█" * filled + "░" * (width - filled)


@Client.on_message(filters.command("report"))
@owner_only
@rate_limited
async def cmd_report(app: Client, msg: Message):
    """Full platform status report; optionally syncs Sheets."""
    args = msg.command[1:]
    if args and len(args) >= 2:
        season = args[0].lower()
        try:
            year = int(args[1])
            await _season_report(msg, season, year)
            return
        except ValueError:
            pass

    status_msg = await msg.reply("⏳ Generating report…")

    s      = await stats_helper.global_stats()
    board  = await stats_helper.leaderboard(5)
    recent = await stats_helper.recent_completions(5)
    total  = max(s["total"], 1)
    pct    = f"{round(s['completed']/total*100)}%"

    top = "\n".join(
        f"  {e['rank']}. @{e['username']} — {e['completed']} ✅  {e['encoded']} 📦  {e['active']} 🎯"
        for e in board
    ) or "  No data."
    recent_lines = "\n".join(
        f"  • {c['title'][:35]} — @{c['completed_by']}"
        for c in recent
    ) or "  No completions yet."
    bk_str = s["last_backup"].strftime("%Y-%m-%d %H:%M UTC") if s["last_backup"] else "Never"

    sheets_status = ""
    if await sheets.is_enabled():
        ok = await sheets.full_sync()
        sheets_status = "\n✅ Google Sheets synced." if ok else "\n⚠️ Sheets sync had errors."

    await status_msg.edit(
        f"📊 **Platform Report** — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Total:      **{s['total']}**\n"
        f"⏳ Pending:    **{s['pending']}**\n"
        f"🎯 Assigned:   **{s['assigned']}**\n"
        f"📤 Encoded:    **{s['encoded']}**\n"
        f"🔗 Leeched:    **{s['leeched']}**\n"
        f"✅ Completed:  **{s['completed']}** ({pct})\n"
        f"❌ Dropped:    **{s['dropped']}**\n"
        f"⚠️  Invalid:    **{s['invalid']}**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 **Top Admins**\n{top}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"🏁 **Recent Completions**\n{recent_lines}\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"💾 Last Backup: {bk_str}"
        + sheets_status
    )


@Client.on_message(filters.command("exportsheet"))
@owner_only
@rate_limited
async def cmd_exportsheet(app: Client, msg: Message):
    """Force full Google Sheets sync with optional link button + CSV files."""
    status_msg = await msg.reply("⏳ Syncing all tabs…")

    if not await sheets.is_enabled():
        await status_msg.edit(
            "❌ Google Sheets is disabled.\n"
            "Enable with: `/set sheets_enabled on`"
        )
        return

    ok = await sheets.full_sync()
    if not ok:
        await status_msg.edit("❌ Sync failed. Check /health for details.")
        return

    sheet_url  = await sheets.spreadsheet_url()
    send_link  = await get_bool("sheets_send_link_on_export", True)
    send_files = await get_bool("sheets_send_file_on_export", False)

    kb = None
    if sheet_url and send_link:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📊 Open Google Sheet", url=sheet_url)
        ]])

    await status_msg.edit("✅ All Google Sheets tabs synced.", reply_markup=kb)

    if send_files:
        from database.settings import get as cfg_get
        bk_ch = await cfg_get("backup_channel")
        if not bk_ch:
            await msg.reply(
                "⚠️ `sheets_send_file_on_export` is on but no backup channel is set.\n"
                "Configure via `/setbackupchannel <id>`."
            )
            return

        await msg.reply("📤 Uploading CSV files to backup channel…")
        now_str = datetime.utcnow().strftime("%Y%m%d_%H%M")

        from helper.sheets import TABS
        for tab_key, tab_name in TABS.items():
            try:
                csv_bytes = await sheets.export_tab_csv(tab_key)
                filename  = f"{tab_name.lower().replace(' ','_')}_{now_str}.csv"
                bio       = io.BytesIO(csv_bytes)
                bio.name  = filename
                await msg.reply_document(bio, file_name=filename,
                                         caption=f"📋 **{tab_name}** export ({now_str} UTC)")
            except Exception as exc:
                pass

        await msg.reply("✅ CSV files sent.")


@Client.on_message(filters.command("audio_stats"))
@admin_or_owner
@rate_limited
async def cmd_audio_stats(app: Client, msg: Message):
    """Per-user completion breakdown."""
    db    = get_db()
    lines = []
    async for user in db.users.find({"role": "admin"}, sort=[("completed_count", -1)]).limit(20):
        uname = user.get("username") or user.get("full_name", "Unknown")
        away  = " 😴" if user.get("is_away") else ""
        lines.append(
            f"  @{uname}{away}\n"
            f"    ✅ {user.get('completed_count',0)} | "
            f"📦 {user.get('encoded_count',0)} | "
            f"🔗 {user.get('leeched_count',0)} | "
            f"⚠️ {user.get('invalid_count',0)} | "
            f"🎯 {user.get('active_task_count',0)}/{user.get('task_limit',5)}"
        )

    if not lines:
        await msg.reply("No admin data found.")
        return

    await msg.reply(
        f"🎙 **Audio Stats** ({len(lines)} admins)\n"
        f"Format: ✅ done | 📦 enc | 🔗 leeched | ⚠️ invalid | 🎯 active\n"
        f"━━━━━━━━━━━━━━━━━━━\n" + "\n\n".join(lines)
    )


@Client.on_message(filters.command("leaderboard"))
@admin_or_owner
@rate_limited
async def cmd_leaderboard(app: Client, msg: Message):
    args  = msg.command[1:]
    limit = 10
    if args:
        try:
            limit = min(max(int(args[0]), 1), 25)
        except ValueError:
            pass

    board = await stats_helper.leaderboard(limit)
    if not board:
        await msg.reply("🏆 No completions yet. Be the first!")
        return

    medals   = ["🥇", "🥈", "🥉"] + ["🏅"] * 25
    top_comp = board[0]["completed"] if board else 1
    lines    = []
    for e in board:
        bar = _progress_bar(e["completed"], top_comp, width=8) if top_comp > 0 else ""
        lines.append(
            f"{medals[e['rank']-1]} **@{e['username']}**\n"
            f"   {bar} {e['completed']} ✅  |  {e['active']} 🎯 active"
        )

    await msg.reply(
        f"🏆 **Leaderboard — Top {limit}**\n\n" + "\n\n".join(lines)
    )


async def _season_report(msg: Message, season: str, year: int) -> None:
    from database.anime import find_by_season
    anime_list = await find_by_season(season, year)
    if not anime_list:
        await msg.reply(f"No anime found for {season.title()} {year}.")
        return
    total   = len(anime_list)
    by_stat = {}
    for a in anime_list:
        by_stat[a["status"]] = by_stat.get(a["status"], 0) + 1
    pct   = round(by_stat.get("completed", 0) / total * 100, 1)
    bar   = _progress_bar(by_stat.get("completed", 0), total, width=12)
    lines = "\n".join(f"  {s.title()}: **{c}**" for s, c in sorted(by_stat.items()))
    await msg.reply(
        f"📅 **{season.title()} {year} Report**\n"
        f"━━━━━━━━━━━━━━━━━━━\n"
        f"📦 Total: **{total}**\n{lines}\n"
        f"Progress: {bar} {pct}%"
    )
