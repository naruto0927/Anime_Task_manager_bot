"""
plugins/franchise.py
Commands: /franchiselist /franchiserebuild
"""
from pyrogram import Client, filters
from pyrogram.types import Message

from database.mongo import get_db
from helper.aliases import owner_only, rate_limited
from helper.franchise import ensure_franchise, generate_slug


@Client.on_message(filters.command("franchiselist"))
@owner_only
@rate_limited
async def cmd_franchiselist(app: Client, msg: Message):
    """List all franchises with their entry counts."""
    db  = get_db()
    frs = [f async for f in db.franchises.find({}).limit(50)]
    if not frs:
        await msg.reply("No franchises in database yet.")
        return

    lines = []
    for fr in frs:
        locked  = "🔒" if fr.get("has_active_assignment") else "🔓"
        entries = len(fr.get("anime_ids", []))
        lines.append(
            f"{locked} **{fr.get('name', fr['franchise_id'])}**\n"
            f"   🆔 `{fr['franchise_id']}` | 📦 {entries} entries"
        )

    await msg.reply(
        f"📚 **Franchises ({len(frs)})**\n"
        f"━━━━━━━━━━━━━━━━━━━\n" + "\n\n".join(lines[:20])
        + ("\n\n_…and more_" if len(frs) > 20 else "")
    )


@Client.on_message(filters.command("franchiserebuild"))
@owner_only
@rate_limited
async def cmd_franchiserebuild(app: Client, msg: Message):
    """Rebuild franchise links for all anime in the database."""
    db         = get_db()
    status_msg = await msg.reply("⚙️ Rebuilding franchise links…")
    updated    = 0
    errors     = 0

    async for anime in db.anime.find({"deleted": {"$ne": True}}):
        try:
            fr_id = await ensure_franchise(anime)
            if anime.get("franchise_id") != fr_id:
                updated += 1
        except Exception:
            errors += 1

    await status_msg.edit(
        f"✅ **Franchise Rebuild Complete**\n\n"
        f"Updated: **{updated}**\n"
        f"Errors: **{errors}**"
    )
