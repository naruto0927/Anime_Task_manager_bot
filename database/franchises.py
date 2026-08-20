"""database/franchises.py — Franchises collection DB operations."""
from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Optional

from database.mongo import get_db


async def get(franchise_id: str) -> Optional[Dict]:
    return await get_db().franchises.find_one({"franchise_id": franchise_id})


async def find_by_alias(title: str) -> Optional[Dict]:
    return await get_db().franchises.find_one({"aliases": {"$in": [title]}})


async def find_by_mal_id(mal_id: int) -> Optional[Dict]:
    return await get_db().franchises.find_one({"mal_ids": mal_id})


async def upsert(franchise_id: str, name: str, anime_id: str,
                 mal_id: Optional[int] = None) -> None:
    add_set: Dict = {"anime_ids": anime_id}
    if mal_id:
        add_set["mal_ids"] = mal_id
    await get_db().franchises.update_one(
        {"franchise_id": franchise_id},
        {
            "$setOnInsert": {
                "franchise_id": franchise_id,
                "canonical_name": franchise_id.replace("_", " ").title(),
                "created_at": datetime.utcnow(),
            },
            "$set": {"name": name, "updated_at": datetime.utcnow()},
            "$addToSet": add_set,
        },
        upsert=True,
    )


async def set_lock(franchise_id: str, locked: bool,
                   assignee_id: Optional[int] = None) -> None:
    await get_db().franchises.update_one(
        {"franchise_id": franchise_id},
        {"$set": {
            "has_active_assignment": locked,
            "active_assignee_id": assignee_id,
        }},
    )


async def is_locked(franchise_id: str) -> bool:
    fr = await get_db().franchises.find_one({"franchise_id": franchise_id})
    return bool(fr and fr.get("has_active_assignment"))


async def list_all() -> List[Dict]:
    return [f async for f in get_db().franchises.find({})]
