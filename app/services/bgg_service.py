import logging
import os
import threading
import time
from typing import Any

import cachetools
import defusedxml.ElementTree as ET
import requests

logger = logging.getLogger(__name__)

_BGG_BASE = "https://boardgamegeek.com/xmlapi2"
_TIMEOUT = 5  # seconds
_RETRY_DELAY = 1  # seconds to wait before retrying after a 202 response


def _bgg_headers() -> dict:
    token = os.getenv("BGG_API_TOKEN")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


# Module-level cache and lock. TTLCache is not thread-safe on its own;
# the RLock is required because APScheduler runs in a background thread
# even with a single gunicorn worker.
#
# IMPORTANT: Do NOT switch to the @cachetools.cached decorator pattern.
# The decorator wraps the method and makes _cache inaccessible, which
# breaks the `_bgg_module._cache.clear()` call in the test clear_cache fixture.
_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=200, ttl=600)
_lock = threading.RLock()


class BGGService:
    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    @classmethod
    def search(cls, query: str) -> list[dict]:
        """Search BGG for games matching query. Returns [] for short queries."""
        if len(query.strip()) < 3:
            return []
        try:
            resp = requests.get(
                f"{_BGG_BASE}/search",
                params={"query": query, "type": "boardgame"},
                headers=_bgg_headers(),
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            return cls._parse_search(resp.content)
        except Exception as exc:
            logger.warning("BGG search failed for %r: %s", query, exc)
            return []

    @classmethod
    def fetch_details(cls, bgg_id: int) -> dict:
        """Fetch full BGG details for a game by BGG ID. Returns {} on failure.
        Results are cached in the module-level TTLCache (10 min, max 200 entries).
        """
        with _lock:
            if bgg_id in _cache:
                return _cache[bgg_id]
        result = cls._fetch_with_retry(bgg_id)
        if result:  # Do NOT cache {} — a BGG timeout would poison the cache for 10 min
            with _lock:
                _cache[bgg_id] = result
        return result

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @classmethod
    def _fetch_with_retry(cls, bgg_id: int) -> dict:
        try:
            resp = requests.get(
                f"{_BGG_BASE}/thing",
                params={"id": bgg_id, "stats": 1},
                headers=_bgg_headers(),
                timeout=_TIMEOUT,
            )
        except Exception as exc:
            logger.warning("BGG fetch_details failed for %d: %s", bgg_id, exc)
            return {}

        if resp.status_code == 202:
            time.sleep(_RETRY_DELAY)
            try:
                resp = requests.get(
                    f"{_BGG_BASE}/thing",
                    params={"id": bgg_id, "stats": 1},
                    headers=_bgg_headers(),
                    timeout=_TIMEOUT,
                )
            except Exception as exc:
                logger.warning("BGG fetch_details retry failed for %d: %s", bgg_id, exc)
                return {}
            if resp.status_code == 202:
                logger.warning("BGG returned 202 twice for bgg_id=%d, giving up", bgg_id)
                return {}

        if not resp.ok:
            return {}

        return cls._parse_details(resp.content)

    @staticmethod
    def _parse_search(content: bytes) -> list[dict]:
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return []
        results = []
        for item in root.findall("item"):
            name_el = item.find("name[@type='primary']")
            year_el = item.find("yearpublished")
            if name_el is None:
                continue
            results.append(
                {
                    "bgg_id": int(item.get("id", 0)),
                    "name": name_el.get("value", ""),
                    "year": year_el.get("value", "") if year_el is not None else "",
                    # BGG search results do not include thumbnails — only /thing does.
                    "thumbnail": "",
                }
            )
        return results

    @staticmethod
    def _parse_details(content: bytes) -> dict:
        try:
            root = ET.fromstring(content)
        except ET.ParseError:
            return {}
        item = root.find("item")
        if item is None:
            return {}

        def _val(path: str, attr: str = "value") -> Any:
            el = item.find(path)
            return el.get(attr) if el is not None else None

        def _int(path: str) -> int | None:
            v = _val(path)
            try:
                return int(v) if v is not None else None
            except (ValueError, TypeError):
                return None

        def _float(path: str) -> float | None:
            v = _val(path)
            try:
                return float(v) if v is not None else None
            except (ValueError, TypeError):
                return None

        name_el = item.find("name[@type='primary']")
        desc_el = item.find("description")

        return {
            "name": name_el.get("value", "") if name_el is not None else "",
            "description": desc_el.text if desc_el is not None else "",
            "min_players": _int("minplayers"),
            "max_players": _int("maxplayers"),
            "playtime": _int("playingtime"),
            "image_url": item.findtext("image"),
            "bgg_rating": _float("statistics/ratings/average"),
            "complexity": _float("statistics/ratings/averageweight"),
            "bgg_rank": _int("statistics/ratings/ranks/rank[@name='boardgame']"),
            "categories": [
                el.get("value", "") for el in item.findall("link[@type='boardgamecategory']")
            ],
            "mechanics": [
                el.get("value", "") for el in item.findall("link[@type='boardgamemechanic']")
            ],
        }
