"""helper/search.py — Anime and franchise search."""
from __future__ import annotations
import asyncio
import re
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz, process

from database.settings import get_int


def _db():
    from database.mongo import get_db
    return get_db()


async def search_anime(query: str, limit: int = 10,
                       include_dropped: bool = False) -> List[Dict]:
    db    = _db()
    query = query.strip()
    if not query:
        return []

    base: Dict[str, Any] = {"deleted": {"$ne": True}}
    if not include_dropped:
        base["status"] = {"$ne": "dropped"}

    results: List[Dict] = []
    seen:    set         = set()

    def _add(doc):
        aid = doc.get("anime_id")
        if aid and aid not in seen:
            results.append(doc)
            seen.add(aid)

    # 1. Direct AniList ID match
    if query.isdigit():
        doc = await db.anime.find_one({**base, "anilist_id": int(query)})
        if doc:
            _add(doc)
            return results

    # 2. Exact anime_id prefix
    if len(query) >= 6:
        doc = await db.anime.find_one({**base, "anime_id": {"$regex": f"^{re.escape(query)}"}})
        if doc:
            _add(doc)

    # 3. Case-insensitive regex across all title fields
    pat = re.compile(re.escape(query), re.IGNORECASE)
    async for doc in db.anime.find({
        **base,
        "$or": [
            {"titles.display_title":  pat},
            {"titles.title_en":       pat},
            {"titles.title_romaji":   pat},
            {"titles.title_japanese": pat},
            {"titles.aliases":        pat},
            {"titles.synonyms":       pat},
            {"franchise_name":        pat},
        ],
    }).limit(limit * 2):
        _add(doc)

    if len(results) >= limit:
        return results[:limit]

    # 4. Fuzzy fallback — pull display_title strings only
    threshold = await get_int("rapidfuzz_threshold", 72)
    raw_docs = await asyncio.to_thread(
        lambda: list(
            _db()._db["anime"]
            .find(base, {"titles.display_title": 1, "titles.title_romaji": 1,
                         "titles.title_en": 1, "anime_id": 1})
            .limit(800)
        )
    )

    candidates: Dict[str, str] = {}  # title_str → anime_id
    for doc in raw_docs:
        aid    = doc.get("anime_id", "")
        titles = doc.get("titles") or {}
        for fv in [titles.get("display_title"), titles.get("title_en"),
                   titles.get("title_romaji")]:
            if isinstance(fv, str) and fv and aid:
                candidates[fv] = aid

    if candidates:
        hits = process.extract(
            query, list(candidates.keys()),
            scorer=fuzz.partial_ratio, limit=limit * 2
        )
        hit_ids = []
        for hit_title, score, _ in hits:
            if score >= threshold:
                aid = candidates[hit_title]
                if aid not in seen:
                    hit_ids.append(aid)
                    seen.add(aid)

        if hit_ids:
            async for doc in db.anime.find({**base, "anime_id": {"$in": hit_ids}}).limit(limit):
                results.append(doc)

    return results[:limit]


async def search_franchise(query: str) -> Optional[Dict]:
    db    = _db()
    query = query.strip()
    if not query:
        return None

    # 1. Exact franchise_id
    fr = await db.franchises.find_one({"franchise_id": query.lower().replace(" ", "_")})
    if fr:
        return fr

    # 2. Regex on name fields
    pat = re.compile(re.escape(query), re.IGNORECASE)
    fr  = await db.franchises.find_one({
        "$or": [{"name": pat}, {"canonical_name": pat}, {"aliases": pat}]
    })
    if fr:
        return fr

    # 3. Also search anime titles to find franchise via anime
    anime_doc = await db.anime.find_one({
        "deleted": {"$ne": True},
        "$or": [
            {"titles.display_title": pat},
            {"franchise_name": pat},
        ]
    })
    if anime_doc and anime_doc.get("franchise_id"):
        fr = await db.franchises.find_one({"franchise_id": anime_doc["franchise_id"]})
        if fr:
            return fr

    # 4. Fuzzy
    best_score = 0
    best_fr    = None
    async for doc in db.franchises.find({}):
        for candidate in [doc.get("name", ""), doc.get("canonical_name", "")]:
            if not isinstance(candidate, str):
                continue
            score = fuzz.partial_ratio(query.lower(), candidate.lower())
            if score > best_score:
                best_score = score
                best_fr    = doc

    return best_fr if best_score >= 60 else None
