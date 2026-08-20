"""
plugins/manual.py
Commands: /manual_anime /manual_import /completed_task /edit_title
"""
from pyrogram import Client, filters
from pyrogram.types import Message

import database.anime as anime_db
import database.logs as logs_db
from database.mongo import get_db
from helper import dashboard, sheets
from helper.aliases import owner_only, rate_limited
from helper.manual import add_manual_anime, manual_complete_task


@Client.on_message(filters.command("manual_anime"))
@owner_only
@rate_limited
async def cmd_manual_anime(app: Client, msg: Message):
    """
    /manual_anime <Title> | <Year> | <Season> [| Type] [| MAL URL]
    """
    raw   = " ".join(msg.command[1:])
    parts = [p.strip() for p in raw.split("|")]
    if len(parts) < 3:
        await msg.reply(
            "Usage: `/manual_anime <Title> | <Year> | <Season> [| Type] [| MAL URL]`\n\n"
            "Example:\n"
            "`/manual_anime Demon Slayer Movie | 2024 | winter | Movie | https://myanimelist.net/anime/12345`"
        )
        return

    title  = parts[0]
    season = parts[2].lower()
    try:
        year = int(parts[1])
    except ValueError:
        await msg.reply("❌ Year must be a number.")
        return
    if season not in ("winter", "spring", "summer", "fall"):
        await msg.reply("❌ Season must be: winter / spring / summer / fall")
        return

    doc = await add_manual_anime(
        title=title, year=year, season=season,
        anime_type=parts[3] if len(parts) > 3 else "TV",
        mal_url=parts[4] if len(parts) > 4 else None,
        added_by=msg.from_user.id,
    )
    await dashboard.upsert_anime_message(app, doc)
    await dashboard.update_all(app)
    await dashboard.log_event(
        app,
        f"✏️ **Manual Add:** {title} ({year} {season.title()})\n"
        f"By @{msg.from_user.username or msg.from_user.first_name}",
    )
    await sheets.sync_pending()
    await msg.reply(
        f"✅ **Manually Added**\n\n"
        f"🎬 **{title}**\n"
        f"📅 {year} {season.title()} | 🎭 {parts[3] if len(parts) > 3 else 'TV'}\n"
        f"🆔 `{doc['anime_id']}`\n\n"
        "Anime is now in the pending queue."
    )


@Client.on_message(filters.command("manual_import"))
@owner_only
@rate_limited
async def cmd_manual_import(app: Client, msg: Message):
    """
    /manual_import
    Title One | 2024 | winter
    Title Two | 2024 | winter | Movie
    """
    lines = msg.text.split("\n")[1:]
    if not lines:
        await msg.reply(
            "**Batch Manual Import**\n\n"
            "Send this command with entries below it, one per line:\n\n"
            "`/manual_import`\n"
            "`Anime Title One | 2024 | winter`\n"
            "`Anime Title Two | 2024 | winter | Movie`"
        )
        return

    status_msg = await msg.reply(f"⏳ Processing {len(lines)} entries…")
    saved, errors = [], []

    for i, line in enumerate(lines, 1):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 3:
            errors.append(f"Line {i}: too few fields — `{line}`")
            continue
        try:
            year = int(parts[1])
        except ValueError:
            errors.append(f"Line {i}: invalid year — `{line}`")
            continue
        season = parts[2].lower()
        if season not in ("winter", "spring", "summer", "fall"):
            errors.append(f"Line {i}: invalid season — `{line}`")
            continue
        doc = await add_manual_anime(
            title=parts[0], year=year, season=season,
            anime_type=parts[3] if len(parts) > 3 else "TV",
            added_by=msg.from_user.id,
        )
        saved.append(doc)

    for doc in saved:
        await dashboard.upsert_anime_message(app, doc)
    await dashboard.update_all(app)
    await sheets.sync_pending()

    report = f"✅ **Batch Import Complete**\n\n{len(saved)} saved"
    if errors:
        report += f"\n⚠️ {len(errors)} errors:\n" + "\n".join(errors[:10])
    await status_msg.edit(report)


@Client.on_message(filters.command("completed_task"))
@owner_only
@rate_limited
async def cmd_completed_task(app: Client, msg: Message):
    """/completed_task <anime_id> — force-complete any active task"""
    args = msg.command[1:]
    if not args:
        await msg.reply("Usage: `/completed_task <anime_id>`")
        return
    anime_id = args[0]
    ok, text = await manual_complete_task(anime_id, msg.from_user.id)
    if ok:
        anime = await anime_db.get_by_id(anime_id)
        title = anime["titles"]["display_title"] if anime else anime_id
        if anime:
            await dashboard.upsert_anime_message(app, anime)
        await dashboard.update_all(app)
        await dashboard.log_event(
            app,
            f"✅ **Force Completed:** {title}\n"
            f"By @{msg.from_user.username or msg.from_user.first_name}",
        )
        await sheets.sync_completed()
        await msg.reply(f"✅ **{title}** marked as completed.")
    else:
        await msg.reply(f"❌ {text}")


@Client.on_message(filters.command("edit_title"))
@owner_only
@rate_limited
async def cmd_edit_title(app: Client, msg: Message):
    """
    /edit_title <anime_id> <new title>
    Permanently locks the display title — never overwritten by imports.
    """
    args = msg.command[1:]
    if len(args) < 2:
        await msg.reply(
            "Usage: `/edit_title <anime_id> <new title>`\n"
            "Example: `/edit_title abc12345 Attack on Titan Final Season`\n\n"
            "⚠️ Once set, this title is permanently locked and will **never** be "
            "overwritten by future imports or MAL/AnimeSchedule updates."
        )
        return

    anime_id  = args[0]
    new_title = " ".join(args[1:]).strip()
    if not new_title:
        await msg.reply("❌ Title cannot be empty.")
        return

    db    = get_db()
    anime = await db.anime.find_one({"anime_id": anime_id, "deleted": {"$ne": True}})
    if not anime:
        await msg.reply("❌ Anime not found.")
        return

    old_title  = anime["titles"].get("display_title", "")
    was_locked = anime["titles"].get("owner_override", False)

    from datetime import datetime
    await db.anime.update_one(
        {"anime_id": anime_id},
        {"$set": {
            "titles.display_title": new_title,
            "titles.owner_override": True,
            "updated_at": datetime.utcnow(),
        }},
    )
    await logs_db.log_audit(
        str(msg.from_user.id), "title_edited",
        target=anime_id, old_value=old_title, new_value=new_title,
    )

    updated = await db.anime.find_one({"anime_id": anime_id})
    if updated:
        await dashboard.upsert_anime_message(app, updated)

    lock_note = "Re-locked ✅" if was_locked else "Now locked 🔒"
    await msg.reply(
        f"✅ Title updated ({lock_note})\n\n"
        f"Old: _{old_title}_\n"
        f"New: **{new_title}**\n\n"
        "This title will never be overwritten by imports or sync jobs."
    )
