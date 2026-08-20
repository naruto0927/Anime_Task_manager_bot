"""
config.py — Bootstrap configuration.

Only the 4 secrets needed to start the process.
Everything else lives in MongoDB and is managed via /panel.

Edit the values below directly — no .env needed.
"""
from __future__ import annotations

# ── Required ──────────────────────────────────────────────────────────────
API_ID:       int = 20167916
API_HASH:     str = "325de70c258003ff1c30fb02077dde25"
BOT_TOKEN:    str = "8222430746:AAHDxx4sBZoobhECKo6vu1ZcTy4DoKq8Hkw"
MONGODB_URI:  str = (
    "mongodb://bloodpdf:naruto.dev.09@ac-qivczm0-shard-00-00.kwrg2jz.mongodb.net:27017,ac-qivczm0-shard-00-01.kwrg2jz.mongodb.net:27017,ac-qivczm0-shard-00-02.kwrg2jz.mongodb.net:27017/?ssl=true&replicaSet=atlas-76a3x9-shard-0&authSource=admin&appName=BloodPDFCluster"
)

# ── Optional ──────────────────────────────────────────────────────────────
OWNER_ID:        int = 6672752177
MONGODB_DB_NAME: str = "anime_platform"
LOG_LEVEL:       str = "INFO"

# ── External APIs ─────────────────────────────────────────────────────────
ANILIST_API:  str = "https://graphql.anilist.co"
AS_TOKEN:     str = ""   # animeschedule.net Bearer token (optional)
AS_BASE_URL:  str = "https://animeschedule.net"
AS_CDN_BASE:  str = "https://cdn.animeschedule.net"
AS_NULL_DT:   str = "0001-01-01T00:00:00Z"
