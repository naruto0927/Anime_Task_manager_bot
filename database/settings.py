"""
database/settings.py — Thin shim that delegates to database.config.cfg.
Kept for backward-compat imports throughout helper/ and scheduler/.
"""
from __future__ import annotations
from typing import Any, List, Optional

from database.config import cfg


async def get(key: str, default: Any = None) -> Any:
    return await cfg.get(key, default)


async def get_int(key: str, default: int = 0) -> int:
    return await cfg.get_int(key, default)


async def get_bool(key: str, default: bool = False) -> bool:
    return await cfg.get_bool(key, default)


async def get_str(key: str, default: str = "") -> str:
    return await cfg.get_str(key, default)


async def set(key: str, value: Any, updated_by: Optional[int] = None) -> None:
    await cfg.set(key, value, updated_by)


async def get_all() -> dict:
    return await cfg.get_all()


async def get_owner_ids() -> List[int]:
    return await cfg.get_owner_ids()


async def initialize_defaults() -> None:
    await cfg.initialize_defaults()


def invalidate(key: str) -> None:
    from database.config import _cache
    _cache.invalidate(key)
