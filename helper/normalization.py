"""helper/normalization.py — Title normalisation and slug generation."""
from __future__ import annotations
import logging
import re
from typing import List, Optional

import aiohttp

logger = logging.getLogger(__name__)

ANIMESCHEDULE_BASE = "https://animeschedule.net/API/v3/anime"


async def resolve_display_title(mal_id: Optional[int], title_en: str,
                                 title_romaji: str,
                                 synonyms: List[str]) -> str:
    if title_en:
        return _clean(title_en)
    if mal_id:
        from database.settings import get_str
        api_key = await get_str("animeschedule_api_key", "")
        if api_key:
            result = await _fetch_animeschedule(mal_id, api_key)
            if result:
                return _clean(result)
    if title_romaji:
        return _clean(title_romaji)
    return _clean(synonyms[0]) if synonyms else "Unknown Title"


async def _fetch_animeschedule(mal_id: int, api_key: str) -> Optional[str]:
    try:
        url = f"{ANIMESCHEDULE_BASE}?malId={mal_id}"
        headers = {"Authorization": f"Bearer {api_key}"}
        async with aiohttp.ClientSession() as s:
            async with s.get(url, headers=headers,
                             timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status == 200:
                    data = await r.json()
                    if isinstance(data, list) and data:
                        return data[0].get("title")
    except Exception as e:
        logger.debug("AnimeSchedule fetch failed: %s", e)
    return None


def _clean(title: str) -> str:
    return re.sub(r"\s+", " ", title).strip()
