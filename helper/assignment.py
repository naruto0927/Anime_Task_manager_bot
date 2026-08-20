"""helper/assignment.py — Assignment business logic."""
from __future__ import annotations
import logging
import random
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import database.anime as anime_db
import database.assignments as assign_db
import database.franchises as fr_db
import database.logs as logs_db
import database.users as users_db
from database.settings import get_int

logger = logging.getLogger(__name__)

PRIORITY_ORDER = ["high", "medium", "low"]


async def assign_next(user_id: int) -> Tuple[Optional[Dict], Optional[str]]:
    """Pick the best pending anime and assign it. Returns (anime_doc, error)."""
    user = await users_db.get_by_id(user_id)
    if not user:
        return None, "You are not registered. Contact the owner."
    if user.get("role") == "removed":
        return None, "Your access has been revoked."
    if user.get("is_away"):
        return None, "You are marked as away. Use /back to resume."

    global_limit = await get_int("task_limit", 5)
    effective_limit = min(global_limit, user.get("task_limit", global_limit))

    active = await assign_db.count_user_active(user_id)
    if active >= effective_limit:
        return None, (
            f"You've reached your task limit ({active}/{effective_limit}). "
            "Complete existing tasks first."
        )

    already = [
        a["anime_id"] for a in await assign_db.get_user_active(user_id)
    ]

    anime = await _pick_anime(user_id, already)
    if not anime:
        return None, (
            "No tasks available right now.\n"
            "All anime are assigned, completed, or franchise-locked."
        )

    await _create_assignment(anime, user_id, reserved=False)
    return anime, None


async def force_assign(anime_id: str, target_user_id: int,
                       by_user_id: int) -> Tuple[bool, str]:
    anime = await anime_db.get_by_id(anime_id)
    if not anime or anime.get("deleted"):
        return False, "Anime not found."
    target = await users_db.get_by_id(target_user_id)
    if not target:
        return False, "Target user not found."

    await _unassign(anime_id)
    await _create_assignment(anime, target_user_id, reserved=False,
                             force_by=by_user_id)
    await logs_db.log_audit(str(by_user_id), "force_assigned",
                            target=anime_id, new_value=str(target_user_id))
    return True, "Assigned."


async def reserve_anime(anime_id: str, user_id: int) -> Tuple[bool, str]:
    anime = await anime_db.get_by_id(anime_id)
    if not anime or anime.get("status") != "pending" or anime.get("deleted"):
        return False, "Anime not found or not in pending status."

    if anime.get("franchise_id"):
        if await fr_db.is_locked(anime["franchise_id"]):
            return False, "This franchise is locked by another assignment."

    existing = await assign_db.get_active(anime_id)
    if existing and existing.get("reserved"):
        return False, "This anime is already reserved."

    hours = await get_int("reservation_hours", 24)
    await _create_assignment(anime, user_id, reserved=True, reserve_hours=hours)
    reserved_until = datetime.utcnow() + timedelta(hours=hours)
    return True, f"Reserved for {hours}h (until {reserved_until.strftime('%Y-%m-%d %H:%M UTC')})."


async def update_status(user_id: int, anime_id: str,
                        new_status: str) -> Tuple[bool, str]:
    assignment = await assign_db.get_active(anime_id)
    if not assignment or assignment["user_id"] != user_id:
        return False, "No active assignment found for this anime."

    now = datetime.utcnow()
    extra: Dict = {}
    if new_status == "completed":
        extra["completed_at"] = now

    await assign_db.set_status(assignment["assignment_id"], new_status, extra)
    await anime_db.set_status(anime_id, new_status)

    # Counters
    inc: Dict = {}
    if new_status == "completed":
        inc = {"active_task_count": -1, "completed_count": 1}
        anime = await anime_db.get_by_id(anime_id)
        if anime and anime.get("franchise_id"):
            await fr_db.set_lock(anime["franchise_id"], False)
    elif new_status == "encoded":
        inc = {"encoded_count": 1}
    elif new_status == "leeched":
        inc = {"leeched_count": 1}
    elif new_status == "invalid":
        inc = {"active_task_count": -1, "invalid_count": 1}
        anime = await anime_db.get_by_id(anime_id)
        if anime and anime.get("franchise_id"):
            await fr_db.set_lock(anime["franchise_id"], False)

    if inc:
        await users_db.increment(user_id, **inc)

    await logs_db.log_activity(anime_id, user_id, "status_changed", new_status)
    return True, "Status updated."


async def expire_old_assignments() -> List[Dict]:
    """Expire overdue assignments. Returns list of affected records."""
    expired_raw = await assign_db.expire_old()
    affected = []
    for a in expired_raw:
        anime = await anime_db.get_by_id(a["anime_id"])
        if anime:
            await _unassign(a["anime_id"])
            affected.append({
                "anime_id": a["anime_id"],
                "user_id":  a["user_id"],
                "title":    anime["titles"].get("display_title", "Unknown"),
            })
    return affected


# ── Internal helpers ──────────────────────────────────────────────────────

async def _pick_anime(user_id: int, exclude: List[str]) -> Optional[Dict]:
    for priority in PRIORITY_ORDER:
        candidates = []
        for doc in await anime_db.find_pending(limit=50, priority=priority,
                                               exclude_ids=exclude):
            if doc.get("franchise_id"):
                if await fr_db.is_locked(doc["franchise_id"]):
                    continue
            candidates.append(doc)
        if candidates:
            return random.choice(candidates)

    # Fallback: any priority
    all_c = []
    for doc in await anime_db.find_pending(limit=100, exclude_ids=exclude):
        if doc.get("franchise_id"):
            if await fr_db.is_locked(doc["franchise_id"]):
                continue
        all_c.append(doc)
    return random.choice(all_c) if all_c else None


async def _create_assignment(anime: Dict, user_id: int,
                              reserved: bool = False,
                              reserve_hours: int = 24,
                              force_by: Optional[int] = None) -> None:
    expiry_days = await get_int("expiry_days", 7)
    now = datetime.utcnow()
    assignment_id = str(uuid.uuid4())

    first_status = "reserved" if reserved else ("force_assigned" if force_by else "assigned")
    doc = {
        "assignment_id": assignment_id,
        "anime_id":      anime["anime_id"],
        "user_id":       user_id,
        "status":        "assigned",
        "reserved":      reserved,
        "reserved_until": now + timedelta(hours=reserve_hours) if reserved else None,
        "assigned_at":   now,
        "expires_at":    now + timedelta(days=expiry_days),
        "completed_at":  None,
        "notes":         [],
        "history":       [{"status": first_status, "timestamp": now.isoformat(),
                           "by": force_by or user_id}],
    }
    await assign_db.insert(doc)
    await anime_db.set_status(anime["anime_id"], "assigned", assigned_user=user_id)
    await users_db.increment(user_id, active_task_count=1)

    if anime.get("franchise_id"):
        await fr_db.set_lock(anime["franchise_id"], True, user_id)

    await logs_db.log_activity(anime["anime_id"], user_id, "assigned")


async def _unassign(anime_id: str) -> None:
    assignment = await assign_db.get_active(anime_id)
    if assignment:
        await assign_db.set_status(assignment["assignment_id"], "expired")
        await users_db.increment(assignment["user_id"], active_task_count=-1)

    anime = await anime_db.get_by_id(anime_id)
    await anime_db.set_status(anime_id, "pending")
    if anime and anime.get("franchise_id"):
        await fr_db.set_lock(anime["franchise_id"], False)

    await logs_db.log_activity(anime_id, 0, "expired")
