"""helper/manual.py — Manual anime add and task completion logic."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Dict, Optional, Tuple

from database.mongo import get_db
import database.assignments as assign_db
import database.logs as logs_db
import database.users as users_db


async def add_manual_anime(title: str, year: int, season: str,
                            anime_type: str = "TV",
                            mal_url: Optional[str] = None,
                            added_by: int = 0) -> Dict:
    """Manually add an anime entry (no MAL import)."""
    anime_id = str(uuid.uuid4())
    doc = {
        "anime_id": anime_id,
        "mal_id":   None,
        "titles": {
            "display_title": title,
            "title_en": title,
            "title_romaji": title,
            "title_japanese": "",
            "aliases": [title],
            "synonyms": [],
            "owner_override": True,
        },
        "franchise_id":   None,
        "franchise_name": None,
        "year":           year,
        "season":         season.lower(),
        "anime_type":     anime_type,
        "status":         "pending",
        "priority":       "medium",
        "episode_count":  None,
        "studio":         None,
        "synopsis":       "",
        "mal_url":        mal_url,
        "image_url":      None,
        "notes":          [],
        "deleted":        False,
        "imported_at":    datetime.utcnow(),
        "updated_at":     datetime.utcnow(),
        "manual":         True,
        "added_by":       added_by,
    }
    await get_db().anime.insert_one(doc)
    await logs_db.log_audit(str(added_by), "manual_add", target=anime_id, new_value=title)
    return doc


async def manual_complete_task(anime_id: str, user_id: int) -> Tuple[bool, str]:
    """Owner-force complete a task."""
    assignment = await assign_db.get_active(anime_id)
    if not assignment:
        return False, "No active assignment found."
    from helper.assignment import update_status
    return await update_status(assignment["user_id"], anime_id, "completed")
