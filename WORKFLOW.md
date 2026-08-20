# AnimeAssignBot — Complete Workflow & Architecture Guide

---

## Table of Contents

1. [What This Bot Does](#1-what-this-bot-does)
2. [Architecture Overview](#2-architecture-overview)
3. [Data Model](#3-data-model)
4. [Startup Sequence](#4-startup-sequence)
5. [User Roles & Access Control](#5-user-roles--access-control)
6. [Core Workflow: Import → Assign → Complete](#6-core-workflow-import--assign--complete)
7. [Assignment Engine (Deep Dive)](#7-assignment-engine-deep-dive)
8. [Franchise System (Deep Dive)](#8-franchise-system-deep-dive)
9. [Import System (Deep Dive)](#9-import-system-deep-dive)
10. [Dashboard System (Deep Dive)](#10-dashboard-system-deep-dive)
11. [Google Sheets Sync (Deep Dive)](#11-google-sheets-sync-deep-dive)
12. [Backup System (Deep Dive)](#12-backup-system-deep-dive)
13. [Scheduler Jobs](#13-scheduler-jobs)
14. [Config System (Deep Dive)](#14-config-system-deep-dive)
15. [Drop / Restore / Delete System](#15-drop--restore--delete-system)
16. [Text Input State Machine](#16-text-input-state-machine)
17. [All Commands Reference](#17-all-commands-reference)
18. [Data Flow Diagrams](#18-data-flow-diagrams)
19. [Layer Dependency Rules](#19-layer-dependency-rules)
20. [First Boot Checklist](#20-first-boot-checklist)

---

## 1. What This Bot Does

AnimeAssignBot is a **workflow management platform** for teams that process anime
(encoding, translation, leeching, etc.). It solves a core coordination problem:

> *You have 200+ anime per season and 10 admins. Who works on what?
> How do you prevent two people doing the same show?
> How do you track who finished what?*

The bot handles all of that automatically:

- **Imports** seasonal anime from MyAnimeList API
- **Assigns** tasks fairly across admins, respecting priority and franchise locks
- **Tracks** progress through statuses: pending → assigned → encoded → leeched → completed
- **Prevents duplicate work** via franchise-level locking
- **Posts live dashboards** to a Telegram channel, auto-refreshed every 5 minutes
- **Syncs** all data to Google Sheets in real time
- **Backs up** the entire database daily as a ZIP to a Telegram channel
- **Expires** abandoned tasks automatically every hour

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                    Telegram Users                    │
└──────────────────────────┬──────────────────────────┘
                           │ Pyrogram long-polling
┌──────────────────────────▼──────────────────────────┐
│                      plugins/                        │
│  (Telegram I/O only — commands, callbacks, replies)  │
│                                                      │
│  start  help  assignments  admins  imports  manual   │
│  drops  reports  search  stats  franchise  panel     │
│  settings  dashboard  backup  health  text_router    │
└──────────┬──────────────────────────────────────────┘
           │ calls
┌──────────▼──────────────────────────────────────────┐
│                      helper/                         │
│           (All business logic lives here)            │
│                                                      │
│  assignment   franchise   importer   dashboard       │
│  sheets       backup      search     stats           │
│  health       manual      normalization  aliases     │
│  alerts       settings                               │
└──────────┬──────────────────────────────────────────┘
           │ calls
┌──────────▼──────────────────────────────────────────┐
│                     database/                        │
│        (MongoDB operations only — no logic)          │
│                                                      │
│  mongo   anime   users   assignments   franchises    │
│  config  dropped  logs   backups   settings(shim)    │
└──────────┬──────────────────────────────────────────┘
           │ Motor async driver
┌──────────▼──────────────────────────────────────────┐
│                     MongoDB Atlas                    │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                    scheduler/                        │
│         (Background jobs — call helper/)             │
│                                                      │
│  backup(24h)  dashboard(5m)  expiry(1h)             │
│  sheets(1h)   health(15m)                            │
└─────────────────────────────────────────────────────┘
```

**Rule:** Each layer only calls the layer below it. Never sideways, never upward.

---

## 3. Data Model

### `anime` collection

```json
{
  "anime_id":       "uuid4",
  "mal_id":         12345,
  "titles": {
    "display_title":  "Frieren: Beyond Journey's End",
    "title_en":       "Frieren: Beyond Journey's End",
    "title_romaji":   "Sousou no Frieren",
    "title_japanese": "葬送のフリーレン",
    "aliases":        ["Frieren", "Sousou no Frieren"],
    "synonyms":       [],
    "owner_override": false
  },
  "franchise_id":   "frieren",
  "franchise_name": "Frieren",
  "year":           2023,
  "season":         "fall",
  "anime_type":     "TV",
  "status":         "pending",
  "priority":       "high",
  "episode_count":  28,
  "studio":         "Madhouse",
  "synopsis":       "...",
  "mal_url":        "https://myanimelist.net/anime/52991",
  "image_url":      "https://cdn.myanimelist.net/...",
  "notes":          [],
  "deleted":        false,
  "imported_at":    "2023-09-01T00:00:00",
  "updated_at":     "2023-09-01T00:00:00"
}
```

**Key field: `owner_override`** — if `true`, the `display_title` was manually set
via `/edit_title` and will NEVER be overwritten by any import or sync job.

### `users` collection

```json
{
  "telegram_id":      123456789,
  "username":         "john_doe",
  "full_name":        "John Doe",
  "role":             "admin",
  "task_limit":       5,
  "is_away":          false,
  "away_since":       null,
  "active_task_count": 2,
  "completed_count":  47,
  "encoded_count":    12,
  "leeched_count":    8,
  "invalid_count":    1,
  "joined_at":        "2024-01-01T00:00:00",
  "last_active":      "2024-06-01T12:00:00",
  "pre_registered":   false
}
```

**Key field: `pre_registered`** — Owner can `/addadmin @username` before the user
ever messages the bot. When they send `/start`, the bot matches their username,
transfers the pre-registration, and grants access instantly.

### `assignments` collection

```json
{
  "assignment_id": "uuid4",
  "anime_id":      "anime-uuid",
  "user_id":       123456789,
  "status":        "assigned",
  "reserved":      false,
  "reserved_until": null,
  "assigned_at":   "2024-06-01T10:00:00",
  "expires_at":    "2024-06-08T10:00:00",
  "completed_at":  null,
  "notes":         ["Waiting for BD source"],
  "history": [
    {"status": "assigned", "timestamp": "2024-06-01T10:00:00", "by": 123456789}
  ]
}
```

### `franchises` collection

```json
{
  "franchise_id":          "attack_on_titan",
  "name":                  "Attack on Titan",
  "canonical_name":        "Attack On Titan",
  "anime_ids":             ["uuid1", "uuid2", "uuid3"],
  "mal_ids":               [16498, 25777, 99147],
  "aliases":               ["Shingeki no Kyojin", "AoT", "SnK"],
  "has_active_assignment": true,
  "active_assignee_id":    123456789,
  "created_at":            "2024-01-01T00:00:00",
  "updated_at":            "2024-06-01T00:00:00"
}
```

### `config` collection

All runtime settings. 30 keys defined in `CONFIG_SCHEMA`. Examples:

```json
{"key": "task_limit",        "value": 5,    "category": "tasks"}
{"key": "dashboard_channel", "value": -1001234567890, "category": "telegram"}
{"key": "sheets_enabled",    "value": true, "category": "sheets"}
{"key": "mal_client_id",     "value": "abc123", "secret": true}
```

---

## 4. Startup Sequence

```
python bot.py
     │
     ├─ 1. Create log directories (logs/, backups/, exports/)
     ├─ 2. Configure logging → stdout + logs/bot.log
     ├─ 3. Create Pyrogram Client
     │       name="AnimeAssignBot"
     │       plugins={"root": "plugins"}  ← auto-discovers all plugins/
     │
     ├─ 4. app.run() → connects to Telegram
     │
     └─ _on_startup() [called by Pyrogram after connect]
           │
           ├─ connect_db()
           │     ├─ Motor async client (pool: 5–50 connections)
           │     └─ create_indexes() on all 10 collections
           │
           ├─ cfg.initialize_defaults()
           │     └─ Writes 30 config keys if they don't exist yet
           │        (safe to call on every boot — uses $setOnInsert)
           │
           ├─ Register 5 scheduler jobs:
           │     ├─ daily_backup        every 24h
           │     ├─ dashboard_refresh   every 5m
           │     ├─ assignment_expiry   every 1h
           │     ├─ sheets_sync         every 1h
           │     └─ health_snapshot     every 15m
           │
           ├─ scheduler.start()
           │
           ├─ write_health_snapshot()  ← initial baseline
           │
           └─ Send startup message to all owner_ids
```

---

## 5. User Roles & Access Control

Two roles exist. Everything is enforced by decorators in `helper/aliases.py`.

### `@owner_only`
Full access to everything. Set via `OWNER_ID` env var (seeded into `owner_ids`
config key on first boot). Additional owners added via `/set owner_ids`.

### `@admin_or_owner`
Task management commands: `/nexttask`, `/mytask`, `/reserve`, `/away`, `/back`,
`/find`, `/franchise`, `/mystats`, `/leaderboard`.

### How access works

```python
@Client.on_message(filters.command("nexttask"))
@admin_or_owner        # ← checks role in DB
@rate_limited          # ← 20 commands per 60s per user
async def cmd_nexttask(app, msg):
    ...
```

`@admin_or_owner` checks in this order:
1. Is user in `owner_ids`? → Allow
2. Is user in `users` collection with `role="admin"`? → Allow
3. Does user have a `pre_registered=True` record matching their username? → Claim it, Allow
4. None of the above → Reply "You are not registered"

### Rate limiting

`@rate_limited` uses an in-memory sliding window: 20 commands per 60 seconds per
user. Prevents spam and accidental loops. Resets every 60 seconds.

---

## 6. Core Workflow: Import → Assign → Complete

This is the full lifecycle of one anime through the system.

```
STEP 1: OWNER IMPORTS
──────────────────────────────────────────────────────
Owner: /importseason Fall 2023

  helper/importer.py:
  ├─ Fetch from MAL API v2 (paginated, up to 500/page)
  ├─ For each anime:
  │   ├─ Check ignore rules (donghua? special? recap?)
  │   ├─ Check duplicates (MAL ID? fuzzy title match? franchise?)
  │   ├─ Build anime document with UUID
  │   └─ Detect/assign franchise_id
  └─ Return stats + review list

Bot replies: "142 found, 89 new, 41 duplicates, 12 ignored"
Bot shows: [✅ Keep All] [❌ Discard All] buttons

Owner clicks: ✅ Keep All
  └─ confirm_import() saves all 89 docs to MongoDB
  └─ ensure_franchise() links each to its franchise
  └─ dashboard updates, sheets sync

──────────────────────────────────────────────────────
STEP 2: ADMIN GETS TASK
──────────────────────────────────────────────────────
Admin: /nexttask

  helper/assignment.py → assign_next():
  ├─ Check user is registered, not away, not at limit
  ├─ Load all existing assignment anime_ids (to exclude)
  ├─ For each priority (high → medium → low):
  │   ├─ Query pending anime (not in excluded list)
  │   ├─ Filter out franchise-locked anime
  │   └─ Pick randomly from candidates
  └─ Create assignment document + update anime status

Bot replies: task card with 5 inline buttons:
  [✅ Completed] [📦 Encoded]
  [🔗 Leeched]  [❌ Invalid]
  [📝 Add Note]

Franchise is now LOCKED → no other admin gets this franchise.

──────────────────────────────────────────────────────
STEP 3: ADMIN WORKS + UPDATES STATUS
──────────────────────────────────────────────────────
Admin clicks: 📦 Encoded
  └─ assignment status: assigned → encoded
  └─ user.encoded_count += 1
  └─ dashboard updates
  └─ sheets sync

Admin clicks: 🔗 Leeched
  └─ assignment status: encoded → leeched

Admin clicks: ✅ Completed
  └─ assignment status: leeched → completed
  └─ anime status: → completed
  └─ user.active_task_count -= 1
  └─ user.completed_count += 1
  └─ FRANCHISE UNLOCKED → others can now get related anime
  └─ dashboard updates
  └─ sheets sync (assigned + completed tabs)
  └─ log channel: "✅ Completed: Frieren → @admin"

──────────────────────────────────────────────────────
STEP 4: AUTOMATIC EXPIRY (if admin never completes)
──────────────────────────────────────────────────────
Every hour, scheduler/expiry.py runs:
  └─ Find assignments where expires_at < now
  └─ Set assignment status → expired
  └─ Set anime status → pending (back to pool)
  └─ user.active_task_count -= 1
  └─ FRANCHISE UNLOCKED
  └─ Notify owners: "⏰ 2 assignments expired"
```

---

## 7. Assignment Engine (Deep Dive)

**File:** `helper/assignment.py`

### Priority System

```
PRIORITY_ORDER = ["high", "medium", "low"]
```

The engine always tries high-priority anime first. If nothing is available at
that priority, it tries medium, then low. Within a priority tier, the selection
is **random** — this prevents all admins from racing to the same title.

### Franchise Locking

When anime A is assigned from franchise "Attack on Titan":
```
franchises.attack_on_titan.has_active_assignment = True
franchises.attack_on_titan.active_assignee_id = user_id
```

Any other pending anime from the same franchise is **invisible** to the assignment
engine until the lock is released. This prevents:
- Two people encoding Season 1 and Season 2 simultaneously
- Ordering conflicts where Season 2 ships before Season 1

The lock is released when the assignment reaches `completed` or `invalid` status,
or when it expires.

### Reservation System

`/reserve <anime_id>` creates an assignment with `reserved=True`. Reserved
assignments have a **shorter expiry** (default 24h from `reservation_hours`
config) and are **not subject to regular expiry** — they have their own
`reserved_until` deadline instead.

### Force Assign & Reassign

`/forceassign` and `/reassign` both call `force_assign()` which:
1. Calls `_unassign()` on the current holder (if any) — releases franchise lock,
   returns anime to pool, decrements their counter
2. Creates a fresh assignment for the target user with `force_assigned` in history
3. Logs to `audit_logs` with old/new assignee

---

## 8. Franchise System (Deep Dive)

**File:** `helper/franchise.py`

### How Franchise Detection Works

When an anime is imported, `detect_franchise()` runs a 3-stage pipeline:

**Stage 1 — MAL Related Anime**
MAL API returns `related_anime` for each title. The bot checks if any related
MAL ID already exists in the DB with a `franchise_id`. If yes, use that same
franchise.

**Stage 2 — Slug + Alias + MAL ID Lookup**
```
"Attack on Titan: The Final Season Part 3"
    → strip season/part markers
    → "Attack on Titan"
    → slugify → "attack_on_titan"
    → look up franchises.franchise_id == "attack_on_titan"
```

**Stage 3 — RapidFuzz**
If stages 1 and 2 fail, compare the slug against all franchise `canonical_name`
and `aliases` using `fuzz.ratio`. If score ≥ `rapidfuzz_threshold` (default 90%),
it's a match.

### Slug Generation

```
"Attack on Titan: The Final Season Part 2 - Cour 2"
    remove: Season N, Part N, Cour N, Movie, OVA, ONA,
            Special, Recap, :..., S2, II, trailing numbers
    → "Attack on Titan"
    → lowercase, remove non-alphanumeric
    → spaces → underscores
    → "attack_on_titan"
```

### Franchise Rebuild

`/franchiserebuild` iterates every anime in the DB and re-runs `ensure_franchise()`
on each. Useful after bulk imports or if franchise links get corrupted.

---

## 9. Import System (Deep Dive)

**File:** `helper/importer.py`

### MAL API Pagination

```
GET /v2/anime/season/{year}/{season}
    ?limit=500&offset=0&fields=id,title,alternative_titles,
     media_type,num_episodes,studios,synopsis,main_picture,
     related_anime,start_season,status

Paginated until data.paging.next is absent.
Rate limited: 0.5s between pages.
```

### Duplicate Detection Pipeline

For each anime fetched:

```
1. MAL ID exact match
   → db.anime.find_one({"mal_id": mal_id})
   → if found: DUPLICATE

2. Franchise detection
   → detect_franchise(raw_item)
   → if franchise_id found AND franchise has existing anime: DUPLICATE

3. RapidFuzz title match
   → Compare against first 200 existing display_titles
   → if score ≥ threshold: DUPLICATE (flagged with matching title)
```

### Ignore Rules

| Config Key           | What it skips                                      |
|----------------------|----------------------------------------------------|
| `ignore_donghua`     | Entries with "Chinese animation" in synopsis       |
| `ignore_specials`    | `media_type == "special"`                          |
| `ignore_recaps`      | Title contains "recap" (case-insensitive regex)    |
| `ignore_music_videos`| `media_type == "music"`                            |
| `ignore_shorts`      | `media_type == "short"` (future MAL type)          |
| `ignore_unknown`     | `media_type == "unknown"`                          |

### Title Resolution

For `display_title`, the system runs `resolve_display_title()`:

```
1. If title_en is set → use it (cleaned)
2. If mal_id exists AND animeschedule_api_key is set:
   → GET animeschedule.net/API/v3/anime?malId={mal_id}
   → Use AnimeSchedule's title if returned
3. Fall back to title_romaji
4. Fall back to first synonym
5. Last resort: "Unknown Title"
```

### Preview Mode

`/importseason Fall 2023 --preview` runs the full pipeline but does NOT save
anything to MongoDB. Stats are shown but no confirm/discard buttons appear.
Useful for checking what would be imported without committing.

### Confirm/Discard Flow

```
Owner: /importseason Fall 2023

  Bot stores review items in memory:
  _pending[owner_id] = [anime_doc, anime_doc, ...]

  Bot shows:
  "89 new anime ready. Confirm import?"
  [✅ Keep All] [❌ Discard All]

  Owner: ✅ Keep All
  → confirm_import(items, [all anime_ids])
  → db.anime.insert_one() for each
  → ensure_franchise() for each
  → _pending.pop(owner_id)

  Owner: ❌ Discard All
  → _pending.pop(owner_id)
  → Nothing saved
```

---

## 10. Dashboard System (Deep Dive)

**File:** `helper/dashboard.py`

### 4 Pinned Messages

The dashboard channel contains exactly **4 pinned messages**, each auto-updated
every 5 minutes. Their Telegram message IDs are stored in MongoDB `config`:

| Config Key                  | Message Content                         |
|-----------------------------|-----------------------------------------|
| `dashboard_msg_global`      | Global stats + top 5 leaderboard        |
| `dashboard_msg_tasks`       | Active tasks board (who has what)       |
| `dashboard_msg_completions` | Last 10 completions                     |
| `dashboard_msg_invalid`     | Invalid/review queue                    |

### Update Flow

```
Every 5 minutes (scheduler/dashboard.py):
  update_all(app)
    ├─ _render_global()  → edit message dashboard_msg_global
    ├─ _render_tasks()   → edit message dashboard_msg_tasks
    ├─ _render_completions() → edit message dashboard_msg_completions
    └─ _render_invalid() → edit message dashboard_msg_invalid

On MESSAGE_NOT_MODIFIED error: silently ignored
On any other RPCError: call _init_message() to create a new message
```

### Per-Anime Tracking Messages

Every imported or assigned anime also gets its own message in the dashboard
channel via `upsert_anime_message()`. These are tracked in `telegram_messages`
collection:

```json
{
  "anime_id":   "uuid4",
  "message_id": 12345,
  "channel_id": -1001234567890,
  "message_type": "tracking"
}
```

When an anime status changes, its message is edited in-place. This gives a
live per-title status board in the channel.

### Log Channel

`log_event(app, message)` sends event strings to the log channel. Called on:
- Every assignment (`🎯 Assigned: Frieren → @admin`)
- Every status change (`📦 Encoded: ... → @admin`)
- Every completion (`✅ Completed: ...`)
- Every force action, import, drop, season operation

---

## 11. Google Sheets Sync (Deep Dive)

**File:** `helper/sheets.py`

### 7 Tabs Auto-Created

| Tab Name       | Content                                              |
|----------------|------------------------------------------------------|
| Overview       | Total/pending/assigned/completed/dropped counts      |
| Pending        | All pending anime with priority, franchise, import date |
| Assigned       | Active assignments with assignee, expiry date        |
| Completed      | All completed with who did it and when               |
| Dropped        | Dropped anime with reasons                           |
| Admin Stats    | Per-admin completion/encoded/leeched/invalid counts  |
| Season Reports | Year/season breakdown with completion percentages    |

### Sync Architecture

All gspread calls run in `asyncio.get_event_loop().run_in_executor(None, fn)`
because gspread is synchronous. This prevents blocking the event loop.

```python
async def _write(ws, rows):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, ws.clear)
    await loop.run_in_executor(None, partial(ws.update, "A1", rows))
```

### Trigger Points

| Event                    | Tabs synced                   |
|--------------------------|-------------------------------|
| Import confirmed         | Pending                       |
| Task assigned            | Assigned                      |
| Task completed           | Assigned + Completed          |
| /report command          | All tabs (full_sync)          |
| /exportsheet command     | All tabs (full_sync)          |
| Auto-sync (1h scheduler) | All tabs (if enabled)         |
| /exportseason            | Creates a per-season tab      |

### Export Sheet Button

After `/exportsheet`, if `sheets_send_link_on_export=true`, the bot replies with
an inline button `[📊 Open Google Sheet]` linking directly to the spreadsheet.

If `sheets_send_file_on_export=true`, it also uploads individual CSV files for
each tab to the backup channel.

---

## 12. Backup System (Deep Dive)

**File:** `helper/backup.py`

### What Gets Backed Up

9 collections are included in every backup:
```
users, anime, franchises, assignments, activity_logs,
audit_logs, telegram_messages, config, dropped
```

### Backup Process

```
run_backup(app):
  ├─ Generate backup_id (8-char UUID prefix)
  ├─ Insert pending record to db.backups
  ├─ Create in-memory ZIP (BytesIO)
  │   └─ For each collection:
  │       ├─ Stream all documents
  │       ├─ Convert ObjectId + datetime to strings
  │       └─ Write as {collection}.json inside ZIP
  ├─ Send ZIP to backup_channel via app.send_document()
  ├─ Mark backup record as success (with message_id for retrieval)
  └─ On failure:
      ├─ Mark record as failed with error message
      └─ Notify all owners via DM
```

### Backup Records

Every backup (success or failure) is recorded in `db.backups`:
```json
{
  "backup_id":             "a3f2b1c0",
  "status":                "success",
  "size_bytes":            524288,
  "file_name":             "anime_backup_20240601_030000_a3f2b1c0.zip",
  "telegram_message_id":   99999,
  "telegram_channel_id":  -1001234567890,
  "created_at":            "2024-06-01T03:00:00",
  "verified_at":           "2024-06-01T03:00:05"
}
```

### Manual Backup

`/backup` triggers `run_backup()` immediately, bypassing the scheduler.
`/backupstatus` shows the last 5 backup records with their status and size.

---

## 13. Scheduler Jobs

**Files:** `scheduler/*.py`

All jobs are registered at startup and run as APScheduler async jobs.

| Job ID               | Interval | What it does                                              |
|----------------------|----------|-----------------------------------------------------------|
| `daily_backup`       | 24h      | `run_backup(app)` — full DB ZIP to backup channel        |
| `dashboard_refresh`  | 5m       | `update_all(app)` — edit all 4 pinned messages           |
| `assignment_expiry`  | 1h       | `expire_old_assignments()` — finds overdue, releases     |
| `sheets_sync`        | 1h       | `full_sync()` if `sheets_auto_sync=true`                 |
| `health_snapshot`    | 15m      | `write_health_snapshot()` — CPU/mem/counts to DB         |

### Dynamic Interval

`dashboard_refresh` reads `dashboard_update_interval` from DB on each run and
reschedules itself if the value changed. This lets owners change the interval
without restarting the bot.

---

## 14. Config System (Deep Dive)

**File:** `database/config.py`

### 30-Key Schema

Every config key has full metadata:

```python
{
    "key":         "task_limit",
    "default":     5,
    "type":        "int",        # str | int | bool | list
    "category":    "tasks",      # telegram | api | sheets | tasks | scheduler | system
    "label":       "Global Task Limit",
    "description": "Default max active tasks per admin",
    "secret":      False,        # True = masked in /panel display
}
```

### TTL Cache

All config reads go through a 60-second in-memory cache:
```
cfg.get("task_limit")
  ├─ Check _cache["task_limit"] — if fresh, return it
  └─ Otherwise: MongoDB read → cache → return
```

`cfg.set()` always invalidates the cache entry for that key, so changes are
visible immediately after saving.

### Type Coercion

When saving via `/set` or `/panel`:
- `"int"` → `int(value)` 
- `"bool"` → `"on"/"true"/"1"/"yes"` → `True`, else `False`
- `"list"` → `value.split(",")` → `[str, str, ...]`
- `"str"` → `value.strip()`

### Secret Masking

Keys marked `"secret": True` (MAL client ID, AnimeSchedule API key, webhook secret)
are masked in `/panel` display:
```
"abcdefgh1234" → "ab••••••••34"
```

---

## 15. Drop / Restore / Delete System

**File:** `plugins/drops.py`

### Status vs. Delete Distinction

| Operation         | Command                         | Effect                                            |
|-------------------|---------------------------------|---------------------------------------------------|
| Drop              | `/dropanime <id> [reason]`      | `status=dropped`, added to `dropped` collection   |
| Restore           | `/restoreanime <id>`            | `status=pending`, removed from `dropped`          |
| Soft delete       | `/deleteanime <id> confirm`     | `deleted=true` — invisible to all queries         |
| Restore soft      | `/restoreanime <id>`            | `deleted=false`, `status=pending`                 |

### Dropped Collection

Dropping an anime adds a record to `db.dropped`:
```json
{
  "anime_id":     "uuid4",
  "title":        "Some Anime",
  "reason":       "No subtitles available",
  "dropped_by":   123456789,
  "date":         "2024-06-01T00:00:00",
  "original_data": { ...full anime document... }
}
```

This preserves the original document so nothing is truly lost. `/restoreanime`
reads from `original_data` if needed.

### Season-Level Operations

| Command                                 | Effect                                      |
|-----------------------------------------|---------------------------------------------|
| `/dropseason Spring 2024`               | Drops all **pending** anime in that season  |
| `/deleteseason Spring 2024 confirm`     | Soft-deletes ALL anime in that season       |
| `/reassignseason Spring 2024`           | Returns all assigned anime to pool          |
| `/restoreseason Spring 2024`            | Un-drops + un-deletes all in that season    |
| `/exportseason Spring 2024`             | Creates a Sheets tab for that season        |

---

## 16. Text Input State Machine

**File:** `plugins/text_router.py`

Two features require users to type a free-text reply:
1. **Note adding** (after pressing 📝 Add Note button)
2. **Panel config editing** (after pressing ✏️ Edit key in /panel)

Both register on `filters.text & filters.private`, which would conflict if both
decorated `@Client.on_message`. The solution is a **single router** that checks
state and dispatches:

```
User sends a plain text message in private chat
          │
          ▼
   text_router.py: _text_router()
          │
          ├─ uid in _pending_notes?
          │      YES → handle_note_reply()  (from plugins/assignments.py)
          │              ├─ "/cancel" → clear state, "❌ Cancelled"
          │              └─ any text → save to assignment.notes[], confirm
          │
          ├─ uid in _state AND uid is owner?
          │      YES → handle_panel_input()  (from plugins/panel.py)
          │              ├─ "/cancel" → clear state, "❌ Edit cancelled"
          │              ├─ invalid type → "❌ Invalid: must be integer" + retry
          │              └─ valid → cfg.set(), log audit, "✅ Updated!"
          │
          └─ No state → silently ignore
```

### Why not just use `/cancel` as a command?

Panel and note flows both check for the string `/cancel` as plain text (not as
a command). This is intentional — `/cancel` as a command would be intercepted by
other handlers before reaching the state machine.

---

## 17. All Commands Reference

### Admin Commands (all admins + owners)

| Command              | What it does                                                         |
|----------------------|----------------------------------------------------------------------|
| `/start`             | Register + see quick-start menu                                      |
| `/help`              | Interactive help pages (owner or admin view)                         |
| `/nexttask`          | Get the next best-fit assignment                                      |
| `/mytask`            | See all your active assignments with inline action buttons           |
| `/reserve <id>`      | Reserve a specific anime for 24h                                     |
| `/away`              | Mark yourself unavailable — no new tasks assigned                    |
| `/back`              | Mark yourself available again                                        |
| `/mystats`           | Your personal stats with progress bars                               |
| `/leaderboard [N]`   | Top N performers with completion bars                                |
| `/find <query>`      | Search by title, alias, franchise name, MAL ID                      |
| `/franchise <name>`  | Full franchise view: all entries, lock status, progress bar          |

### Owner-Only Commands

**Import**

| Command                              | What it does                                        |
|--------------------------------------|-----------------------------------------------------|
| `/importseason <Season> <Year>`      | Import from MAL with confirm/discard preview        |
| `/importseason ... --preview`        | Dry run — shows stats, saves nothing                |
| `/importyear <Year>`                 | Import all 4 seasons, one confirm for all           |

**Admin Management**

| Command                          | What it does                                              |
|----------------------------------|-----------------------------------------------------------|
| `/addadmin @username`            | Grant admin (pre-registers if not yet started)            |
| `/removeadmin @username`         | Revoke access                                             |
| `/listadmins`                    | Show all admins + away status + active/completed counts   |
| `/maxtasks [N or @user N]`       | Set global or per-user task limit                         |
| `/forceassign <id> @user`        | Assign specific anime to specific user                    |
| `/reassign <id> @user`           | Move assignment from current holder to new user           |
| `/priority <id> high/medium/low` | Set anime priority                                        |

**Manual Entry**

| Command                            | What it does                                            |
|------------------------------------|---------------------------------------------------------|
| `/manual_anime T\|Y\|S[|Type][|URL]`| Add one anime manually (pipe-separated fields)         |
| `/manual_import` (+ lines below)   | Batch add: one `Title\|Year\|Season` per line          |
| `/completed_task <id>`             | Force-complete any active task (owner override)         |
| `/edit_title <id> <new title>`     | Permanently lock display title (never overwritten)      |

**Drop / Restore / Delete**

| Command                           | What it does                                             |
|-----------------------------------|----------------------------------------------------------|
| `/dropanime <id> [reason]`        | Drop + log reason                                        |
| `/restoreanime <id>`              | Restore to pending                                       |
| `/dropped`                        | List 20 most recently dropped                            |
| `/deleteanime <id> confirm`       | Soft-delete (invisible to all queries)                   |
| `/dropseason S Y`                 | Drop all pending in a season                             |
| `/deleteseason S Y confirm`       | Soft-delete entire season                                |
| `/reassignseason S Y`             | Return assigned anime to pool                            |
| `/restoreseason S Y`              | Restore all dropped/deleted in a season                  |
| `/exportseason S Y`               | Export season to a Google Sheets tab                     |

**Dashboard & Channels**

| Command                       | What it does                                                |
|-------------------------------|-------------------------------------------------------------|
| `/setdashboard <id>`          | Set dashboard channel                                       |
| `/setlogchannel <id>`         | Set log channel                                             |
| `/setbackupchannel <id>`      | Set backup channel                                          |
| `/rebuilddashboard`           | Delete and recreate all 4 pinned messages                   |

**Franchise Management**

| Command               | What it does                                                    |
|-----------------------|-----------------------------------------------------------------|
| `/franchiselist`      | Show all franchises with lock status and entry counts           |
| `/franchiserebuild`   | Relink all anime to franchises (repair job)                     |

**Reports & Export**

| Command                       | What it does                                                |
|-------------------------------|-------------------------------------------------------------|
| `/report [Season Year]`       | Full platform report or season-specific breakdown           |
| `/exportsheet`                | Full Google Sheets sync + optional link button + CSV files  |
| `/audio_stats`                | Per-admin completion breakdown                              |
| `/stats`                      | Global stats with progress bar + leaderboard                |
| `/userstats @username`        | Stats for a specific user                                   |

**Backup**

| Command            | What it does                                                       |
|--------------------|--------------------------------------------------------------------|
| `/backup`          | Manual backup now                                                  |
| `/backupstatus`    | Last 5 backup records                                              |

**System**

| Command          | What it does                                                         |
|------------------|----------------------------------------------------------------------|
| `/health`        | Full system status: MongoDB, Sheets, CPU, memory, uptime, channels  |
| `/ping`          | Latency check                                                        |
| `/panel`         | Full tree-nav config editor with 30 keys, type hints, secret masking|
| `/set <k> <v>`   | Quick-set any config key from CLI                                    |

---

## 18. Data Flow Diagrams

### Assignment Flow

```
/nexttask
    │
    ├─ DB: users.find(telegram_id)
    ├─ DB: assignments.count(user_id, active)     ← check limit
    ├─ DB: assignments.find(user_id, active)      ← get exclude list
    │
    ├─ For priority in [high, medium, low]:
    │   ├─ DB: anime.find(status=pending, priority=P, not in exclude)
    │   └─ For each candidate:
    │       └─ DB: franchises.find(franchise_id) → check locked
    │           └─ if not locked → candidates.append()
    │
    ├─ random.choice(candidates)                  ← fair random pick
    │
    ├─ DB: assignments.insert_one(doc)
    ├─ DB: anime.update_one(status=assigned)
    ├─ DB: users.update_one(active_task_count += 1)
    ├─ DB: franchises.update_one(locked=True)
    ├─ DB: activity_logs.insert_one(action=assigned)
    │
    ├─ Telegram: reply with task card + buttons
    ├─ Telegram: upsert_anime_message (dashboard channel)
    ├─ Telegram: update_all (4 pinned messages)
    ├─ Telegram: log_event (log channel)
    └─ Sheets: sync_assigned()
```

### Import Flow

```
/importseason Fall 2023
    │
    ├─ MAL API: fetch all pages
    │     GET /v2/anime/season/2023/fall?limit=500&offset=0
    │     GET /v2/anime/season/2023/fall?limit=500&offset=500
    │     ...until no next page
    │
    ├─ For each raw_item:
    │   ├─ _check_ignore() → skip if donghua/special/recap/etc.
    │   ├─ _check_dup()
    │   │   ├─ DB: anime.find(mal_id)
    │   │   ├─ detect_franchise() → stage 1/2/3
    │   │   └─ RapidFuzz against 200 existing titles
    │   └─ _build_doc()
    │       ├─ resolve_display_title() → EN/AnimeSchedule/Romaji
    │       ├─ detect_franchise()
    │       └─ build full document with UUID
    │
    ├─ Telegram: reply ImportStats summary
    ├─ Store items in memory: _pending[owner_id]
    └─ Telegram: [✅ Keep All] [❌ Discard All] buttons

Owner clicks ✅:
    ├─ DB: anime.insert_one() × N
    ├─ For each: ensure_franchise() → DB: franchises.upsert()
    ├─ Telegram: update_all()
    ├─ Telegram: upsert_anime_message() × N
    └─ Sheets: sync_pending()
```

---

## 19. Layer Dependency Rules

```
plugins/   → helper/    ✅ allowed
plugins/   → database/  ✅ allowed (for simple lookups only)
helper/    → database/  ✅ allowed
helper/    → plugins/   ❌ NEVER
database/  → helper/    ❌ NEVER
database/  → plugins/   ❌ NEVER
scheduler/ → helper/    ✅ allowed
scheduler/ → plugins/   ❌ NEVER
```

These are enforced and verified by grep in CI. The audit shows zero violations.

---

## 20. First Boot Checklist

```
1. Configure .env
   ├─ API_ID         (from my.telegram.org)
   ├─ API_HASH       (from my.telegram.org)
   ├─ BOT_TOKEN      (from @BotFather)
   ├─ MONGODB_URI    (from MongoDB Atlas)
   └─ OWNER_ID       (your Telegram user ID — from @userinfobot)

2. Start the bot
   python bot.py

3. Send /start to the bot
   → You should see the owner welcome message

4. Set up channels (bot must be admin in each):
   /setdashboard -1001234567890
   /setlogchannel -1001234567891
   /setbackupchannel -1001234567892

5. Build the dashboard:
   /rebuilddashboard
   → 4 messages pinned in dashboard channel

6. Set MAL API key (for imports):
   /set mal_client_id YOUR_MAL_CLIENT_ID
   (Get from: myanimelist.net/apiconfig)

7. Import your first season:
   /importseason Fall 2023 --preview
   → Check the stats
   /importseason Fall 2023
   → Click ✅ Keep All

8. Add your admins:
   /addadmin @alice
   /addadmin @bob
   → They can now use /nexttask

9. Optional: Set up Google Sheets:
   /set sheets_credentials_file credentials.json
   /set sheets_spreadsheet_id YOUR_SPREADSHEET_ID
   /set sheets_enabled on
   /set sheets_auto_sync on
   /exportsheet   (trigger first sync)

10. Verify everything:
    /health        (all green?)
    /stats         (anime count correct?)
    /panel         (all channels set?)
```
