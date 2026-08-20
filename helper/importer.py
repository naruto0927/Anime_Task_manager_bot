"""helper/importer.py — AniList seasonal import."""
from __future__ import annotations
import asyncio
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import httpx
from rapidfuzz import fuzz

from database.mongo import get_db
from database.settings import get_bool, get_int
from helper.franchise import detect_franchise, ensure_franchise

logger = logging.getLogger(__name__)

ANILIST_URL   = "https://graphql.anilist.co"
VALID_SEASONS = {"winter", "spring", "summer", "fall"}
_SEASON_MAP   = {"winter": "WINTER", "spring": "SPRING",
                 "summer": "SUMMER", "fall": "FALL"}
_FORMAT_MAP   = {
    "TV": "TV", "TV_SHORT": "TV Short", "MOVIE": "Movie",
    "SPECIAL": "Special", "OVA": "OVA", "ONA": "ONA", "MUSIC": "Music",
}

_SEASON_QUERY = """
query ($season: MediaSeason, $year: Int, $page: Int) {
  Page(page: $page, perPage: 50) {
    pageInfo { hasNextPage }
    media(season: $season, seasonYear: $year, type: ANIME, sort: POPULARITY_DESC) {
      id
      title { romaji english native }
      format status episodes
      coverImage { large medium }
      description(asHtml: false)
      studios(isMain: true) { nodes { name } }
      genres
      tags { name rank isMediaSpoiler }
      countryOfOrigin
      siteUrl
      startDate { year month day }
      relations {
        edges {
          relationType(version: 2)
          node { id title { romaji english } type }
        }
      }
    }
  }
}
"""


@dataclass
class ImportStats:
    total_found: int = 0
    new: int = 0
    duplicates: int = 0
    ignored: int = 0
    dropped: int = 0
    items: List[Dict] = field(default_factory=list)
    duplicate_reasons: List[Dict] = field(default_factory=list)
    ignored_reasons: List[Dict] = field(default_factory=list)


async def import_season(year: int, season: str,
                        preview: bool = False) -> Tuple[ImportStats, List[Dict]]:
    season = season.lower()
    if season not in VALID_SEASONS:
        raise ValueError(f"Invalid season: {season}")
    raw = await _fetch_season_anilist(year, season)
    stats, items = await _process(raw, year, season)
    return stats, ([] if preview else items)


async def import_year(year: int,
                      preview: bool = False) -> Tuple[ImportStats, List[Dict]]:
    combined  = ImportStats()
    all_items: List[Dict] = []
    for s in ["winter", "spring", "summer", "fall"]:
        st, it = await import_season(year, s, preview)
        combined.total_found += st.total_found
        combined.new         += st.new
        combined.duplicates  += st.duplicates
        combined.ignored     += st.ignored
        combined.dropped     += st.dropped
        combined.items.extend(st.items)
        all_items.extend(it)
    return combined, all_items


async def confirm_import(items: List[Dict], keep_ids: List[str]) -> int:
    db    = get_db()
    saved = 0
    for item in items:
        if item["anime_id"] in keep_ids:
            try:
                await db.anime.insert_one(dict(item))   # dict() avoids mutating original
                await ensure_franchise(item)
                saved += 1
            except Exception as e:
                logger.warning("Failed to save %s: %s", item.get("anime_id"), e)
    logger.info("Import confirmed: %d anime saved", saved)
    return saved


# ── AniList Fetch ─────────────────────────────────────────────────────────

async def _fetch_season_anilist(year: int, season: str) -> List[Dict]:
    al_season = _SEASON_MAP[season]
    items: List[Dict] = []
    page = 1
    async with httpx.AsyncClient(timeout=30, headers={
        "Content-Type": "application/json",
        "Accept": "application/json",
    }) as client:
        while True:
            try:
                resp = await client.post(ANILIST_URL, json={
                    "query": _SEASON_QUERY,
                    "variables": {"season": al_season, "year": year, "page": page},
                })
                if resp.status_code == 429:
                    retry = int(resp.headers.get("Retry-After", "60"))
                    logger.warning("AniList rate limited, waiting %ds", retry)
                    await asyncio.sleep(retry)
                    continue
                resp.raise_for_status()
                data     = resp.json()
                page_obj = data.get("data", {}).get("Page", {})
                media    = page_obj.get("media", [])
                items.extend(media)
                if not page_obj.get("pageInfo", {}).get("hasNextPage"):
                    break
                page += 1
                await asyncio.sleep(0.6)
            except Exception as e:
                logger.error("AniList fetch error (page %d): %s", page, e)
                break
    logger.info("AniList: fetched %d entries for %s %d", len(items), season, year)
    return items


# ── Processing ────────────────────────────────────────────────────────────

async def _process(raw_items: List[Dict], year: int,
                   season: str) -> Tuple[ImportStats, List[Dict]]:
    stats  = ImportStats()
    review: List[Dict] = []

    ignore_donghua  = await get_bool("ignore_donghua",      False)
    ignore_specials = await get_bool("ignore_specials",     False)
    ignore_recaps   = await get_bool("ignore_recaps",       False)
    ignore_music    = await get_bool("ignore_music_videos", False)
    ignore_shorts   = await get_bool("ignore_shorts",       False)
    ignore_unknown  = await get_bool("ignore_unknown",      False)

    ignore_map = {
        "ignore_donghua":      ignore_donghua,
        "ignore_specials":     ignore_specials,
        "ignore_recaps":       ignore_recaps,
        "ignore_music_videos": ignore_music,
        "ignore_shorts":       ignore_shorts,
        "ignore_unknown":      ignore_unknown,
    }

    for raw in raw_items:
        stats.total_found += 1
        al_id     = raw.get("id")
        fmt       = (raw.get("format") or "UNKNOWN").upper()
        title_obj = raw.get("title") or {}
        title     = (title_obj.get("english") or title_obj.get("romaji") or str(al_id))

        reason = _check_ignore(raw, fmt, title, ignore_map)
        if reason:
            stats.ignored += 1
            stats.ignored_reasons.append({"al_id": al_id, "title": title, "reason": reason})
            continue

        dup = await _check_dup(al_id, title)
        if dup:
            stats.duplicates += 1
            stats.duplicate_reasons.append({"al_id": al_id, "title": title, "reason": dup})
            continue

        doc = await _build_doc(raw, year, season)
        stats.new += 1
        stats.items.append(doc)
        review.append(doc)

    return stats, review


def _check_ignore(raw: Dict, fmt: str, title: str,
                  ignore_map: Dict) -> Optional[str]:
    if ignore_map["ignore_specials"] and fmt == "SPECIAL":
        return "special"
    if ignore_map["ignore_music_videos"] and fmt == "MUSIC":
        return "music_video"
    if ignore_map["ignore_unknown"] and fmt == "UNKNOWN":
        return "unknown_type"
    if ignore_map["ignore_shorts"] and fmt == "TV_SHORT":
        return "short"
    if ignore_map["ignore_recaps"] and re.search(r"\brecap\b", title, re.IGNORECASE):
        return "recap"
    if ignore_map["ignore_donghua"]:
        country = (raw.get("countryOfOrigin") or "").upper()
        genres  = [str(g).lower() for g in (raw.get("genres") or [])]
        tags    = [str((t.get("name") if isinstance(t, dict) else t) or "").lower()
                   for t in (raw.get("tags") or [])]
        if (country == "CN"
                or "chinese animation" in genres
                or "donghua" in genres
                or "chinese animation" in tags):
            return "donghua"
    return None


async def _check_dup(al_id: Optional[int], title: str) -> Optional[str]:
    db = get_db()
    if al_id:
        if await db.anime.find_one({"anilist_id": al_id, "deleted": {"$ne": True}}):
            return f"duplicate_anilist_id:{al_id}"

    threshold = await get_int("rapidfuzz_threshold", 90)
    # Only compare display_title strings — never pass the whole doc
    existing_titles = await asyncio.to_thread(
        lambda: [
            (doc.get("titles") or {}).get("display_title", "")
            for doc in get_db()._db["anime"].find(
                {"deleted": {"$ne": True}},
                {"titles.display_title": 1}
            ).limit(500)
            if isinstance((doc.get("titles") or {}).get("display_title"), str)
        ]
    )
    for candidate in existing_titles:
        if candidate and fuzz.ratio(title, candidate) >= threshold:
            return f"fuzzy_match:{candidate}"
    return None


async def _build_doc(raw: Dict, year: int, season: str) -> Dict:
    db        = get_db()
    al_id     = raw.get("id")
    title_obj = raw.get("title") or {}
    title_en  = str(title_obj.get("english") or "").strip()
    title_rom = str(title_obj.get("romaji")  or "").strip()
    title_ja  = str(title_obj.get("native")  or "").strip()
    display   = title_en or title_rom or title_ja or str(al_id)

    # Franchise detection using AniList relations
    franchise_id   = await _detect_franchise_al(raw, db)
    franchise_name = None
    if franchise_id:
        fr = await db.franchises.find_one({"franchise_id": franchise_id})
        franchise_name = fr["name"] if fr else None

    # Studios — safe extract
    studios_obj = raw.get("studios") or {}
    nodes       = studios_obj.get("nodes") or [] if isinstance(studios_obj, dict) else []
    studios     = [n["name"] for n in nodes if isinstance(n, dict) and n.get("name")]

    fmt     = _FORMAT_MAP.get((raw.get("format") or "").upper(), "Unknown")
    cover   = raw.get("coverImage") or {}
    img_url = cover.get("large") or cover.get("medium") if isinstance(cover, dict) else None
    desc    = str(raw.get("description") or "")[:500]

    # AniList relations for prequel/sequel linking
    relations = _extract_relations(raw)

    aliases = list({title_en, title_rom, title_ja} - {""})

    return {
        "anime_id":       str(uuid.uuid4()),
        "anilist_id":     al_id,
        "mal_id":         None,
        "titles": {
            "title_en":       title_en,
            "title_romaji":   title_rom,
            "title_japanese": title_ja,
            "display_title":  display,
            "aliases":        aliases,
            "synonyms":       [],
            "owner_override": False,
        },
        "franchise_id":   franchise_id,
        "franchise_name": franchise_name,
        "year":           year,
        "season":         season,
        "anime_type":     fmt,
        "status":         "pending",
        "priority":       "medium",
        "episode_count":  raw.get("episodes"),
        "studio":         studios[0] if studios else None,
        "synopsis":       desc,
        "anilist_url":    raw.get("siteUrl"),
        "image_url":      img_url,
        "genres":         [str(g) for g in (raw.get("genres") or [])],
        "country":        raw.get("countryOfOrigin"),
        "relations":      relations,
        "notes":          [],
        "deleted":        False,
        "imported_at":    datetime.utcnow(),
        "updated_at":     datetime.utcnow(),
    }


def _extract_relations(raw: Dict) -> List[Dict]:
    """Extract prequel/sequel/side story relations from AniList response."""
    relations_obj = raw.get("relations") or {}
    edges         = relations_obj.get("edges") or [] if isinstance(relations_obj, dict) else []
    result        = []
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        rel_type = edge.get("relationType", "")
        node     = edge.get("node") or {}
        if not isinstance(node, dict):
            continue
        node_titles = node.get("title") or {}
        name = (str(node_titles.get("english") or node_titles.get("romaji") or "")).strip()
        if rel_type and name and node.get("type") == "ANIME":
            result.append({
                "al_id":    node.get("id"),
                "title":    name,
                "relation": rel_type,  # PREQUEL, SEQUEL, SIDE_STORY, etc.
            })
    return result


async def _detect_franchise_al(raw: Dict, db) -> Optional[str]:
    """Detect franchise by checking AniList relations against existing DB entries."""
    al_id    = raw.get("id")
    relations = _extract_relations(raw)

    # Check if any related anime already exists in DB with a franchise
    for rel in relations:
        rel_al_id = rel.get("al_id")
        if rel_al_id:
            existing = await db.anime.find_one(
                {"anilist_id": rel_al_id, "franchise_id": {"$exists": True, "$ne": None}}
            )
            if existing:
                return existing["franchise_id"]

    return None
