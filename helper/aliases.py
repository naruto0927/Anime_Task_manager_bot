"""
helper/aliases.py — Permission decorators and rate limiter.

IMPORTANT: owner_ids are cached in-process from config.py at import time.
This means ZERO database calls for permission checks — no async, no threads,
no Motor issues, no timeout risk. Just a fast in-memory set lookup.

The DB-backed get_owner_ids() is still available for /panel and /help
display purposes, but NOT used in the hot path decorators.
"""
from __future__ import annotations
import functools
import logging
import time
from collections import defaultdict
from datetime import datetime

from pyrogram.types import Message

# ── In-memory owner cache — populated at startup from config.py ───────────
# This is a module-level set so permission checks are instant, sync, and
# never touch the database or event loop.
_owner_ids: set[int] = set()


def init_owners(*ids: int) -> None:
    """Call once at startup with owner IDs from config.py."""
    _owner_ids.update(ids)


def is_owner(user_id: int) -> bool:
    return user_id in _owner_ids


logger = logging.getLogger(__name__)
_rate_buckets: dict = defaultdict(list)
_WINDOW = 60
_MAX    = 20


def _check_rate(user_id: int) -> bool:
    now = time.time()
    _rate_buckets[user_id] = [t for t in _rate_buckets[user_id] if now - t < _WINDOW]
    if len(_rate_buckets[user_id]) >= _MAX:
        return False
    _rate_buckets[user_id].append(now)
    return True


def owner_only(func):
    @functools.wraps(func)
    async def wrapper(app, msg: Message, *a, **kw):
        try:
            if not msg.from_user:
                return
            if not is_owner(msg.from_user.id):
                await msg.reply("⛔ Owner only.")
                return
            return await func(app, msg, *a, **kw)
        except Exception as e:
            logger.exception("Error in %s: %s", func.__name__, e)
            try:
                await msg.reply(f"⚠️ `{func.__name__}` error:\n`{type(e).__name__}: {e}`")
            except Exception:
                pass
    return wrapper


def admin_or_owner(func):
    @functools.wraps(func)
    async def wrapper(app, msg: Message, *a, **kw):
        try:
            if not msg.from_user:
                return
            user_id = msg.from_user.id

            # Owners always pass
            if is_owner(user_id):
                return await func(app, msg, *a, **kw)

            # Check DB for registered admins
            from database.mongo import get_db
            db = get_db()
            db_user = await db.users.find_one({"telegram_id": user_id})

            if not db_user:
                # Try claiming pre-registration by username
                username = msg.from_user.username or ""
                if username:
                    pre = await db.users.find_one({"username": username, "pre_registered": True})
                    if pre:
                        await db.users.update_one(
                            {"username": username},
                            {"$set": {
                                "telegram_id":    user_id,
                                "full_name":      msg.from_user.full_name or "",
                                "pre_registered": False,
                                "joined_at":      datetime.utcnow(),
                                "last_active":    datetime.utcnow(),
                            }},
                        )
                        return await func(app, msg, *a, **kw)
                await msg.reply("⛔ Not registered. Contact an owner.")
                return

            if db_user.get("role") == "removed":
                await msg.reply("⛔ Your access has been revoked.")
                return

            return await func(app, msg, *a, **kw)
        except Exception as e:
            logger.exception("Error in %s: %s", func.__name__, e)
            try:
                await msg.reply(f"⚠️ `{func.__name__}` error:\n`{type(e).__name__}: {e}`")
            except Exception:
                pass
    return wrapper


def rate_limited(func):
    @functools.wraps(func)
    async def wrapper(app, msg: Message, *a, **kw):
        try:
            if msg.from_user and not _check_rate(msg.from_user.id):
                await msg.reply("⏱️ Slow down!")
                return
            return await func(app, msg, *a, **kw)
        except Exception as e:
            logger.exception("Error in %s: %s", func.__name__, e)
            try:
                await msg.reply(f"⚠️ `{func.__name__}` error:\n`{type(e).__name__}: {e}`")
            except Exception:
                pass
    return wrapper
