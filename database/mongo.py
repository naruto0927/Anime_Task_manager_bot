"""
database/mongo.py — MongoDB via sync PyMongo + asyncio.to_thread.

Motor 3.x has a known event-loop conflict with Python 3.13 (asyncio changed
how loops are detected). We replace it with plain PyMongo running in a thread
pool via asyncio.to_thread, which is perfectly safe and loop-agnostic.

The public API is unchanged:
    connect_db()   — async, call once at startup
    disconnect_db()— async, call at shutdown
    get_db()       — sync, returns an AsyncCollection proxy
    ping_db()      — async bool

All collection proxy methods (find_one, find, aggregate, count_documents,
insert_one, update_one, delete_one, create_indexes, …) are async and
offload blocking I/O to a thread.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import pymongo
from pymongo import MongoClient, ASCENDING, DESCENDING, IndexModel, TEXT
from pymongo.database import Database

from config import MONGODB_URI, MONGODB_DB_NAME

logger = logging.getLogger(__name__)

_client: Optional[MongoClient] = None
_db:     Optional[Database]    = None


# ── Connection ─────────────────────────────────────────────────────────────

async def connect_db() -> None:
    global _client, _db
    _client = MongoClient(
        MONGODB_URI,
        serverSelectionTimeoutMS=10_000,
        maxPoolSize=10,
        connect=True,
    )
    _db = _client[MONGODB_DB_NAME]
    # Verify connection is alive
    await asyncio.to_thread(_client.admin.command, "ping")
    await _create_indexes()
    logger.info("MongoDB connected: %s", MONGODB_DB_NAME)


async def disconnect_db() -> None:
    global _client
    if _client:
        await asyncio.to_thread(_client.close)
        logger.info("MongoDB disconnected")


async def ping_db() -> bool:
    try:
        await asyncio.to_thread(_client.admin.command, "ping")
        return True
    except Exception:
        return False


# ── Collection proxy ───────────────────────────────────────────────────────

class AsyncCollection:
    """
    Wraps a pymongo Collection, exposing async methods via to_thread.
    Supports the subset of Motor's API used across this codebase.
    """

    def __init__(self, col):
        self._col = col

    # ── Single-doc ops ──────────────────────────────────────────────────

    async def find_one(self, filt=None, *args, **kwargs):
        return await asyncio.to_thread(self._col.find_one, filt, *args, **kwargs)

    async def insert_one(self, doc, *args, **kwargs):
        return await asyncio.to_thread(self._col.insert_one, doc, *args, **kwargs)

    async def update_one(self, filt, update, *args, **kwargs):
        return await asyncio.to_thread(self._col.update_one, filt, update, *args, **kwargs)

    async def update_many(self, filt, update, *args, **kwargs):
        return await asyncio.to_thread(self._col.update_many, filt, update, *args, **kwargs)

    async def find_one_and_update(self, filt, update, *args, **kwargs):
        return await asyncio.to_thread(self._col.find_one_and_update, filt, update, *args, **kwargs)

    async def delete_one(self, filt, *args, **kwargs):
        return await asyncio.to_thread(self._col.delete_one, filt, *args, **kwargs)

    async def delete_many(self, filt, *args, **kwargs):
        return await asyncio.to_thread(self._col.delete_many, filt, *args, **kwargs)

    async def count_documents(self, filt=None, *args, **kwargs):
        return await asyncio.to_thread(self._col.count_documents, filt or {}, *args, **kwargs)

    async def create_indexes(self, indexes, *args, **kwargs):
        return await asyncio.to_thread(self._col.create_indexes, indexes, *args, **kwargs)

    # ── Cursor ops (find / aggregate) ────────────────────────────────────

    def find(self, filt=None, *args, **kwargs):
        """Returns an AsyncCursor — iterate with `async for`."""
        return AsyncCursor(self._col, filt or {}, *args, **kwargs)

    def aggregate(self, pipeline, *args, **kwargs):
        """Returns an AsyncCursor — iterate with `async for`."""
        return AsyncAggregateCursor(self._col, pipeline, *args, **kwargs)


class AsyncCursor:
    """
    Async iterator over a pymongo find() cursor.
    Supports .limit() and .sort() chaining.
    """

    def __init__(self, col, filt, *args, **kwargs):
        self._col    = col
        self._filt   = filt
        self._args   = args
        self._limit  = 0
        self._sort   = kwargs.pop("sort", None)
        self._kwargs = kwargs  # remaining kwargs (e.g. projection)

    def limit(self, n: int) -> "AsyncCursor":
        self._limit = n
        return self

    def sort(self, key_or_list, direction=None) -> "AsyncCursor":
        if direction is not None:
            self._sort = [(key_or_list, direction)]
        else:
            self._sort = key_or_list
        return self

    def _fetch(self) -> list:
        cur = self._col.find(self._filt, *self._args, **self._kwargs)
        if self._sort:
            cur = cur.sort(self._sort)
        if self._limit:
            cur = cur.limit(self._limit)
        return list(cur)

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        docs = await asyncio.to_thread(self._fetch)
        for doc in docs:
            yield doc


class AsyncAggregateCursor:
    """Async iterator over a pymongo aggregate() pipeline."""

    def __init__(self, col, pipeline, *args, **kwargs):
        self._col      = col
        self._pipeline = pipeline
        self._args     = args
        self._kwargs   = kwargs

    def _fetch(self) -> list:
        return list(self._col.aggregate(self._pipeline, *self._args, **self._kwargs))

    def __aiter__(self):
        return self._iterate()

    async def _iterate(self):
        docs = await asyncio.to_thread(self._fetch)
        for doc in docs:
            yield doc


# ── DB proxy ───────────────────────────────────────────────────────────────

class AsyncDB:
    """Attribute access returns AsyncCollection wrappers."""

    def __init__(self, db: Database):
        self._db = db

    def __getattr__(self, name: str) -> AsyncCollection:
        return AsyncCollection(self._db[name])

    def __getitem__(self, name: str) -> AsyncCollection:
        return AsyncCollection(self._db[name])


_async_db: Optional[AsyncDB] = None


def get_db() -> AsyncDB:
    if _async_db is None:
        raise RuntimeError("Database not initialised. Call connect_db() first.")
    return _async_db


# ── Index creation ─────────────────────────────────────────────────────────

async def _create_indexes() -> None:
    global _async_db
    _async_db = AsyncDB(_db)
    db = _async_db

    await db.anime.create_indexes([
        IndexModel([("mal_id", ASCENDING)], unique=True, sparse=True),
        IndexModel([("franchise_id", ASCENDING)]),
        IndexModel([("status", ASCENDING)]),
        IndexModel([("season", ASCENDING), ("year", ASCENDING)]),
        IndexModel([
            ("titles.display_title", TEXT),
            ("titles.title_en", TEXT),
            ("titles.title_romaji", TEXT),
            ("titles.aliases", TEXT),
        ]),
        IndexModel([("deleted", ASCENDING)]),
        IndexModel([("priority", ASCENDING)]),
        IndexModel([("assigned_user", ASCENDING)]),
    ])

    await db.users.create_indexes([
        IndexModel([("telegram_id", ASCENDING)], unique=True, sparse=True),
        IndexModel([("username", ASCENDING)]),
        IndexModel([("role", ASCENDING)]),
        IndexModel([("is_away", ASCENDING)]),
    ])

    await db.franchises.create_indexes([
        IndexModel([("franchise_id", ASCENDING)], unique=True),
        IndexModel([("name", TEXT)]),
    ])

    await db.assignments.create_indexes([
        IndexModel([("anime_id", ASCENDING)]),
        IndexModel([("user_id", ASCENDING)]),
        IndexModel([("status", ASCENDING)]),
        IndexModel([("expires_at", ASCENDING)]),
        IndexModel([("assigned_at", DESCENDING)]),
    ])

    await db.activity_logs.create_indexes([
        IndexModel([("anime_id", ASCENDING)]),
        IndexModel([("user_id", ASCENDING)]),
        IndexModel([("timestamp", DESCENDING)]),
    ])

    await db.audit_logs.create_indexes([
        IndexModel([("user", ASCENDING)]),
        IndexModel([("action", ASCENDING)]),
        IndexModel([("timestamp", DESCENDING)]),
    ])

    await db.dropped.create_indexes([
        IndexModel([("anime_id", ASCENDING)], unique=True),
        IndexModel([("date", DESCENDING)]),
    ])

    await db.telegram_messages.create_indexes([
        IndexModel([("anime_id", ASCENDING)], unique=True),
        IndexModel([("message_type", ASCENDING)]),
    ])

    await db.config.create_indexes([
        IndexModel([("key", ASCENDING)], unique=True),
        IndexModel([("category", ASCENDING)]),
    ])

    await db.backups.create_indexes([
        IndexModel([("created_at", DESCENDING)]),
        IndexModel([("status", ASCENDING)]),
    ])

    await db.health.create_indexes([
        IndexModel([("timestamp", DESCENDING)]),
    ])

    logger.info("MongoDB indexes ensured")
