"""
database/config.py — Full ConfigService with schema, TTL cache, coerce, mask.

Replaces the simple database/settings.py for all runtime configuration.
The old settings.py is kept for backward compat imports but delegates here.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Full CONFIG_SCHEMA — every supported variable with metadata
# ---------------------------------------------------------------------------

CONFIG_SCHEMA: List[Dict[str, Any]] = [
    # ── Telegram ──────────────────────────────────────────────────────────
    {"key": "owner_ids",            "default": [],    "type": "list", "category": "telegram",
     "label": "Owner IDs",          "description": "Comma-separated Telegram user IDs with owner access", "secret": False},
    {"key": "dashboard_channel",    "default": None,  "type": "int",  "category": "telegram",
     "label": "Dashboard Channel ID","description": "Channel ID for 4 live pinned dashboard messages",   "secret": False},
    {"key": "log_channel",          "default": None,  "type": "int",  "category": "telegram",
     "label": "Log Channel ID",      "description": "Channel ID for activity log messages",              "secret": False},
    {"key": "backup_channel",       "default": None,  "type": "int",  "category": "telegram",
     "label": "Backup Channel ID",   "description": "Channel ID for daily backup ZIP files",             "secret": False},
    {"key": "webhook_url",          "default": "",    "type": "str",  "category": "telegram",
     "label": "Webhook URL",         "description": "Public HTTPS URL for Telegram webhook",             "secret": False},
    {"key": "webhook_port",         "default": 8443,  "type": "int",  "category": "telegram",
     "label": "Webhook Port",        "description": "Port for webhook server (8443 recommended)",        "secret": False},
    {"key": "webhook_secret",       "default": "",    "type": "str",  "category": "telegram",
     "label": "Webhook Secret Token","description": "Secret token for Telegram webhook verification",    "secret": True},
    # ── Google Sheets ─────────────────────────────────────────────────────
    {"key": "sheets_enabled",         "default": False,"type": "bool","category": "sheets",
     "label": "Sheets Enabled",        "description": "Enable/disable Google Sheets live sync",          "secret": False},
    {"key": "sheets_auto_sync",        "default": False,"type": "bool","category": "sheets",
     "label": "Auto Sync",             "description": "Auto-sync Sheets on every data change",           "secret": False},
    {"key": "sheets_spreadsheet_id",   "default": "",  "type": "str", "category": "sheets",
     "label": "Spreadsheet ID",        "description": "Google Sheets spreadsheet ID (from URL)",         "secret": False},
    {"key": "sheets_credentials_file", "default": "credentials.json","type": "str","category": "sheets",
     "label": "Credentials File",      "description": "Path to Google service account credentials JSON", "secret": False},
    {"key": "sheets_sync_interval",    "default": 3600,"type": "int", "category": "sheets",
     "label": "Sync Interval (s)",     "description": "Seconds between auto-syncs",                      "secret": False},
    {"key": "sheets_send_link_on_export","default": True,"type":"bool","category":"sheets",
     "label": "Send Sheet Link",       "description": "Inline button linking to sheet after /exportsheet","secret": False},
    {"key": "sheets_send_file_on_export","default":False,"type":"bool","category":"sheets",
     "label": "Send CSV Files",        "description": "Upload CSV files to backup channel on /exportsheet","secret": False},
    # ── API Keys ─────────────────────────────────────────────────────────
    {"key": "mal_client_id",          "default": "",  "type": "str", "category": "api",
     "label": "MAL Client ID",         "description": "MyAnimeList API v2 Client ID",                    "secret": True},
    {"key": "animeschedule_api_key",   "default": "",  "type": "str", "category": "api",
     "label": "AnimeSchedule API Key", "description": "AnimeSchedule.net API key (optional)",            "secret": True},
    # ── Task Settings ─────────────────────────────────────────────────────
    {"key": "task_limit",             "default": 5,   "type": "int", "category": "tasks",
     "label": "Global Task Limit",     "description": "Default max active tasks per admin",              "secret": False},
    {"key": "expiry_days",            "default": 7,   "type": "int", "category": "tasks",
     "label": "Assignment Expiry (days)","description": "Days before inactive assignment auto-expires",  "secret": False},
    {"key": "reservation_hours",      "default": 24,  "type": "int", "category": "tasks",
     "label": "Reservation Duration (h)","description": "Hours a /reserve hold lasts",                  "secret": False},
    {"key": "rapidfuzz_threshold",    "default": 90,  "type": "int", "category": "tasks",
     "label": "Fuzzy Match Threshold (%)","description": "Minimum similarity % for duplicate detection", "secret": False},
    {"key": "ignore_donghua",         "default": False,"type": "bool","category": "tasks",
     "label": "Ignore Donghua",        "description": "Skip Chinese animation during import",            "secret": False},
    {"key": "ignore_specials",        "default": False,"type": "bool","category": "tasks",
     "label": "Ignore Specials",       "description": "Skip Special type entries during import",         "secret": False},
    {"key": "ignore_recaps",          "default": False,"type": "bool","category": "tasks",
     "label": "Ignore Recaps",         "description": "Skip recap episodes during import",               "secret": False},
    {"key": "ignore_music_videos",    "default": False,"type": "bool","category": "tasks",
     "label": "Ignore Music Videos",   "description": "Skip Music type entries during import",           "secret": False},
    {"key": "ignore_shorts",          "default": False,"type": "bool","category": "tasks",
     "label": "Ignore Shorts",         "description": "Skip very short-form content during import",      "secret": False},
    {"key": "ignore_unknown",         "default": False,"type": "bool","category": "tasks",
     "label": "Ignore Unknown Type",   "description": "Skip entries with unknown media type",            "secret": False},
    # ── Scheduler ─────────────────────────────────────────────────────────
    {"key": "dashboard_update_interval","default": 300,"type": "int","category": "scheduler",
     "label": "Dashboard Refresh (s)",  "description": "How often dashboard messages auto-update",       "secret": False},
    {"key": "backup_hour",             "default": 3,  "type": "int", "category": "scheduler",
     "label": "Backup Hour (UTC)",      "description": "Hour of day (0–23 UTC) for daily backup",        "secret": False},
    {"key": "backup_minute",           "default": 0,  "type": "int", "category": "scheduler",
     "label": "Backup Minute",          "description": "Minute (0–59) for daily backup",                 "secret": False},
    # ── System ────────────────────────────────────────────────────────────
    {"key": "app_env",  "default": "production","type": "str","category": "system",
     "label": "App Environment","description": "'production' or 'development'",                         "secret": False},
    {"key": "log_level","default": "INFO",       "type": "str","category": "system",
     "label": "Log Level",      "description": "DEBUG | INFO | WARNING | ERROR",                        "secret": False},
]

SCHEMA_MAP: Dict[str, Dict] = {s["key"]: s for s in CONFIG_SCHEMA}
CATEGORIES = ["telegram", "api", "sheets", "tasks", "scheduler", "system"]
CATEGORY_LABELS = {
    "telegram":  "📱 Telegram",
    "api":       "🔑 API Keys",
    "sheets":    "📊 Google Sheets",
    "tasks":     "📋 Task Settings",
    "scheduler": "⏰ Scheduler",
    "system":    "⚙️ System",
}

# ---------------------------------------------------------------------------
# TTL Cache
# ---------------------------------------------------------------------------

class _Cache:
    TTL = 60

    def __init__(self):
        self._data: Dict[str, Tuple[Any, float]] = {}

    def get(self, key: str) -> Tuple[bool, Any]:
        if key in self._data:
            value, ts = self._data[key]
            if time.monotonic() - ts < self.TTL:
                return True, value
        return False, None

    def set(self, key: str, value: Any) -> None:
        self._data[key] = (value, time.monotonic())

    def invalidate(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()


_cache = _Cache()


# ---------------------------------------------------------------------------
# ConfigService
# ---------------------------------------------------------------------------

class ConfigService:

    async def get(self, key: str, default: Any = None) -> Any:
        hit, val = _cache.get(key)
        if hit:
            return val
        from database.mongo import get_db
        doc = await get_db().config.find_one({"key": key})
        if doc is not None:
            _cache.set(key, doc["value"])
            return doc["value"]
        return SCHEMA_MAP.get(key, {}).get("default", default)

    async def get_int(self, key: str, default: int = 0) -> int:
        val = await self.get(key, default)
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    async def get_bool(self, key: str, default: bool = False) -> bool:
        val = await self.get(key, default)
        if isinstance(val, bool):
            return val
        return str(val).lower() in ("true", "1", "on", "yes")

    async def get_str(self, key: str, default: str = "") -> str:
        val = await self.get(key, default)
        return str(val) if val is not None else default

    async def get_list(self, key: str, default: Optional[List] = None) -> List:
        val = await self.get(key, default or [])
        if isinstance(val, list):
            return val
        if isinstance(val, str):
            return [x.strip() for x in val.split(",") if x.strip()]
        return default or []

    async def get_owner_ids(self) -> List[int]:
        raw = await self.get_list("owner_ids", [])
        try:
            ids = [int(x) for x in raw if str(x).lstrip("-").isdigit()]
        except (TypeError, ValueError):
            ids = []
        # Fallback: if DB has no owners, use config.py OWNER_ID directly
        if not ids:
            from config import OWNER_ID
            if OWNER_ID:
                ids = [OWNER_ID]
        return ids

    async def get_all(self) -> Dict[str, Any]:
        result = {s["key"]: s["default"] for s in CONFIG_SCHEMA}
        from database.mongo import get_db
        async for doc in get_db().config.find({}):
            if doc["key"] in result or doc["key"] in SCHEMA_MAP:
                result[doc["key"]] = doc["value"]
        return result

    async def set(self, key: str, value: Any, updated_by: Optional[int] = None) -> None:
        from database.mongo import get_db
        schema   = SCHEMA_MAP.get(key, {})
        coerced  = self._coerce(value, schema.get("type", "str"))
        _cache.invalidate(key)
        await get_db().config.update_one(
            {"key": key},
            {"$set": {
                "value":       coerced,
                "type":        schema.get("type", "str"),
                "category":    schema.get("category", "system"),
                "label":       schema.get("label", key),
                "description": schema.get("description", ""),
                "secret":      schema.get("secret", False),
                "updated_at":  datetime.utcnow(),
                "updated_by":  updated_by,
            }},
            upsert=True,
        )
        logger.info("Config updated: %s = %r (by %s)", key, coerced, updated_by)

    async def initialize_defaults(self) -> None:
        from database.mongo import get_db
        from config import OWNER_ID
        db = get_db()
        for schema in CONFIG_SCHEMA:
            existing = await db.config.find_one({"key": schema["key"]})
            if existing is None:
                default = schema["default"]
                if schema["key"] == "owner_ids" and OWNER_ID:
                    default = [OWNER_ID]
                await db.config.insert_one({
                    "key":         schema["key"],
                    "value":       default,
                    "type":        schema["type"],
                    "category":    schema["category"],
                    "label":       schema["label"],
                    "description": schema["description"],
                    "secret":      schema["secret"],
                    "updated_at":  datetime.utcnow(),
                    "updated_by":  None,
                })
            elif schema["key"] == "owner_ids" and OWNER_ID:
                # Repair: if stored owner_ids is empty, seed from config.py
                current = existing.get("value", [])
                if not current:
                    await db.config.update_one(
                        {"key": "owner_ids"},
                        {"$set": {"value": [OWNER_ID], "updated_at": datetime.utcnow()}},
                    )
                    _cache.invalidate("owner_ids")
                    logger.info("Repaired empty owner_ids → [%s]", OWNER_ID)
        logger.info("Config defaults initialized (%d keys)", len(CONFIG_SCHEMA))

    @staticmethod
    def _coerce(value: Any, type_str: str) -> Any:
        if type_str == "int":
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
        if type_str == "bool":
            if isinstance(value, bool):
                return value
            return str(value).lower() in ("true", "1", "on", "yes")
        if type_str == "list":
            if isinstance(value, list):
                return value
            return [x.strip() for x in str(value).split(",") if x.strip()]
        return str(value) if value is not None else ""

    @staticmethod
    def mask(value: Any) -> str:
        s = str(value)
        if len(s) <= 4:
            return "••••"
        return s[:2] + "•" * (len(s) - 4) + s[-2:]


cfg = ConfigService()
