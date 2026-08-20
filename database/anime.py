"""database/anime.py — Anime collection DB operations."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional

from database.mongo import get_db


async def get_by_id(anime_id: str) -> Optional[Dict]:
    return await get_db().anime.find_one({"anime_id": anime_id})


async def get_by_mal_id(mal_id: int) -> Optional[Dict]:
    return await get_db().anime.find_one({"mal_id": mal_id, "deleted": {"$ne": True}})


async def upsert(doc: Dict) -> None:
    db = get_db()
    await db.anime.update_one(
        {"anime_id": doc["anime_id"]},
        {"$set": doc},
        upsert=True,
    )


async def set_status(anime_id: str, status: str, **extra) -> None:
    await get_db().anime.update_one(
        {"anime_id": anime_id},
        {"$set": {"status": status, "updated_at": datetime.utcnow(), **extra}},
    )


async def soft_delete(anime_id: str) -> None:
    await get_db().anime.update_one(
        {"anime_id": anime_id},
        {"$set": {"deleted": True, "deleted_at": datetime.utcnow()}},
    )


async def restore(anime_id: str) -> None:
    await get_db().anime.update_one(
        {"anime_id": anime_id},
        {"$set": {"deleted": False, "status": "pending", "updated_at": datetime.utcnow()}},
    )


async def find_pending(limit: int = 50, priority: Optional[str] = None,
                       exclude_ids: Optional[List[str]] = None) -> List[Dict]:
    filt: Dict[str, Any] = {"status": "pending", "deleted": {"$ne": True}}
    if priority:
        filt["priority"] = priority
    if exclude_ids:
        filt["anime_id"] = {"$nin": exclude_ids}
    cursor = get_db().anime.find(filt).limit(limit)
    return [doc async for doc in cursor]


async def find_by_season(season: str, year: int, status: Optional[str] = None) -> List[Dict]:
    filt: Dict[str, Any] = {"season": season, "year": year, "deleted": {"$ne": True}}
    if status:
        filt["status"] = status
    return [doc async for doc in get_db().anime.find(filt)]


async def count_by_status() -> Dict[str, int]:
    pipeline = [
        {"$match": {"deleted": {"$ne": True}}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
    ]
    counts: Dict[str, int] = {}
    async for row in get_db().anime.aggregate(pipeline):
        counts[row["_id"]] = row["count"]
    return counts
