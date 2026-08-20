"""database/backups.py — Backup records collection."""
from __future__ import annotations
from datetime import datetime
from typing import Dict, Optional

from database.mongo import get_db


async def insert(backup_id: str, filename: str, collections: list) -> None:
    await get_db().backups.insert_one({
        "backup_id":   backup_id,
        "collections": collections,
        "file_name":   filename,
        "status":      "pending",
        "size_bytes":  0,
        "created_at":  datetime.utcnow(),
    })


async def mark_success(backup_id: str, size: int,
                       message_id: int, channel_id: int) -> None:
    await get_db().backups.update_one(
        {"backup_id": backup_id},
        {"$set": {
            "status":              "success",
            "size_bytes":          size,
            "telegram_message_id": message_id,
            "telegram_channel_id": channel_id,
            "verified_at":         datetime.utcnow(),
        }},
    )


async def mark_failed(backup_id: str, error: str) -> None:
    await get_db().backups.update_one(
        {"backup_id": backup_id},
        {"$set": {"status": "failed", "error": error}},
    )


async def get_latest_success() -> Optional[Dict]:
    return await get_db().backups.find_one(
        {"status": "success"}, sort=[("created_at", -1)]
    )
