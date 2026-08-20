"""plugins/search.py — /find /franchise /mystats"""
import logging
from typing import Dict

from pyrogram import Client, filters
from pyrogram.types import Message

from helper.aliases import admin_or_owner, rate_limited
from helper.franchise import get_franchise_info
from helper.search import search_anime, search_franchise
from helper.stats import user_stats
from helper.theme import SEP_BOLD, SEASON_EMOJI, STATUS_EMOJI, PRIORITY, progress_bar

logger = logging.getLogger(__name__)

RELATION_LABEL = {
    "PREQUEL":     "⬅️ Prequel",
    "SEQUEL":      "➡️ Sequel",
    "SIDE_STORY":  "🔀 Side Story",
    "ALTERNATIVE": "🔁 Alternative",
    "SPIN_OFF":    "↪️ Spin-off",
    "PARENT":      "⬆️ Parent Story",
    "OTHER":       "🔗 Related",
}


@Client.on_message(filters.command("find"))
@admin_or_owner
@rate_limited
async def cmd_find(app: Client, msg: Message):
    query = " ".join(msg.command[1:]).strip()
    if not query:
        await msg.reply(
            "🔍 **Search Anime**\n"
            f"{SEP_BOLD}\n"
            "Usage: `/find <title>`\n\n"
            "Examples:\n"
            "  `/find frieren`\n"
            "  `/find re:zero`\n"
            "  `/find 21`  ← by AniList ID"
        )
        return

    results = await search_anime(query, limit=5)
    if not results:
        await msg.reply(
            f"🔍 No results for `{query}`\n\n"
            "Try: partial title · Romaji · AniList ID"
        )
        return

    lines = [f"🔍 **Results** for `{query}`\n{SEP_BOLD}"]
    for a in results:
        titles  = a.get("titles") or {}
        title   = titles.get("display_title", "Unknown")
        status  = a.get("status", "pending")
        emoji   = STATUS_EMOJI.get(status, "❓")
        url     = a.get("anilist_url") or ""
        link    = f"[{title}]({url})" if url else f"**{title}**"
        ep      = a.get("episode_count")
        fmt     = a.get("anime_type", "TV")
        season  = a.get("season", "")
        s_emoji = SEASON_EMOJI.get(season, "📅")
        ep_str  = f" · {ep}ep" if ep else ""
        fr_str  = f"\n   📺 {a['franchise_name']}" if a.get("franchise_name") else ""
        al_id   = a.get("anilist_id") or "—"
        aid     = (a.get("anime_id") or "")[:8]
        lines.append(
            f"{emoji} {link}\n"
            f"   {s_emoji} {a.get('year','?')} {season.title()} · {fmt}{ep_str}{fr_str}\n"
            f"   `{aid}` · AL:`{al_id}` · _{status.title()}_"
        )

    await msg.reply("\n\n".join(lines), disable_web_page_preview=True)


@Client.on_message(filters.command("franchise"))
@admin_or_owner
@rate_limited
async def cmd_franchise(app: Client, msg: Message):
    query = " ".join(msg.command[1:]).strip()
    if not query:
        await msg.reply(
            "📺 **Franchise Lookup**\n"
            f"{SEP_BOLD}\n"
            "Usage: `/franchise <name>`\n"
            "Example: `/franchise re:zero`"
        )
        return

    fr = await search_franchise(query)
    if not fr:
        await msg.reply(f"❌ Franchise not found: `{query}`")
        return

    info = await get_franchise_info(fr["franchise_id"])
    if not info:
        await msg.reply("Franchise found but no entries in database.")
        return

    entries   = sorted(info.get("anime_entries", []),
                       key=lambda x: (x.get("year", 0), x.get("season", "")))
    total     = len(entries)
    completed = sum(1 for e in entries if e["status"] == "completed")
    pct       = f"{round(completed/total*100)}%" if total else "0%"
    bar       = progress_bar(completed, total)
    lock_str  = "🔒 **Locked**" if info.get("has_active_assignment") else "🔓 Free"

    entry_lines = []
    for e in entries:
        emoji    = STATUS_EMOJI.get(e["status"], "❓")
        assignee = f" → @{e['assignee']}" if e.get("assignee") else ""
        url      = e.get("anilist_url", "")
        title    = e["title"]
        link     = f"[{title}]({url})" if url else f"**{title}**"
        ep       = f" · {e['episode_count']}ep" if e.get("episode_count") else ""
        s_emoji  = SEASON_EMOJI.get(e.get("season", ""), "📅")
        entry_lines.append(
            f"  {emoji} {link}{ep}\n"
            f"     {s_emoji} {e.get('year','?')} {e.get('season','').title()}{assignee}"
        )

    # Collect unique relations across all entries
    seen_rels: Dict[str, set] = {}
    for e in entries:
        for rel in (e.get("relations") or []):
            rtype = rel.get("relation", "OTHER")
            if rtype not in RELATION_LABEL:
                continue
            seen_rels.setdefault(rtype, set())
            t = rel.get("title", "")
            if t:
                seen_rels[rtype].add(t)

    rel_lines = []
    for rtype in ["PREQUEL", "SEQUEL", "SIDE_STORY", "ALTERNATIVE", "SPIN_OFF"]:
        if rtype in seen_rels:
            label = RELATION_LABEL[rtype]
            for t in seen_rels[rtype]:
                rel_lines.append(f"  {label}: **{t}**")

    text = (
        f"📺 **{info.get('name', fr['franchise_id'])}**\n"
        f"{SEP_BOLD}\n"
        f"Lock: {lock_str} · Progress: {bar} {pct} ({completed}/{total})\n"
        f"{SEP_BOLD}\n"
        f"**Entries:**\n"
        + ("\n".join(entry_lines) if entry_lines else "  No entries.")
    )
    if rel_lines:
        text += f"\n{SEP_BOLD}\n**Related Works:**\n" + "\n".join(rel_lines)

    await msg.reply(text, disable_web_page_preview=True)


@Client.on_message(filters.command("mystats"))
@admin_or_owner
@rate_limited
async def cmd_mystats(app: Client, msg: Message):
    try:
        stats = await user_stats(msg.from_user.id)
        if not stats:
            await msg.reply("No stats yet. Use /nexttask to get started!")
            return

        away_str = "😴 Away" if stats["is_away"] else "🟢 Active"
        avg_str  = f"\n⏱️ Avg: **{stats['avg_completion_hours']}h**" if stats.get("avg_completion_hours") else ""
        bar      = progress_bar(stats["active_tasks"], stats["task_limit"])
        joined   = stats["joined_at"].strftime("%Y-%m-%d") if stats.get("joined_at") else "—"

        await msg.reply(
            f"📊 **Statistics**\n"
            f"{SEP_BOLD}\n"
            f"👤 @{stats['username']} · {away_str}\n"
            f"{SEP_BOLD}\n"
            f"✅ Completed: **{stats['completed']}**\n"
            f"📦 Encoded:   **{stats['encoded']}**\n"
            f"🔗 Leeched:   **{stats['leeched']}**\n"
            f"❌ Invalid:   **{stats['invalid']}**{avg_str}\n"
            f"{SEP_BOLD}\n"
            f"🎯 Tasks: **{stats['active_tasks']}/{stats['task_limit']}**  {bar}\n"
            f"📅 Since: {joined}"
        )
    except Exception as e:
        logger.exception("/mystats error")
        await msg.reply(f"⚠️ `{e}`")
