"""helper/animeschedule.py — animeschedule.net API client (simplified)."""
from __future__ import annotations
import logging
from typing import Optional
import httpx
from config import AS_TOKEN, AS_BASE_URL, AS_CDN_BASE, AS_NULL_DT

logger = logging.getLogger(__name__)
_API_URL = "https://animeschedule.net/api/v3/timetables"
_client: Optional[httpx.AsyncClient] = None


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        headers = {"Accept": "application/json"}
        if AS_TOKEN:
            headers["Authorization"] = f"Bearer {AS_TOKEN}"
        _client = httpx.AsyncClient(timeout=30, headers=headers)
    return _client


async def get_timetable(year: int, week: int) -> list:
    if not AS_TOKEN:
        return []
    try:
        r = await _http().get(_API_URL, params={"week": week, "year": year, "tz": "UTC"})
        if r.status_code != 200:
            logger.warning("animeschedule API %d", r.status_code)
            return []
        data = r.json()
        raw  = data if isinstance(data, list) else data.get("entries", [])
        return [e for e in raw if isinstance(e, dict)]
    except Exception as exc:
        logger.warning("animeschedule error: %s", exc)
        return []
