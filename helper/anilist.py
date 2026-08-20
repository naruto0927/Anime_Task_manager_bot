"""
services/anilist.py — AniList GraphQL API client.

Provides search (multi-result list), single best-match, detail-by-ID,
and full relation-chain walking for both anime and manga.

In-memory cache (per-process, not persisted) with a 10-minute TTL keeps
repeated lookups fast without hammering the free AniList API.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx

from config import ANILIST_API

logger = logging.getLogger(__name__)


class AniListAPI:
    """Async wrapper for the AniList GraphQL API."""

    URL: str = ANILIST_API

    # ── GraphQL Queries ───────────────────────────────────────────────────

    _ANIME_Q = """query($s:String){Media(search:$s,type:ANIME,sort:SEARCH_MATCH){
        id title{romaji english native}
        description(asHtml:false) episodes duration status format source
        averageScore genres
        coverImage{extraLarge large}
        bannerImage siteUrl
        season seasonYear
        startDate{year month day}
        endDate{year month day}
        trailer{site id}
        characters(sort:ROLE,perPage:6){nodes{name{full}image{medium}}}
        studios(isMain:true){nodes{name}}}}"""

    _MANGA_Q = """query($s:String){Media(search:$s,type:MANGA,sort:SEARCH_MATCH){
        id title{romaji english native}
        description(asHtml:false) chapters volumes status format source
        averageScore genres
        coverImage{extraLarge large}
        siteUrl
        startDate{year month day}
        endDate{year month day}
        trailer{site id}
        characters(sort:ROLE,perPage:6){nodes{name{full}image{medium}}}
        staff(sort:RELEVANCE){nodes{name{full}}}}}"""

    _ANIME_SEARCH_Q = """query($s:String){Page(perPage:8){
        media(search:$s,type:ANIME,sort:SEARCH_MATCH){
            id title{romaji english} format status episodes
            coverImage{extraLarge large medium} siteUrl startDate{year}}}}"""

    _MANGA_SEARCH_Q = """query($s:String){Page(perPage:8){
        media(search:$s,type:MANGA,sort:SEARCH_MATCH){
            id title{romaji english} format status chapters volumes
            coverImage{extraLarge large medium} siteUrl startDate{year}}}}"""

    _ANIME_BY_ID = """query($id:Int){Media(id:$id,type:ANIME){
        id title{romaji english native}
        description(asHtml:false) episodes duration status format source
        averageScore genres
        coverImage{extraLarge large}
        bannerImage siteUrl
        season seasonYear
        startDate{year month day}
        endDate{year month day}
        trailer{site id}
        characters(sort:ROLE,perPage:6){nodes{name{full}image{medium}}}
        studios(isMain:true){nodes{name}}}}"""

    _MANGA_BY_ID = """query($id:Int){Media(id:$id,type:MANGA){
        id title{romaji english native}
        description(asHtml:false) chapters volumes status format source
        averageScore genres
        coverImage{extraLarge large}
        siteUrl
        startDate{year month day}
        endDate{year month day}
        trailer{site id}
        characters(sort:ROLE,perPage:6){nodes{name{full}image{medium}}}
        staff(sort:RELEVANCE){nodes{name{full}}}}}"""

    _RELATIONS_Q = """query($id:Int){Media(id:$id){
        id title{romaji english}
        relations{edges{relationType node{
            id type title{romaji english} format status episodes
            averageScore startDate{year} siteUrl
        }}}}}"""

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None
        self._cache:  dict = {}   # {key: (value, expires_at)}

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=30,
                headers={
                    "Content-Type": "application/json",
                    "Accept":       "application/json",
                },
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── In-Memory Cache Helpers ───────────────────────────────────────────

    def _mem_get(self, key: str) -> Any:
        entry = self._cache.get(key)
        if entry and datetime.now(timezone.utc) < entry[1]:
            return entry[0]
        return None

    def _mem_set(self, key: str, value: Any, ttl: int = 600) -> None:
        self._cache[key] = (
            value,
            datetime.now(timezone.utc) + timedelta(seconds=ttl),
        )

    # ── Core GraphQL Request ──────────────────────────────────────────────

    async def _gql(self, query: str, search: str) -> Optional[dict]:
        cache_key = f"al:gql:{hash(query + search)}"
        cached    = self._mem_get(cache_key)
        if cached is not None:
            return cached
        try:
            r = await self.client.post(
                self.URL,
                json={"query": query, "variables": {"s": search}},
            )
            r.raise_for_status()
            data   = r.json()
            result = (
                data.get("data", {}).get("Media")
                if "errors" not in data else None
            )
            if result:
                self._mem_set(cache_key, result)
            return result
        except Exception as exc:
            logger.error("AniList error: %s", exc)
            return None

    # ── Single Best-Match Queries ─────────────────────────────────────────

    async def search_anime(self, q: str) -> Optional[dict]:
        return await self._gql(self._ANIME_Q, q)

    async def search_manga(self, q: str) -> Optional[dict]:
        return await self._gql(self._MANGA_Q, q)

    # ── Multi-Result List Queries ─────────────────────────────────────────

    async def search_anime_list(self, q: str) -> list:
        """Return up to 8 search results for inline buttons."""
        cache_key = f"al:list:anime:{q}"
        cached    = self._mem_get(cache_key)
        if cached is not None:
            return cached
        try:
            r = await self.client.post(
                self.URL,
                json={"query": self._ANIME_SEARCH_Q, "variables": {"s": q}},
            )
            r.raise_for_status()
            data   = r.json()
            result = (
                (data.get("data", {}).get("Page", {}).get("media") or [])
                if "errors" not in data else []
            )
            self._mem_set(cache_key, result)
            return result
        except Exception as exc:
            logger.error("AniList search list error: %s", exc)
            return []

    async def search_manga_list(self, q: str) -> list:
        """Return up to 8 manga search results for inline buttons."""
        cache_key = f"al:list:manga:{q}"
        cached    = self._mem_get(cache_key)
        if cached is not None:
            return cached
        try:
            r = await self.client.post(
                self.URL,
                json={"query": self._MANGA_SEARCH_Q, "variables": {"s": q}},
            )
            r.raise_for_status()
            data   = r.json()
            result = (
                (data.get("data", {}).get("Page", {}).get("media") or [])
                if "errors" not in data else []
            )
            self._mem_set(cache_key, result)
            return result
        except Exception as exc:
            logger.error("AniList manga search list error: %s", exc)
            return []

    # ── Detail by ID ──────────────────────────────────────────────────────

    async def get_anime_by_id(self, media_id: int) -> Optional[dict]:
        cache_key = f"al:id:anime:{media_id}"
        cached    = self._mem_get(cache_key)
        if cached is not None:
            return cached
        try:
            r = await self.client.post(
                self.URL,
                json={"query": self._ANIME_BY_ID, "variables": {"id": media_id}},
            )
            r.raise_for_status()
            data   = r.json()
            result = data.get("data", {}).get("Media") if "errors" not in data else None
            if result:
                self._mem_set(cache_key, result, ttl=300)
            return result
        except Exception as exc:
            logger.error("AniList get_anime_by_id error: %s", exc)
            return None

    async def get_manga_by_id(self, media_id: int) -> Optional[dict]:
        cache_key = f"al:id:manga:{media_id}"
        cached    = self._mem_get(cache_key)
        if cached is not None:
            return cached
        try:
            r = await self.client.post(
                self.URL,
                json={"query": self._MANGA_BY_ID, "variables": {"id": media_id}},
            )
            r.raise_for_status()
            data   = r.json()
            result = data.get("data", {}).get("Media") if "errors" not in data else None
            if result:
                self._mem_set(cache_key, result, ttl=300)
            return result
        except Exception as exc:
            logger.error("AniList get_manga_by_id error: %s", exc)
            return None

    # ── Relations ─────────────────────────────────────────────────────────

    async def _get_relations_raw(self, media_id: int) -> Optional[dict]:
        """Fetch a single media entry with its direct relations."""
        try:
            r = await self.client.post(
                self.URL,
                json={"query": self._RELATIONS_Q, "variables": {"id": media_id}},
            )
            r.raise_for_status()
            data = r.json()
            return data.get("data", {}).get("Media") if "errors" not in data else None
        except Exception as exc:
            logger.error("AniList relations error: %s", exc)
            return None

    async def get_full_relations(self, media_id: int) -> dict:
        """
        Walk the PREQUEL/SEQUEL chain recursively and collect all other relations.

        Returns::

            {
                "root":     {id, title, ...},
                "timeline": [(rel_type, node), ...],   # oldest prequel → newest sequel
                "other":    {relationType: [nodes], ...},
            }
        """
        visited:  set  = set()
        timeline: list = []
        other:    dict = {}

        async def walk(mid: int) -> None:
            if mid in visited:
                return
            visited.add(mid)
            data = await self._get_relations_raw(mid)
            if not data:
                return
            edges = (data.get("relations") or {}).get("edges") or []
            for edge in edges:
                rel_type = edge.get("relationType", "")
                node     = edge.get("node") or {}
                nid      = node.get("id")
                if not nid or node.get("type") not in (None, "ANIME", "MANGA"):
                    continue
                if rel_type in ("PREQUEL", "SEQUEL"):
                    if nid not in visited:
                        timeline.append((rel_type, node))
                        await walk(nid)
                elif rel_type in (
                    "SIDE_STORY", "SPIN_OFF", "ADAPTATION",
                    "ALTERNATIVE", "SUMMARY", "PARENT", "CHARACTER",
                ):
                    other.setdefault(rel_type, [])
                    if not any(n.get("id") == nid for n in other[rel_type]):
                        other[rel_type].append(node)

        root_data = await self._get_relations_raw(media_id)
        if not root_data:
            return {"root": None, "timeline": [], "other": {}}

        visited.add(media_id)
        edges = (root_data.get("relations") or {}).get("edges") or []
        for edge in edges:
            rel_type = edge.get("relationType", "")
            node     = edge.get("node") or {}
            nid      = node.get("id")
            if not nid:
                continue
            if rel_type in ("PREQUEL", "SEQUEL"):
                if nid not in visited:
                    timeline.append((rel_type, node))
                    await walk(nid)
            elif rel_type in (
                "SIDE_STORY", "SPIN_OFF", "ADAPTATION",
                "ALTERNATIVE", "SUMMARY", "PARENT", "CHARACTER",
            ):
                other.setdefault(rel_type, [])
                if not any(n.get("id") == nid for n in other[rel_type]):
                    other[rel_type].append(node)

        return {"root": root_data, "timeline": timeline, "other": other}
