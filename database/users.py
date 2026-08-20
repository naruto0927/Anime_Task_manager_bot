"""database/users.py — Users collection DB operations."""
from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Optional

from database.mongo import get_db


async def get_by_id(telegram_id: int) -> Optional[Dict]:
    return await get_db().users.find_one({"telegram_id": telegram_id})


async def get_by_username(username: str) -> Optional[Dict]:
    return await get_db().users.find_one({"username": username})


async def upsert_on_start(telegram_id: int, username: str, full_name: str) -> None:
    db = get_db()
    # Claim pre-registration if exists
    if username:
        pre = await db.users.find_one({"username": username, "pre_registered": True})
        if pre:
            await db.users.update_one(
                {"username": username},
                {"$set": {
                    "telegram_id": telegram_id,
                    "full_name": full_name,
                    "pre_registered": False,
                    "last_active": datetime.utcnow(),
                }},
            )
            return
    await db.users.update_one(
        {"telegram_id": telegram_id},
        {
            "$setOnInsert": {
                "telegram_id": telegram_id,
                "role": "admin",
                "task_limit": 5,
                "is_away": False,
                "active_task_count": 0,
                "completed_count": 0,
                "encoded_count": 0,
                "leeched_count": 0,
                "invalid_count": 0,
                "joined_at": datetime.utcnow(),
            },
            "$set": {
                "username": username,
                "full_name": full_name,
                "last_active": datetime.utcnow(),
            },
        },
        upsert=True,
    )


async def set_away(telegram_id: int, away: bool) -> None:
    upd = {"is_away": away}
    if away:
        upd["away_since"] = datetime.utcnow()
    else:
        upd["away_since"] = None
    await get_db().users.update_one({"telegram_id": telegram_id}, {"$set": upd})


async def increment(telegram_id: int, **fields) -> None:
    await get_db().users.update_one(
        {"telegram_id": telegram_id},
        {"$inc": fields, "$set": {"last_active": datetime.utcnow()}},
    )


async def set_role(username: str, role: str) -> bool:
    result = await get_db().users.update_one(
        {"username": username}, {"$set": {"role": role}}
    )
    return result.matched_count > 0


async def list_admins() -> List[Dict]:
    return [u async for u in get_db().users.find(
        {"role": "admin"}, sort=[("completed_count", -1)]
    )]


async def set_task_limit(username: str, limit: int) -> bool:
    result = await get_db().users.update_one(
        {"username": username}, {"$set": {"task_limit": limit}}
    )
    return result.matched_count > 0
