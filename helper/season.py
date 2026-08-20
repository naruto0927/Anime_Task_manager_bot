"""
services/season.py — MyAnimeList seasonal TV anime scraper enriched via AniList.

Results are cached for 24 h in MongoDB.  Each title is returned as:
    ``"<English or Romaji> | <MAL title>"``

Pagination helper (``paginate``) is a pure static method.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup

from config import AS_TOKEN

logger = logging.getLogger(__name__)


class SeasonScraper:
    """Scrape MAL seasonal anime and enrich with AniList English titles."""

    VALID_SEASONS: tuple = ("winter", "spring", "summer", "fall")
    CACHE_TTL:     int   = 86400   # 24 hours

    _MAL_HEADERS: dict = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept":          "text/html,*/*",
        "Accept-Language": "en-US,en;q=0.9",
    }

    _ANILIST_Q: str = """
    query ($search: String) {
      Media(search: $search, type: ANIME, isAdult: false) {
        title { romaji english }
        relations {
          edges {
            relationType
          }
        }
      }
    }
    """

    def __init__(self, as_scraper=None) -> None:
        self.as_scraper = as_scraper   # AnimeScheduleScraper instance, injected at boot
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=20, headers=self._MAL_HEADERS, follow_redirects=True
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # ── Public ────────────────────────────────────────────────────────────

    async def get_season(self, year: int, season: str) -> list:
        """
        Return ``["English Title | MAL Title", ...]`` for TV (New) anime.
        Cached for 24 h.  Returns [] on failure.
        """
        season = season.lower().strip()
        if season not in self.VALID_SEASONS:
            return []

        cache_key = f"season:{year}:{season}"
        cached = await self.db.get_cache(cache_key)
        if cached is not None:
            logger.debug("Season cache hit: %s", cache_key)
            return cached

        mal_titles = await self._fetch_mal_titles(year, season)
        if not mal_titles:
            return []

        enriched = await self._enrich_titles(mal_titles)
        total = len(enriched.get("new", [])) + len(enriched.get("continuing", []))
        logger.info(
            "Season scraped: %d titles (%d new, %d continuing) for %s %d",
            total,
            len(enriched.get("new", [])),
            len(enriched.get("continuing", [])),
            season, year,
        )
        return enriched

    # ── MAL Scrape ────────────────────────────────────────────────────────

    async def _fetch_mal_titles(self, year: int, season: str) -> list:
        url = f"https://myanimelist.net/anime/season/{year}/{season}"
        try:
            r = await self.client.get(url)
            if r.status_code != 200:
                logger.warning("MAL season page returned %d", r.status_code)
                return []
            return await asyncio.get_event_loop().run_in_executor(
                None, self._parse_mal_html, r.text
            )
        except Exception as exc:
            logger.warning("MAL fetch error: %s", exc)
            return []

    @staticmethod
    def _parse_mal_html(html: str) -> list:
        """Extract TV (New) anime titles from the MAL season page."""
        try:
            soup     = BeautifulSoup(html, "html.parser")
            seasonal = soup.find("div", class_="seasonal-anime-list")
            if not seasonal:
                return []
            tv_new_header = seasonal.find(
                "div", class_="anime-header",
                string=re.compile(r"TV .New.", re.I)
            )
            if not tv_new_header:
                return []
            titles = []
            for anime in tv_new_header.find_all_next(
                "div", class_="seasonal-anime", limit=200
            ):
                prev_hdr = anime.find_previous_sibling("div", class_="anime-header")
                if prev_hdr and not re.search(r"TV \(New\)", prev_hdr.text, re.I):
                    break
                tag = anime.select_one("h2.h2_anime_title a.link-title")
                if tag:
                    titles.append(tag.text.strip())
            return titles
        except Exception as exc:
            logger.error("MAL parse error: %s", exc)
            return []

    # ── AniList Enrichment ────────────────────────────────────────────────

    # Patterns that indicate a returning/sequel anime
    _SEQUEL_PATTERNS = re.compile(
        r"""
        (?:
            \bseason\s*[2-9]              |  # Season 2, Season 3 ...
            \b[2-9](?:nd|rd|th)\s+season  |  # 2nd Season, 3rd Season ...
            \bpart\s*[2-9]               |  # Part 2, Part 3 ...
            \b[2-9](?:nd|rd|th)\s+part   |  # 2nd Part ...
            \bcour\s*[2-9]               |  # Cour 2 ...
            \bii\b | \biii\b | \biv\b | \bv\b |  # Roman numerals
            \b2nd\b | \b3rd\b | \b4th\b | \b5th\b |  # ordinals
            \bfinal\s+season\b           |  # Final Season
            \blast\s+season\b            |
            \bcontinuation\b             |
            \bthe\s+return\b             |
            \brefrain\b                  |
            \bcontinued\b                |
            -hen\b                       |  # Japanese arc: Sennen Kessen-hen
            \barc\b                      |  # "Arc" in title
            \bchapter\s+\d              |  # Chapter 2
            (?::\s*.+\s+-\s+\w)         |  # "Title: Subtitle - Part" (Bleach style)
            [\s:]\d+$                       # trailing digit: "Anime 2"
        )
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    # Known long-running franchises — always "returning" when listed in a season
    _KNOWN_FRANCHISES = re.compile(
        r"""
        \b(?:
            bleach | naruto | one\s*piece | dragon\s*ball |
            fairy\s*tail | attack\s*on\s*titan | shingeki |
            boruto | sword\s*art\s*online |\bsao\b |
            black\s*clover | my\s*hero\s*academia | boku\s*no\s*hero |
            jujutsu\s*kaisen | demon\s*slayer | kimetsu |
            fullmetal\s*alchemist | hunter\s*x\s*hunter |
            tokyo\s*ghoul | re\s*zero | overlord |
            danmachi | konosuba | tensura | slime |
            mushoku\s*tensei | jobless\s*reincarnation |
            isekai\s*ittara\s*honki\s*dasu |
            tensei\s*shitara\s*slime |
            youjo\s*senki | tanya\s*the\s*evil |
            konosuba | kono\s*subarashii |
            re\s*zero | rezero
        )\b
        """,
        re.VERBOSE | re.IGNORECASE,
    )

    @classmethod
    def _is_returning(cls, mal_title: str, eng_title: str) -> bool:
        """
        Return True if title indicates a returning/sequel series.

        Checks (in order):
          1. Sequel pattern regex (Season N, Part N, II, -hen, arc subtitle, etc.)
          2. Known long-running franchise list (Bleach, Naruto, One Piece, etc.)
        """
        for t in (mal_title, eng_title or ""):
            if cls._SEQUEL_PATTERNS.search(t):
                return True
            if cls._KNOWN_FRANCHISES.search(t):
                return True
        return False

    async def _enrich_titles(self, mal_titles: list) -> dict:
        """
        Fetch English titles + sequel status for each MAL title.

        Detection order (fastest-first, APIs are bonuses):
          1. Title pattern + known franchise  (instant, no network)
          2. animeschedule.net API            (fast, already authenticated)
          3. AniList GraphQL                  (slow, rate-limited, optional)

        Returns:
          { "new": [...], "continuing": [...] }
        """
        sem = asyncio.Semaphore(5)

        async def fetch_one(mal_title: str) -> tuple[str, bool]:
            async with sem:
                # ── Step 1: Pattern detection (always runs, no network) ───
                pattern_is_return = self._is_returning(mal_title, "")

                # ── Step 2: animeschedule.net (fast, English + sequel) ────
                as_eng       = None
                as_is_sequel = None
                if self.as_scraper is not None:
                    try:
                        as_eng, as_is_sequel = await self._animeschedule_english_and_sequel(mal_title)
                    except Exception as exc:
                        logger.debug("animeschedule error for '%s': %s", mal_title, exc)

                # ── Step 3: AniList (optional — skip if already have both) ─
                al_eng       = None
                al_is_sequel = None
                # Only call AniList if animeschedule didn't give us both
                if as_eng is None or as_is_sequel is None:
                    try:
                        al_eng, al_is_sequel = await self._anilist_english(mal_title)
                    except Exception as exc:
                        logger.debug("AniList error for '%s': %s", mal_title, exc)

                await asyncio.sleep(0.1)

                # ── Resolve English title ─────────────────────────────────
                # Priority: AniList english > animeschedule english > MAL title
                if al_eng and al_eng.lower() not in (
                    mal_title.lower(), (as_eng or "").lower()
                ):
                    eng = al_eng
                elif as_eng and as_eng.lower() != mal_title.lower():
                    eng = as_eng
                else:
                    eng = al_eng  # may be romaji fallback from AniList

                display = (
                    f"{eng} | {mal_title}"
                    if (eng and eng.lower() != mal_title.lower())
                    else mal_title
                )

                # ── Resolve sequel flag ───────────────────────────────────
                # Priority: AniList PREQUEL relation > animeschedule > pattern
                if al_is_sequel is True:
                    is_return = True
                    src = "AniList"
                elif as_is_sequel is True:
                    is_return = True
                    src = "animeschedule"
                elif al_is_sequel is False and as_is_sequel is False:
                    # Both APIs say original — patterns are still safety net
                    is_return = pattern_is_return
                    src = f"both APIs=new, pattern={pattern_is_return}"
                elif pattern_is_return:
                    # APIs unknown/empty but pattern matched
                    is_return = True
                    src = "pattern"
                else:
                    is_return = False
                    src = "all negative"

                logger.debug(
                    "[enrich] '%s' al=%s as=%s pat=%s → %s (%s)  title='%s'",
                    mal_title, al_is_sequel, as_is_sequel,
                    pattern_is_return, is_return, src, display,
                )
                return display, is_return

        pairs = await asyncio.gather(*[fetch_one(t) for t in mal_titles])

        new_titles  = [d for d, ret in pairs if not ret]
        cont_titles = [d for d, ret in pairs if ret]

        logger.info(
            "Season enriched: %d new, %d returning",
            len(new_titles), len(cont_titles),
        )
        return {"new": new_titles, "continuing": cont_titles}

    async def _anilist_english(self, search: str) -> tuple[Optional[str], Optional[bool]]:
        """
        Query AniList GraphQL for english title and PREQUEL relation.
        Returns (english_title, is_sequel) where is_sequel is True/False/None.
        None means AniList returned no data (blocked, rate-limited, etc).
        """
        try:
            r = await self.client.post(
                "https://graphql.anilist.co",
                json={"query": self._ANILIST_Q, "variables": {"search": search}},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=8,
            )
            if r.status_code != 200:
                logger.debug("AniList HTTP %d for '%s'", r.status_code, search)
                return None, None

            data  = r.json()
            media = (data.get("data") or {}).get("Media") or {}
            if not media:
                return None, None

            t       = media.get("title") or {}
            eng     = t.get("english") or None
            romaji  = t.get("romaji")  or None

            edges = (media.get("relations") or {}).get("edges") or []
            types = {(e.get("relationType") or "").upper() for e in edges if e}

            if "PREQUEL" in types:
                is_sequel = True
            elif types:
                is_sequel = False
            else:
                is_sequel = None   # no relation data

            # Return strict English only (not romaji as english)
            final_eng = eng if (eng and eng != romaji) else romaji
            return final_eng, is_sequel

        except Exception as exc:
            logger.debug("AniList error for '%s': %s", search, exc)
            return None, None

    async def _animeschedule_english_and_sequel(
        self, romaji: str
    ) -> tuple[Optional[str], Optional[bool]]:
        """
        Query animeschedule.net for both the English title AND sequel status.

        Returns:
          (english_title, is_sequel)
          english_title: str or None
          is_sequel:     True/False if determinable, None if unknown
        """
        if not AS_TOKEN:
            return None, None

        romaji_lower = romaji.lower()
        eng          = None
        is_sequel    = None

        # ── Strategy 1: /api/v3/anime search ─────────────────────────────
        try:
            r = await self.client.get(
                "https://animeschedule.net/api/v3/anime",
                params={"q": romaji},
                headers={
                    "Authorization": f"Bearer {AS_TOKEN}",
                    "Accept": "application/json",
                },
            )
            if r.status_code == 200:
                data  = r.json()
                items = data if isinstance(data, list) else (
                    data.get("anime") or data.get("results") or data.get("data") or []
                )
                for item in items[:8]:
                    if not isinstance(item, dict):
                        continue
                    item_rom = (
                        item.get("romaji") or item.get("romajiName")
                        or item.get("title") or ""
                    ).lower()

                    # Match check
                    if not (
                        romaji_lower in item_rom
                        or item_rom in romaji_lower
                        or self._similarity(romaji_lower, item_rom) > 0.7
                    ):
                        continue

                    # English title
                    item_eng = (
                        item.get("english") or item.get("englishName")
                        or item.get("english_title") or ""
                    ).strip()
                    if item_eng and item_eng.lower() not in (romaji_lower, item_rom):
                        eng = item_eng

                    # Sequel detection from animeschedule fields:
                    #   - "prequelOf" / "sequelOf" (relation fields)
                    #   - "seasons" count > 1
                    #   - "season" number > 1
                    prequel_of  = item.get("prequelOf")   # this show IS a sequel
                    sequel_of   = item.get("sequelOf")     # this show HAS a sequel
                    season_num  = item.get("season") or item.get("seasonNumber") or 1
                    seasons_cnt = item.get("seasons") or item.get("seasonsCount") or 1

                    try:
                        season_num  = int(season_num)
                        seasons_cnt = int(seasons_cnt)
                    except (TypeError, ValueError):
                        season_num  = 1
                        seasons_cnt = 1

                    if prequel_of is not None:
                        # has a prequel → this is a sequel
                        is_sequel = True
                    elif season_num > 1 or seasons_cnt > 1:
                        is_sequel = True
                    elif sequel_of is not None:
                        # has a sequel but is itself the original → not returning
                        is_sequel = False
                    else:
                        is_sequel = False

                    break  # found best match
        except Exception as exc:
            logger.debug("animeschedule API error for '%s': %s", romaji, exc)

        # ── Strategy 2: timetable cache scan ─────────────────────────────
        if eng is None and is_sequel is None:
            try:
                from helper.season import _current_week_year
                year, week = current_week_year()
                cached = await self.db.get_cache(f"scrape:v2:timetable:{year}:{week}")
                if cached:
                    for entry in cached:
                        entry_rom = (entry.get("romaji") or "").lower()
                        entry_eng = (entry.get("title")  or "").strip()
                        if not (
                            romaji_lower in entry_rom
                            or entry_rom in romaji_lower
                            or self._similarity(romaji_lower, entry_rom) > 0.7
                        ):
                            continue
                        if entry_eng and entry_eng.lower() != entry_rom:
                            eng = entry_eng
                        # timetable doesn't have sequel info → leave is_sequel as None
                        break
            except Exception as exc:
                logger.debug("animeschedule timetable scan error: %s", exc)

        return eng, is_sequel

    @staticmethod
    def _similarity(a: str, b: str) -> float:
        """Simple character overlap ratio for fuzzy matching."""
        if not a or not b:
            return 0.0
        shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
        matches = sum(1 for c in shorter if c in longer)
        return matches / max(len(longer), 1)

    # ── Pagination Helper ─────────────────────────────────────────────────

    @staticmethod
    def paginate(
        data: "list | dict", year: int, season: str,
        page: int = 0, per_page: int = 15,
    ) -> tuple[str, int]:
        """
        Return ``(text, total_pages)`` for the given 0-indexed *page*.

        *data* is either:
          - old list format (all titles)
          - new dict format {"new": [...], "continuing": [...]}

        Displays two sections:
          🆕 New This Season
          🔄 Continuing / New Season
        """
        # Handle both old list format and new dict format
        if isinstance(data, dict):
            new_titles  = data.get("new", [])
            cont_titles = data.get("continuing", [])
        else:
            new_titles  = data
            cont_titles = []

        # Build a flat list with section markers for pagination
        all_items: list = []
        if new_titles:
            all_items.append(("header", "🆕 <b>New This Season</b>"))
            for t in new_titles:
                all_items.append(("title", t))
        if cont_titles:
            all_items.append(("header", "🔄 <b>Returning Anime</b>"))
            for t in cont_titles:
                all_items.append(("title", t))

        # Count only title items for pagination
        title_items = [x for x in all_items if x[0] == "title"]
        total       = len(title_items)
        total_pages = max(1, (total + per_page - 1) // per_page)
        page        = max(0, min(page, total_pages - 1))

        start = page * per_page
        end   = start + per_page

        # Walk all_items and collect titles for this page
        title_count = 0
        page_global_num = start  # offset for global numbering
        lines: list = []
        current_section_printed = False
        pending_header = None

        for kind, value in all_items:
            if kind == "header":
                pending_header = value
                current_section_printed = False
                continue
            # kind == "title"
            if title_count < start:
                title_count += 1
                continue
            if title_count >= end:
                break
            # Print pending section header (only once per section per page)
            if pending_header and not current_section_printed:
                lines.append(pending_header)
                current_section_printed = True
            display = value.split(" | ")[0] if " | " in value else value
            lines.append(f"  {title_count + 1}. {display}")
            title_count += 1

        header_txt  = f"📋 <b>{season.capitalize()} {year} — Anime</b>"
        sub_txt     = f"<i>{len(new_titles)} new  ·  {len(cont_titles)} returning</i>"
        page_txt    = f"<i>Page {page + 1}/{total_pages}</i>" if total_pages > 1 else ""

        parts = [header_txt, sub_txt]
        if page_txt:
            parts.append(page_txt)
        parts.append("")
        parts.extend(lines)

        return "\n".join(parts), total_pages


def _current_week_year():
    from datetime import date
    d = date.today()
    iso = d.isocalendar()
    return iso[0], iso[1]
