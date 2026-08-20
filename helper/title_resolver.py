"""helper/title_resolver.py — Resolve anime titles via AniList."""
from __future__ import annotations
import logging
import re
from typing import Optional
import httpx

logger = logging.getLogger(__name__)
ANILIST_URL = "https://graphql.anilist.co"
_QUERY = """query ($search: String) {
  Media(search: $search, type: ANIME, sort: SEARCH_MATCH) {
    title { romaji english }
  }
}"""

_mem: dict = {}
_client: Optional[httpx.AsyncClient] = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(timeout=10, headers={
            "Content-Type": "application/json", "Accept": "application/json"
        })
    return _client


async def resolve(title: str) -> str:
    if not title or not title.strip():
        return title
    title = title.strip()
    key   = title.lower()
    if key in _mem:
        return _mem[key]
    result = await _from_anilist(title) or title
    _mem[key] = result
    return result


async def _from_anilist(title: str) -> Optional[str]:
    try:
        r = await _http().post(ANILIST_URL, json={
            "query": _QUERY, "variables": {"search": title}
        })
        r.raise_for_status()
        data    = r.json()
        media   = (data.get("data") or {}).get("Media") or {}
        titles  = media.get("title") or {}
        english = (titles.get("english") or "").strip()
        romaji  = (titles.get("romaji")  or "").strip()
        if not english:
            return None
        if romaji and not _loose_match(title, romaji):
            return None
        return english
    except Exception as exc:
        logger.debug("TitleResolver AniList error for '%s': %s", title, exc)
        return None


def _loose_match(a: str, b: str, threshold: float = 0.72) -> bool:
    na = re.sub(r"[^a-z0-9]", "", a.lower())
    nb = re.sub(r"[^a-z0-9]", "", b.lower())
    if not na or not nb:
        return False
    if na in nb or nb in na:
        return True
    def bigrams(s):
        return {s[i:i+2] for i in range(len(s)-1)} if len(s) >= 2 else set()
    ba, bb = bigrams(na), bigrams(nb)
    if not ba or not bb:
        return False
    return len(ba & bb) / len(ba | bb) >= threshold
