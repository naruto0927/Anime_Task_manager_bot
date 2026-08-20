"""database/logs.py — Activity and audit log collections."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional

from database.mongo import get_db


async def log_activity(anime_id: str, user_id: int,
                       action: str, detail: Optional[str] = None) -> None:
    await get_db().activity_logs.insert_one({
        "log_id":    str(uuid.uuid4()),
        "anime_id":  anime_id,
        "user_id":   user_id,
        "action":    action,
        "detail":    detail,
        "timestamp": datetime.utcnow(),
    })


async def log_audit(user: str, action: str,
                    target: Optional[str] = None,
                    old_value: Optional[str] = None,
                    new_value: Optional[str] = None) -> None:
    await get_db().audit_logs.insert_one({
        "log_id":    str(uuid.uuid4()),
        "user":      user,
        "action":    action,
        "target":    target,
        "old_value": old_value,
        "new_value": new_value,
        "timestamp": datetime.utcnow(),
    })
