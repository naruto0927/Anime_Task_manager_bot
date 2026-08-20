# AnimeAssignBot

A Pyrogram-native Telegram bot for managing anime encoding/translation assignments
across a team of admins — with franchise tracking, Google Sheets sync, scheduled
backups, and a live dashboard channel.

---

## Architecture

```
plugins/   ← Telegram commands only
helper/    ← All business logic
database/  ← All MongoDB operations
scheduler/ ← All background jobs
bot.py     ← Single startup file
config.py  ← 4 env vars only
```

---

## Installation

### 1. Clone & install dependencies

```bash
git clone https://github.com/yourname/AnimeAssignBot
cd AnimeAssignBot
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your credentials
```

**Required env vars:**

| Variable       | Description                         |
|----------------|-------------------------------------|
| `API_ID`       | Telegram API ID (my.telegram.org)   |
| `API_HASH`     | Telegram API Hash                   |
| `BOT_TOKEN`    | Bot token from @BotFather           |
| `MONGODB_URI`  | MongoDB connection string           |

**Optional:**

| Variable           | Default           | Description              |
|--------------------|-------------------|--------------------------|
| `OWNER_ID`         | `0`               | Your Telegram user ID    |
| `MONGODB_DB_NAME`  | `anime_platform`  | MongoDB database name    |
| `LOG_LEVEL`        | `INFO`            | Logging level            |

---

## MongoDB Setup

1. Create a free cluster at [MongoDB Atlas](https://cloud.mongodb.com)
2. Create a database user with read/write access
3. Whitelist `0.0.0.0/0` (or your server IP) in Network Access
4. Copy the connection string into `MONGODB_URI`

All indexes are created automatically on first boot.  
All other settings (task limits, channels, Sheets config, etc.) are stored in MongoDB
and managed through `/panel`.

---

## Bot Setup

### First boot checklist

1. Start the bot: `python bot.py`
2. Send `/start` to the bot
3. Set your dashboard channel: `/setdashboard -1001234567890`
4. Set your log channel: `/setlogchannel -1001234567891`
5. Set your backup channel: `/setbackupchannel -1001234567892`
6. Build the dashboard: `/rebuilddashboard`
7. Import your first season: `/importseason Spring 2025`

> **Important:** The bot must be an **admin** in all three channels.

---

## Koyeb Deployment

1. Push your code to GitHub (without `.env` — use Koyeb env vars)
2. Create a new Koyeb service → choose **Docker**
3. Set all 4 required env vars in the Koyeb dashboard
4. Deploy — Koyeb will build the image and run the bot

**Recommended Koyeb settings:**
- Instance type: Nano (sufficient for most deployments)
- Health check: HTTP on port 8080, or disable (bot uses Telegram long polling)
- Persistent storage: Not required (MongoDB handles all state)

---

## Commands Reference

### Admin Commands

| Command              | Description                                   |
|----------------------|-----------------------------------------------|
| `/start`             | Register and see your quick-start menu        |
| `/nexttask`          | Get your next anime assignment                |
| `/mytask`            | View your active assignments                  |
| `/reserve <id>`      | Reserve a specific anime                      |
| `/away`              | Mark yourself as away (no new tasks)          |
| `/back`              | Resume receiving tasks                        |
| `/mystats`           | Your personal statistics                      |
| `/leaderboard`       | Top performers                                |
| `/find <query>`      | Search for anime by title                     |
| `/franchise <name>`  | View franchise details                        |

### Owner Commands

| Command                            | Description                              |
|------------------------------------|------------------------------------------|
| `/importseason <Season> <Year>`    | Import a seasonal batch from MAL         |
| `/importyear <Year>`               | Import all 4 seasons for a year          |
| `/manual_anime <title>\|<year>\|…` | Manually add an anime                    |
| `/manual_import` (multiline)       | Batch manual import                      |
| `/completed_task <anime_id>`       | Force-complete any task                  |
| `/addadmin @username`              | Grant admin access                       |
| `/removeadmin @username`           | Revoke admin access                      |
| `/listadmins`                      | List all registered admins               |
| `/forceassign <id> @user`          | Force-assign anime to a user             |
| `/reassign <id> @user`             | Reassign from current holder             |
| `/report [Season Year]`            | Full platform or season report           |
| `/exportsheet [all\|csv\|sheets]`  | Export data to Sheets and/or CSV         |
| `/audio_stats`                     | Per-admin breakdown                      |
| `/stats`                           | Global statistics                        |
| `/userstats @user`                 | Stats for a specific user                |
| `/maxtasks [limit\|@user limit]`   | Set global or per-user task limit        |
| `/priority <anime_id> <level>`     | Set anime priority (high/medium/low)     |
| `/backup`                          | Run immediate backup                     |
| `/backupstatus`                    | Show last 5 backup records               |
| `/rebuilddashboard`                | Rebuild all dashboard messages           |
| `/setdashboard <channel_id>`       | Set dashboard channel                    |
| `/setlogchannel <channel_id>`      | Set event log channel                    |
| `/setbackupchannel <channel_id>`   | Set backup channel                       |
| `/franchiselist`                   | List all franchises                      |
| `/franchiserebuild`                | Rebuild franchise links for all anime    |
| `/health`                          | System health and status                 |
| `/ping`                            | Latency check                            |
| `/panel` or `/settings`            | Interactive settings panel               |
| `/set <key> <value>`               | Set any config key directly              |

---

## Dashboard Setup

The dashboard uses **3 Telegram channels** (can be the same one):

1. **Dashboard Channel** — pinned messages auto-updated every 5 min:
   - Global stats overview
   - Active tasks board
   - Recent completions
   - Invalid / review queue

2. **Log Channel** — event stream (assignments, completions, imports)

3. **Backup Channel** — daily `.zip` backups of the entire database

Setup steps:
```
/setdashboard -1001234567890
/setlogchannel -1001234567891
/setbackupchannel -1001234567892
/rebuilddashboard
```

---

## Google Sheets Setup

1. Create a [Google Cloud project](https://console.cloud.google.com)
2. Enable the **Google Sheets API** and **Google Drive API**
3. Create a **Service Account** → download the JSON credentials file
4. Share your spreadsheet with the service account email
5. Upload `credentials.json` to your server/container
6. Configure in bot:

```
/set sheets_credentials_file credentials.json
/set sheets_spreadsheet_id 1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms
/set sheets_enabled on
/set sheets_auto_sync on
/exportsheet sheets
```

**Spreadsheet tabs created automatically:**
- Overview, Pending, Assigned, Completed, Dropped, Admin Stats, Season Reports

---

## Import Settings

Control what gets imported via `/panel → Import` or `/set`:

| Key                    | Default | Description                           |
|------------------------|---------|---------------------------------------|
| `ignore_donghua`       | false   | Skip Chinese animations               |
| `ignore_specials`      | false   | Skip special episodes                 |
| `ignore_recaps`        | false   | Skip recap episodes                   |
| `ignore_music_videos`  | false   | Skip music videos                     |
| `ignore_shorts`        | false   | Skip short-form anime                 |
| `ignore_unknown`       | false   | Skip entries with unknown type        |
| `rapidfuzz_threshold`  | 90      | Fuzzy duplicate detection sensitivity |

---

## Scheduled Jobs

| Job                  | Interval | Description                         |
|----------------------|----------|-------------------------------------|
| `assignment_expiry`  | 1 hour   | Expire overdue assignments          |
| `dashboard_refresh`  | 5 min    | Update dashboard messages           |
| `daily_backup`       | 24 hours | Full database backup to channel     |
| `sheets_sync`        | 1 hour   | Auto-sync Google Sheets (if enabled)|
| `health_snapshot`    | 15 min   | Write health metrics to MongoDB     |

---

## License

MIT
