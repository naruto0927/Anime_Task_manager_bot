"""database/assignments.py — Assignments collection DB operations."""
from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Optional

from database.mongo import get_db

ACTIVE_STATUSES = ["assigned", "encoded", "leeched"]
CLOSED_STATUSES = ["completed", "dropped", "expired"]


async def get_active(anime_id: str) -> Optional[Dict]:
    return await get_db().assignments.find_one({
        "anime_id": anime_id,
        "status": {"$nin": CLOSED_STATUSES},
    })


async def get_user_active(user_id: int) -> List[Dict]:
    return [a async for a in get_db().assignments.find(
        {"user_id": user_id, "status": {"$in": ACTIVE_STATUSES}},
        sort=[("assigned_at", 1)],
    )]


async def count_user_active(user_id: int) -> int:
    return await get_db().assignments.count_documents(
        {"user_id": user_id, "status": {"$in": ACTIVE_STATUSES}}
    )


async def insert(doc: Dict) -> None:
    await get_db().assignments.insert_one(doc)


async def set_status(assignment_id: str, status: str,
                     extra: Optional[Dict] = None) -> None:
    upd: Dict = {"status": status}
    if extra:
        upd.update(extra)
    now = datetime.utcnow()
    await get_db().assignments.update_one(
        {"assignment_id": assignment_id},
        {
            "$set": upd,
            "$push": {
                "history": {
                    "status": status,
                    "timestamp": now.isoformat(),
                    "by": "system",
                }
            },
        },
    )


async def expire_old() -> List[Dict]:
    """Return list of {anime_id, user_id, title} for all expired assignments."""
    db = get_db()
    now = datetime.utcnow()
    expired = []

    async for a in db.assignments.find({
        "status": "assigned",
        "reserved": {"$ne": True},
        "expires_at": {"$lte": now},
    }):
        expired.append(a)

    async for a in db.assignments.find({
        "reserved": True,
        "status": "assigned",
        "reserved_until": {"$lte": now},
    }):
        expired.append(a)

    return expired


async def add_note(assignment_id: str, note: str) -> None:
    await get_db().assignments.update_one(
        {"assignment_id": assignment_id},
        {"$push": {"notes": note}},
    )


async def find_completed(limit: int = 10) -> List[Dict]:
    return [a async for a in get_db().assignments.find(
        {"status": "completed"},
        sort=[("completed_at", -1)],
    ).limit(limit)]
