"""database/dropped.py — Dropped anime collection."""
from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Optional

from database.mongo import get_db


async def add(anime_id: str, title: str, reason: str,
              dropped_by: int, original_data: Dict) -> None:
    await get_db().dropped.update_one(
        {"anime_id": anime_id},
        {"$set": {
            "anime_id": anime_id,
            "title": title,
            "reason": reason,
            "dropped_by": dropped_by,
            "date": datetime.utcnow(),
            "original_data": original_data,
        }},
        upsert=True,
    )


async def remove(anime_id: str) -> None:
    await get_db().dropped.delete_one({"anime_id": anime_id})


async def list_recent(limit: int = 20) -> List[Dict]:
    return [d async for d in get_db().dropped.find(
        {}, sort=[("date", -1)]
    ).limit(limit)]


async def count() -> int:
    return await get_db().dropped.count_documents({})
