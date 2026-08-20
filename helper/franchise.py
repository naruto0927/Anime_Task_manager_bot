"""helper/franchise.py — Franchise detection and management logic."""
from __future__ import annotations
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz, process

import database.anime as anime_db
import database.assignments as assign_db
import database.franchises as fr_db
import database.users as users_db
from database.settings import get_int

logger = logging.getLogger(__name__)

_SEASON_STRIP = [
    r"\bSeason\s+\d+\b", r"\b\d+(st|nd|rd|th)\s+Season\b",
    r"\bPart\s+\d+\b", r"\bCour\s+\d+\b", r"\bChapter\s+\d+\b",
    r"\bMovie\b", r"\bOVA\b", r"\bONA\b", r"\bSpecial\b", r"\bRecap\b",
    r":.*$", r"\s+S\d+$", r"\s+II+$", r"\s+\d+$",
]


def generate_slug(title: str) -> str:
    cleaned = title
    for p in _SEASON_STRIP:
        cleaned = re.sub(p, "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    slug = re.sub(r"[^a-z0-9 ]", "", cleaned.lower())
    return re.sub(r"\s+", "_", slug).strip("_")


async def detect_franchise(raw_mal_item: Dict[str, Any]) -> Optional[str]:
    """Return existing franchise_id for a MAL item, or None."""
    mal_id = raw_mal_item.get("id")
    title  = raw_mal_item.get("title", "")

    # 1. MAL related anime
    for rel in (raw_mal_item.get("related_anime") or []):
        rel_id = (rel.get("node") or {}).get("id")
        if rel_id:
            from database.mongo import get_db
            existing = await get_db().anime.find_one(
                {"mal_id": rel_id, "franchise_id": {"$exists": True, "$ne": None}}
            )
            if existing:
                return existing["franchise_id"]

    # 2. DB slug / alias / mal_id
    slug = generate_slug(title)
    fr = await fr_db.get(slug)
    if fr:
        return fr["franchise_id"]
    fr = await fr_db.find_by_alias(title)
    if fr:
        return fr["franchise_id"]
    if mal_id:
        fr = await fr_db.find_by_mal_id(mal_id)
        if fr:
            return fr["franchise_id"]

    # 3. Fuzzy
    threshold = await get_int("rapidfuzz_threshold", 90)
    all_fr = await fr_db.list_all()
    if not all_fr:
        return None
    candidates = []
    for f in all_fr:
        candidates.append((f["canonical_name"], f["franchise_id"]))
        for alias in f.get("aliases", []):
            candidates.append((alias, f["franchise_id"]))
    names = [c[0] for c in candidates]
    result = process.extractOne(slug, names, scorer=fuzz.ratio)
    if result and result[1] >= threshold:
        idx = names.index(result[0])
        return candidates[idx][1]

    return None


async def ensure_franchise(anime_doc: Dict) -> str:
    """Ensure a franchise exists for the anime. Returns franchise_id."""
    franchise_id = anime_doc.get("franchise_id")
    if not franchise_id:
        title = (anime_doc["titles"].get("display_title")
                 or anime_doc["titles"].get("title_romaji", ""))
        franchise_id = generate_slug(title) or str(uuid.uuid4())[:8]

    title = anime_doc["titles"].get("display_title", "")
    mal_id = anime_doc.get("mal_id")
    await fr_db.upsert(franchise_id, title, anime_doc["anime_id"], mal_id)

    from database.mongo import get_db
    await get_db().anime.update_one(
        {"anime_id": anime_doc["anime_id"]},
        {"$set": {"franchise_id": franchise_id}},
    )
    return franchise_id


async def get_franchise_info(franchise_id: str) -> Optional[Dict]:
    from database.mongo import get_db
    fr = await fr_db.get(franchise_id)
    if not fr:
        return None
    db = get_db()
    entries = []
    async for a in db.anime.find({"franchise_id": franchise_id, "deleted": {"$ne": True}}):
        assignment = await assign_db.get_active(a["anime_id"])
        username = None
        if assignment:
            user = await users_db.get_by_id(assignment["user_id"])
            username = user["username"] if user else str(assignment["user_id"])
        entries.append({
            "anime_id":      a["anime_id"],
            "title":         (a.get("titles") or {}).get("display_title", "Unknown"),
            "status":        a.get("status", "pending"),
            "assignee":      username,
            "year":          a.get("year"),
            "season":        a.get("season", ""),
            "episode_count": a.get("episode_count"),
            "anilist_url":   a.get("anilist_url", ""),
            "relations":     a.get("relations", []),
        })
    fr["anime_entries"] = entries
    return fr
