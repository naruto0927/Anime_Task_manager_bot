"""helper/stats.py — Platform and per-user statistics."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from database.mongo import get_db
import database.assignments as assign_db
import database.backups as backup_db


async def global_stats() -> Dict[str, Any]:
    from database.anime import count_by_status
    counts = await count_by_status()
    total = sum(counts.values())
    bk = await backup_db.get_latest_success()
    return {
        "total":      total,
        "pending":    counts.get("pending", 0),
        "assigned":   counts.get("assigned", 0),
        "encoded":    counts.get("encoded", 0),
        "leeched":    counts.get("leeched", 0),
        "completed":  counts.get("completed", 0),
        "dropped":    counts.get("dropped", 0),
        "invalid":    counts.get("invalid", 0),
        "last_backup": bk["created_at"] if bk else None,
    }


async def user_stats(user_id: int) -> Optional[Dict[str, Any]]:
    db = get_db()
    user = await db.users.find_one({"telegram_id": user_id})
    if not user:
        return None

    active = await assign_db.count_user_active(user_id)
    avg_secs: Optional[float] = None
    deltas = []
    async for a in db.assignments.find(
        {"user_id": user_id, "status": "completed",
         "completed_at": {"$exists": True}},
    ).limit(100):
        delta = (a["completed_at"] - a["assigned_at"]).total_seconds()
        deltas.append(delta)
    if deltas:
        avg_secs = sum(deltas) / len(deltas)

    return {
        "username":             user.get("username", "Unknown"),
        "full_name":            user.get("full_name", ""),
        "active_tasks":         active,
        "task_limit":           user.get("task_limit", 5),
        "completed":            user.get("completed_count", 0),
        "encoded":              user.get("encoded_count", 0),
        "leeched":              user.get("leeched_count", 0),
        "invalid":              user.get("invalid_count", 0),
        "is_away":              user.get("is_away", False),
        "avg_completion_hours": round(avg_secs / 3600, 1) if avg_secs else None,
        "joined_at":            user.get("joined_at"),
    }


async def leaderboard(limit: int = 10) -> List[Dict[str, Any]]:
    db = get_db()
    board = []
    async for user in db.users.find({}, sort=[("completed_count", -1)]).limit(limit):
        board.append({
            "rank":      len(board) + 1,
            "username":  user.get("username") or user.get("full_name", "Unknown"),
            "completed": user.get("completed_count", 0),
            "encoded":   user.get("encoded_count", 0),
            "active":    user.get("active_task_count", 0),
        })
    return board


async def active_tasks_board() -> List[Dict[str, Any]]:
    db = get_db()
    board = []
    async for user in db.users.find({"active_task_count": {"$gt": 0}}):
        board.append({
            "username":    user.get("username") or user.get("full_name", "Unknown"),
            "task_count":  user.get("active_task_count", 0),
            "last_active": user.get("last_active"),
        })
    board.sort(key=lambda x: x["task_count"], reverse=True)
    return board


async def recent_completions(limit: int = 10) -> List[Dict]:
    db = get_db()
    results = []
    async for a in db.assignments.find(
        {"status": "completed"}, sort=[("completed_at", -1)]
    ).limit(limit):
        anime = await db.anime.find_one({"anime_id": a["anime_id"]})
        user  = await db.users.find_one({"telegram_id": a["user_id"]})
        if anime:
            results.append({
                "title":        anime["titles"]["display_title"],
                "completed_by": user.get("username", "Unknown") if user else "Unknown",
                "completed_at": a.get("completed_at"),
            })
    return results


async def invalid_queue() -> List[Dict]:
    db = get_db()
    results = []
    async for a in db.anime.find(
        {"status": "invalid", "deleted": {"$ne": True}},
        sort=[("updated_at", -1)],
    ).limit(20):
        results.append({
            "anime_id": a["anime_id"],
            "title":    a["titles"]["display_title"],
            "year":     a["year"],
            "season":   a["season"],
        })
    return results
