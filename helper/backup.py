"""helper/backup.py — Backup logic."""
from __future__ import annotations
import io
import json
import logging
import uuid
import zipfile
from datetime import datetime
from typing import Any

from pyrogram import Client

import database.backups as backup_db
from database.mongo import get_db
from database.settings import get as cfg_get
from helper.aliases import _owner_ids

logger = logging.getLogger(__name__)

COLLECTIONS = [
    "users", "anime", "franchises", "assignments",
    "activity_logs", "audit_logs", "telegram_messages",
    "config", "dropped",
]


async def run_backup(app: Client) -> bool:
    db        = get_db()
    backup_id = str(uuid.uuid4())[:8]
    now       = datetime.utcnow()
    filename  = f"anime_backup_{now.strftime('%Y%m%d_%H%M%S')}_{backup_id}.zip"

    await backup_db.insert(backup_id, filename, COLLECTIONS)

    try:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for col_name in COLLECTIONS:
                docs = []
                async for doc in db[col_name].find({}):
                    doc["_id"] = str(doc["_id"])
                    docs.append(_serialize(doc))
                zf.writestr(f"{col_name}.json",
                            json.dumps(docs, ensure_ascii=False, default=str))

        size = buf.tell()
        buf.seek(0)

        ch_val = await cfg_get("backup_channel")
        if not ch_val:
            raise RuntimeError("Backup channel not configured. Use /setbackupchannel.")
        channel_id = int(ch_val)

        caption = (
            f"💾 **Backup**\n"
            f"ID: `{backup_id}`\n"
            f"Time: {now.strftime('%Y-%m-%d %H:%M UTC')}\n"
            f"Size: {size // 1024:.0f} KB\n"
            f"Collections: {len(COLLECTIONS)}"
        )
        msg = await app.send_document(
            channel_id, buf,
            file_name=filename,
            caption=caption,
        )
        await backup_db.mark_success(backup_id, size, msg.id, channel_id)
        logger.info("Backup complete: %s (%d KB)", backup_id, size // 1024)
        return True

    except Exception as e:
        logger.error("Backup failed: %s", e)
        await backup_db.mark_failed(backup_id, str(e))
        for oid in _owner_ids:
            try:
                await app.send_message(
                    oid, f"🚨 **Backup Failed**\n`{e}`"
                )
            except Exception:
                pass
        return False


def _serialize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(i) for i in obj]
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj
