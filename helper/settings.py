"""helper/settings.py — Config panel validation and apply helpers."""
from __future__ import annotations
from typing import Any, Tuple

import database.settings as settings_db
import database.logs as logs_db

BOOLEAN_KEYS = {
    "ignore_donghua", "ignore_specials", "ignore_recaps",
    "ignore_music_videos", "ignore_shorts", "ignore_unknown",
    "sheets_enabled", "sheets_auto_sync",
    "sheets_send_link_on_export", "sheets_send_file_on_export",
}
INT_KEYS = {
    "task_limit", "expiry_days", "reservation_hours",
    "rapidfuzz_threshold", "dashboard_update_interval",
    "sheets_sync_interval", "backup_hour", "backup_minute",
    "dashboard_channel", "log_channel", "backup_channel",
}


def coerce(key: str, raw: str) -> Tuple[bool, Any, str]:
    """Validate and coerce a raw string value. Returns (ok, value, error)."""
    if key in BOOLEAN_KEYS:
        if raw.lower() in ("on", "true", "1", "yes"):
            return True, True, ""
        if raw.lower() in ("off", "false", "0", "no"):
            return True, False, ""
        return False, None, "Use: on / off"
    if key in INT_KEYS:
        try:
            return True, int(raw), ""
        except ValueError:
            return False, None, f"'{key}' requires an integer."
    return True, raw.strip(), ""


async def update_setting(key: str, value: Any,
                          updated_by: int = 0) -> None:
    old = await settings_db.get(key)
    await settings_db.set(key, value, updated_by)
    await logs_db.log_audit(
        str(updated_by), "setting_changed",
        target=key, old_value=str(old), new_value=str(value),
    )
