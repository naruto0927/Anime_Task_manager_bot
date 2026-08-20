"""
helper/theme.py — Ocean Dark theme constants.
All UI text, separators, and emoji sets live here so the entire
bot visual identity can be changed in one file.
"""

# ── Separators ─────────────────────────────────────────────────────────────
SEP      = "▰▱▰▱▰▱▰▱▰▱▰▱▰▱▰▱"   # main separator
SEP_THIN = "─" * 24                # thin line
SEP_BOLD = "━" * 24                # bold line

# ── Status ─────────────────────────────────────────────────────────────────
STATUS = {
    "pending":   "🔵 Pending",
    "assigned":  "🟣 Assigned",
    "encoded":   "🟠 Encoded",
    "leeched":   "🟡 Leeched",
    "completed": "🟢 Completed",
    "invalid":   "🔴 Invalid",
    "dropped":   "⚫ Dropped",
}
STATUS_EMOJI = {k: v.split()[0] for k, v in STATUS.items()}

# ── Priority ───────────────────────────────────────────────────────────────
PRIORITY = {"high": "🔴 HIGH", "medium": "🟡 MED", "low": "🟢 LOW"}
PRIORITY_EMOJI = {"high": "🔴", "medium": "🟡", "low": "🟢"}

# ── Season ─────────────────────────────────────────────────────────────────
SEASON_EMOJI = {"spring": "🌸", "summer": "☀️", "fall": "🍂", "winter": "❄️"}

# ── Task card ──────────────────────────────────────────────────────────────
def task_card(anime: dict, status: str = None, extra_line: str = "") -> str:
    titles   = anime.get("titles") or {}
    title    = titles.get("display_title", "Unknown")
    url      = anime.get("anilist_url") or anime.get("mal_url") or ""
    link     = f"[{title}]({url})" if url else f"**{title}**"
    prio     = anime.get("priority", "medium")
    prio_str = PRIORITY.get(prio, prio.upper())
    ep_str   = f" · {anime['episode_count']}ep" if anime.get("episode_count") else ""
    fmt      = anime.get("anime_type", "TV")
    season   = anime.get("season", "")
    s_emoji  = SEASON_EMOJI.get(season, "📅")
    studio   = anime.get("studio", "")
    fr_name  = anime.get("franchise_name", "")
    status_s = STATUS.get(status or anime.get("status", "pending"), "")
    country  = anime.get("country", "")
    cn_tag   = " 🇨🇳" if country == "CN" else ""

    lines = [
        f"🎯 **Assignment**",
        SEP_BOLD,
        f"🎬 {link}{cn_tag}",
        f"{s_emoji} {anime.get('year', '?')} {season.title()} · {fmt}{ep_str}",
    ]
    if studio:
        lines.append(f"🏢 {studio}")
    if fr_name:
        lines.append(f"📺 {fr_name}")
    lines += [
        f"⚡ {prio_str}",
        f"📌 `{(anime.get('anime_id') or '')[:8]}`",
    ]
    if status_s:
        lines.append(f"◈ {status_s}")
    if extra_line:
        lines.append(extra_line)
    lines.append(SEP_BOLD)
    return "\n".join(lines)


def progress_bar(value: int, maximum: int, width: int = 12) -> str:
    if maximum <= 0:
        return "○" * width
    filled = round((min(value, maximum) / maximum) * width)
    return "●" * filled + "○" * (width - filled)
