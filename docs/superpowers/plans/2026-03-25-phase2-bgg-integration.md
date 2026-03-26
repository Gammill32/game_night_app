# Phase 2: BGG API Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace manual game entry with a live BoardGameGeek search-to-add flow, enrich game detail pages with BGG metadata (rating, complexity, categories), and consolidate the fragile BGG import chain into a single clean `BGGService`.

**Architecture:** `BGGService` in `app/services/bgg_service.py` owns all BGG HTTP and XML parsing. It uses a thread-safe `TTLCache` (10 min, max 200 entries). The `add_game` form becomes an HTMX-powered search widget. Game detail pages load BGG enrichment data via a secondary HTMX request after page render (keeps core page fast on cache miss). The fragile top-level `fetch_bgg_data.py` is deleted.

**Tech Stack:** Flask, HTMX, `cachetools.TTLCache`, `requests`, BGG XML API2, `pytest-mock`

**Spec:** `docs/superpowers/specs/2026-03-25-gamenight-redesign-design.md`

**Prerequisite:** Phase 1 complete, all smoke tests passing in CI.

---

## File Map

### New files
- `app/services/bgg_service.py` — BGGService class (search, fetch_details, cache)
- `app/templates/_bgg_results.html` — HTMX fragment: search results list
- `app/templates/_bgg_selected.html` — HTMX fragment: selected game confirmation
- `app/templates/_bgg_details.html` — HTMX fragment: BGG metadata panel for view_game
- `app/templates/_bgg_error.html` — HTMX fragment: error state (BGG unavailable)
- `tests/services/__init__.py`
- `tests/services/test_bgg_service.py` — unit tests for BGGService
- `tests/blueprints/__init__.py`
- `tests/blueprints/test_games_bgg.py` — integration tests for new endpoints

### Modified files
- `app/blueprints/games.py` — add `/games/bgg-search` and `/games/<id>/bgg-details` routes
- `app/templates/add_game.html` — replace static form with HTMX search widget
- `app/templates/view_game.html` — add BGG details panel loaded via HTMX
- `app/utils/utils.py` — remove `fetch_and_parse_bgg_data` (moved to BGGService)

### Deleted files
- `fetch_bgg_data.py` (root-level)
- `scripts/fetch_bgg_data.py`

---

## Task 1: BGGService — core implementation (TDD)

**Files:**
- Create: `app/services/bgg_service.py`
- Create: `tests/services/__init__.py`
- Create: `tests/services/test_bgg_service.py`

- [ ] **Step 1: Write failing tests for `BGGService.search()`**

```python
# tests/services/test_bgg_service.py
import pytest
from unittest.mock import patch, MagicMock
from app.services.bgg_service import BGGService


SEARCH_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<items total="2">
  <item type="boardgame" id="13">
    <name type="primary" value="Catan" />
    <yearpublished value="1995" />
    <thumbnail>https://example.com/catan.jpg</thumbnail>
  </item>
  <item type="boardgame" id="822">
    <name type="primary" value="Carcassonne" />
    <yearpublished value="2000" />
    <thumbnail>https://example.com/carc.jpg</thumbnail>
  </item>
</items>"""

DETAILS_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<items>
  <item type="boardgame" id="13">
    <name type="primary" sortindex="1" value="Catan" />
    <description>Build settlements.</description>
    <minplayers value="3" />
    <maxplayers value="4" />
    <playingtime value="120" />
    <image>https://example.com/catan-full.jpg</image>
    <statistics>
      <ratings>
        <average value="7.2" />
        <averageweight value="2.3" />
        <ranks>
          <rank type="subtype" name="boardgame" value="100" />
        </ranks>
      </ratings>
    </statistics>
    <link type="boardgamecategory" value="Negotiation" />
    <link type="boardgamemechanic" value="Dice Rolling" />
  </item>
</items>"""


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear BGGService cache between tests."""
    BGGService._cache.clear()
    yield
    BGGService._cache.clear()


def test_search_returns_empty_for_short_query():
    results = BGGService.search("ab")
    assert results == []


def test_search_returns_empty_for_empty_query():
    results = BGGService.search("")
    assert results == []


def test_search_parses_results(requests_mock):
    requests_mock.get(
        "https://boardgamegeek.com/xmlapi2/search",
        content=SEARCH_XML,
        status_code=200,
    )
    results = BGGService.search("Catan")
    assert len(results) == 2
    assert results[0]["bgg_id"] == 13
    assert results[0]["name"] == "Catan"
    assert results[0]["year"] == "1995"


def test_search_returns_empty_on_timeout(requests_mock):
    import requests
    requests_mock.get(
        "https://boardgamegeek.com/xmlapi2/search",
        exc=requests.exceptions.Timeout,
    )
    results = BGGService.search("Catan")
    assert results == []


def test_fetch_details_parses_game(requests_mock):
    requests_mock.get(
        "https://boardgamegeek.com/xmlapi2/thing",
        content=DETAILS_XML,
        status_code=200,
    )
    details = BGGService.fetch_details(13)
    assert details["name"] == "Catan"
    assert details["min_players"] == 3
    assert details["max_players"] == 4
    assert details["playtime"] == 120
    assert details["bgg_rating"] == pytest.approx(7.2, 0.01)
    assert details["complexity"] == pytest.approx(2.3, 0.01)
    assert details["bgg_rank"] == 100
    assert "Negotiation" in details["categories"]
    assert "Dice Rolling" in details["mechanics"]


def test_fetch_details_retries_on_202(requests_mock):
    requests_mock.get(
        "https://boardgamegeek.com/xmlapi2/thing",
        [
            {"status_code": 202, "content": b""},
            {"status_code": 200, "content": DETAILS_XML},
        ],
    )
    details = BGGService.fetch_details(13)
    assert details["name"] == "Catan"
    assert requests_mock.call_count == 2


def test_fetch_details_returns_empty_on_double_202(requests_mock):
    requests_mock.get(
        "https://boardgamegeek.com/xmlapi2/thing",
        status_code=202,
        content=b"",
    )
    details = BGGService.fetch_details(13)
    assert details == {}


def test_fetch_details_cached_on_second_call(requests_mock):
    requests_mock.get(
        "https://boardgamegeek.com/xmlapi2/thing",
        content=DETAILS_XML,
        status_code=200,
    )
    BGGService.fetch_details(13)
    BGGService.fetch_details(13)
    assert requests_mock.call_count == 1  # Second call served from cache


def test_fetch_details_returns_empty_on_timeout(requests_mock):
    import requests
    requests_mock.get(
        "https://boardgamegeek.com/xmlapi2/thing",
        exc=requests.exceptions.Timeout,
    )
    details = BGGService.fetch_details(13)
    assert details == {}
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pip install requests-mock  # Add to requirements-dev.txt too
pytest tests/services/test_bgg_service.py -v
```
Expected: `ImportError: cannot import name 'BGGService'`

Add `requests-mock` to `requirements-dev.txt`.

- [ ] **Step 3: Implement `BGGService`**

```python
# app/services/bgg_service.py
import time
import threading
import logging
import xml.etree.ElementTree as ET
from typing import Any

import requests
import cachetools

logger = logging.getLogger(__name__)

_BGG_BASE = "https://boardgamegeek.com/xmlapi2"
_TIMEOUT = 5  # seconds


class BGGService:
    _cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=200, ttl=600)
    _lock = threading.RLock()

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
                timeout=_TIMEOUT,
            )
            resp.raise_for_status()
            return cls._parse_search(resp.content)
        except Exception as exc:
            logger.warning("BGG search failed for %r: %s", query, exc)
            return []

    @classmethod
    @cachetools.cached(cache=lambda self: self._cache, key=lambda self, bgg_id: bgg_id, lock=lambda self: self._lock)
    def fetch_details(cls, bgg_id: int) -> dict:
        """Fetch full BGG details for a game by BGG ID. Returns {} on failure."""
        return cls._fetch_with_retry(bgg_id)

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @classmethod
    def _fetch_with_retry(cls, bgg_id: int) -> dict:
        try:
            resp = requests.get(
                f"{_BGG_BASE}/thing",
                params={"id": bgg_id, "stats": 1},
                timeout=_TIMEOUT,
            )
        except Exception as exc:
            logger.warning("BGG fetch_details failed for %d: %s", bgg_id, exc)
            return {}

        if resp.status_code == 202:
            time.sleep(1)
            try:
                resp = requests.get(
                    f"{_BGG_BASE}/thing",
                    params={"id": bgg_id, "stats": 1},
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
            thumb_el = item.find("thumbnail")
            if name_el is None:
                continue
            results.append({
                "bgg_id": int(item.get("id", 0)),
                "name": name_el.get("value", ""),
                "year": year_el.get("value", "") if year_el is not None else "",
                "thumbnail": thumb_el.text if thumb_el is not None else "",
            })
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
                el.get("value", "")
                for el in item.findall("link[@type='boardgamecategory']")
            ],
            "mechanics": [
                el.get("value", "")
                for el in item.findall("link[@type='boardgamemechanic']")
            ],
        }
```

Note: the `@cachetools.cached` decorator on a classmethod needs the cache and lock accessed via `cls`. Adjust the decorator to use module-level cache and lock:

```python
_cache: cachetools.TTLCache = cachetools.TTLCache(maxsize=200, ttl=600)
_lock = threading.RLock()

# Use module-level decorator for classmethod:
@classmethod
def fetch_details(cls, bgg_id: int) -> dict:
    with _lock:
        if bgg_id in _cache:
            return _cache[bgg_id]
        result = cls._fetch_with_retry(bgg_id)
        _cache[bgg_id] = result
        return result
```

Update `BGGService` to use module-level `_cache` and `_lock` for the test fixture to work correctly.

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/services/test_bgg_service.py -v
```
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/bgg_service.py tests/services/ requirements-dev.txt
git commit -m "feat: implement BGGService with TTLCache, 202 retry, and timeout handling"
```

---

## Task 2: Clean up the old BGG import chain

**Files:**
- Delete: `fetch_bgg_data.py`
- Delete: `scripts/fetch_bgg_data.py`
- Modify: `app/utils/utils.py`
- Modify: `app/services/games_services.py`

- [ ] **Step 1: Read `app/utils/utils.py` and `app/services/games_services.py`** to understand all references to `fetch_and_parse_bgg_data` and `fetch_bgg_data`.

- [ ] **Step 2: Update `app/utils/utils.py`**

Remove the `fetch_and_parse_bgg_data` function (and its import of `fetch_bgg_data`). If there are other utilities in the file unrelated to BGG, keep them.

- [ ] **Step 3: Update `app/services/games_services.py`**

Replace `from app.utils import fetch_and_parse_bgg_data` with `from app.services.bgg_service import BGGService`.

Replace all calls to `fetch_and_parse_bgg_data(bgg_id)` with `BGGService.fetch_details(bgg_id)`.

The `get_or_create_game` function calls this — the signature and return dict keys should be compatible since `BGGService.fetch_details` returns the same keys (`name`, `description`, `min_players`, `max_players`, `playtime`, `image_url`).

- [ ] **Step 4: Delete the old files**

```bash
git rm fetch_bgg_data.py scripts/fetch_bgg_data.py
```

- [ ] **Step 5: Run full test suite**

```bash
pytest -v
```
Expected: All pass. Fix any import errors.

- [ ] **Step 6: Commit**

```bash
git add app/utils/utils.py app/services/games_services.py
git commit -m "refactor: consolidate BGG logic into BGGService, remove fetch_bgg_data.py"
```

---

## Task 3: BGG search endpoint + HTMX fragments

**Files:**
- Modify: `app/blueprints/games.py`
- Create: `app/templates/_bgg_results.html`
- Create: `app/templates/_bgg_selected.html`
- Create: `app/templates/_bgg_error.html`
- Create: `tests/blueprints/__init__.py`
- Create: `tests/blueprints/test_games_bgg.py`

- [ ] **Step 1: Write failing tests for the search endpoint**

```python
# tests/blueprints/test_games_bgg.py
import pytest
from unittest.mock import patch


def test_bgg_search_returns_fragment(auth_client):
    with patch("app.blueprints.games.BGGService.search") as mock_search:
        mock_search.return_value = [
            {"bgg_id": 13, "name": "Catan", "year": "1995", "thumbnail": ""},
        ]
        resp = auth_client.get("/games/bgg-search?q=Catan")
    assert resp.status_code == 200
    assert b"Catan" in resp.data


def test_bgg_search_short_query_returns_empty_fragment(auth_client):
    resp = auth_client.get("/games/bgg-search?q=ab")
    assert resp.status_code == 200
    assert resp.data.strip() == b""  # Empty fragment — no API call


def test_bgg_search_requires_login(client):
    resp = client.get("/games/bgg-search?q=Catan")
    assert resp.status_code in (302, 401)


def test_bgg_details_fragment_returns_html(auth_client):
    with patch("app.blueprints.games.BGGService.fetch_details") as mock_fetch:
        mock_fetch.return_value = {
            "bgg_rating": 7.2,
            "complexity": 2.3,
            "bgg_rank": 100,
            "categories": ["Strategy"],
            "mechanics": ["Trading"],
        }
        # Need a game in DB — create one first
        from app.models import Game
        from app.extensions import db
        game = Game(name="Catan", bgg_id=13)
        db.session.add(game)
        db.session.commit()
        resp = auth_client.get(f"/games/{game.id}/bgg-details")
        db.session.delete(game)
        db.session.commit()
    assert resp.status_code == 200
    assert b"7.2" in resp.data
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
pytest tests/blueprints/test_games_bgg.py -v
```
Expected: 404 errors (routes don't exist yet).

- [ ] **Step 3: Add routes to `app/blueprints/games.py`**

Add two new routes at the bottom of the file:

```python
from app.services.bgg_service import BGGService

@games_bp.route("/bgg-search")
@login_required
def bgg_search():
    """HTMX endpoint: search BGG and return results fragment."""
    query = request.args.get("q", "").strip()
    if len(query) < 3:
        return ""  # Empty response — HTMX will clear the results div
    results = BGGService.search(query)
    return render_template("_bgg_results.html", results=results, query=query)


@games_bp.route("/<int:game_id>/bgg-details")
@login_required
def bgg_details(game_id: int):
    """HTMX endpoint: fetch BGG enrichment data for a game and return fragment."""
    game = Game.query.get_or_404(game_id)
    if not game.bgg_id:
        return render_template("_bgg_error.html", message="No BGG data available for this game.")
    details = BGGService.fetch_details(game.bgg_id)
    if not details:
        return render_template("_bgg_error.html", message="Could not reach BoardGameGeek.")
    return render_template("_bgg_details.html", details=details)
```

- [ ] **Step 4: Create `_bgg_results.html`**

```html
{% if results %}
<ul class="divide-y divide-stone-100 rounded-xl border border-stone-200 bg-white overflow-hidden">
  {% for game in results %}
  <li>
    <button type="button"
            class="w-full flex items-center gap-3 px-4 py-3 text-left hover:bg-stone-50 transition-colors"
            hx-get="{{ url_for('games.bgg_search') }}?select={{ game.bgg_id }}&name={{ game.name | urlencode }}&year={{ game.year | urlencode }}&thumbnail={{ game.thumbnail | urlencode }}"
            hx-target="#bgg-search-widget"
            hx-swap="outerHTML">
      {% if game.thumbnail %}
      <img src="{{ game.thumbnail }}" alt="" class="h-10 w-10 object-contain rounded flex-shrink-0" />
      {% else %}
      <div class="h-10 w-10 bg-stone-100 rounded flex-shrink-0"></div>
      {% endif %}
      <div>
        <div class="text-sm font-medium text-stone-800">{{ game.name }}</div>
        {% if game.year %}<div class="text-xs text-stone-500">{{ game.year }}</div>{% endif %}
      </div>
    </button>
  </li>
  {% endfor %}
</ul>
{% else %}
<p class="text-sm text-stone-500 px-1">No results found for "{{ query }}".</p>
{% endif %}
```

Note: clicking a result sends a GET with `?select=<bgg_id>&name=...` params — handle this in the route to return `_bgg_selected.html`.

- [ ] **Step 5: Update the `bgg_search` route to handle selection**

```python
@games_bp.route("/bgg-search")
@login_required
def bgg_search():
    query = request.args.get("q", "").strip()
    # Selection: user clicked a result
    if request.args.get("select"):
        return render_template("_bgg_selected.html",
            bgg_id=request.args.get("select"),
            name=request.args.get("name"),
            year=request.args.get("year"),
            thumbnail=request.args.get("thumbnail"),
        )
    if len(query) < 3:
        return ""
    results = BGGService.search(query)
    return render_template("_bgg_results.html", results=results, query=query)
```

- [ ] **Step 6: Create `_bgg_selected.html`**

```html
<div id="bgg-search-widget" class="flex items-center gap-3 p-3 rounded-xl border border-green-200 bg-green-50">
  {% if thumbnail %}
  <img src="{{ thumbnail }}" alt="" class="h-12 w-12 object-contain rounded flex-shrink-0" />
  {% endif %}
  <div class="flex-1">
    <div class="text-sm font-semibold text-stone-800">{{ name }}</div>
    {% if year %}<div class="text-xs text-stone-500">{{ year }}</div>{% endif %}
  </div>
  <button type="button"
          class="text-xs text-stone-500 hover:text-red-600 underline"
          hx-get="{{ url_for('games.bgg_search') }}?q="
          hx-target="#bgg-search-widget"
          hx-swap="outerHTML">
    Change
  </button>
  <input type="hidden" name="bgg_id" value="{{ bgg_id }}" />
</div>
```

- [ ] **Step 7: Create `_bgg_error.html`**

```html
<p class="text-sm text-red-600">{{ message }}</p>
```

- [ ] **Step 8: Create `_bgg_details.html`**

```html
<div class="space-y-3">
  {% if details.bgg_rating %}
  <div class="flex items-center gap-4">
    <div class="text-center">
      <div class="text-2xl font-bold text-stone-800">{{ "%.1f"|format(details.bgg_rating) }}</div>
      <div class="text-xs text-stone-500">BGG Rating</div>
    </div>
    {% if details.bgg_rank %}
    <div class="text-center">
      <div class="text-2xl font-bold text-stone-800">#{{ details.bgg_rank }}</div>
      <div class="text-xs text-stone-500">BGG Rank</div>
    </div>
    {% endif %}
    {% if details.complexity %}
    <div class="text-center">
      <div class="text-2xl font-bold text-stone-800">{{ "%.1f"|format(details.complexity) }}/5</div>
      <div class="text-xs text-stone-500">Complexity</div>
    </div>
    {% endif %}
  </div>
  {% endif %}

  {% if details.categories %}
  <div>
    <div class="text-xs font-semibold text-stone-500 uppercase tracking-wide mb-1">Categories</div>
    <div class="flex flex-wrap gap-1">
      {% for cat in details.categories %}
      <span class="px-2 py-0.5 bg-stone-100 text-stone-700 text-xs rounded-full">{{ cat }}</span>
      {% endfor %}
    </div>
  </div>
  {% endif %}

  {% if details.mechanics %}
  <div>
    <div class="text-xs font-semibold text-stone-500 uppercase tracking-wide mb-1">Mechanics</div>
    <div class="flex flex-wrap gap-1">
      {% for mech in details.mechanics %}
      <span class="px-2 py-0.5 bg-red-50 text-red-700 text-xs rounded-full">{{ mech }}</span>
      {% endfor %}
    </div>
  </div>
  {% endif %}
</div>
```

- [ ] **Step 9: Run tests**

```bash
pytest tests/blueprints/test_games_bgg.py -v
```
Expected: All pass.

- [ ] **Step 10: Commit**

```bash
git add app/blueprints/games.py app/templates/_bgg_results.html app/templates/_bgg_selected.html app/templates/_bgg_error.html app/templates/_bgg_details.html tests/blueprints/
git commit -m "feat: add BGG search endpoint and HTMX fragments"
```

---

## Task 4: Update `add_game.html` — HTMX search widget

**Files:**
- Modify: `app/templates/add_game.html`

- [ ] **Step 1: Rewrite `add_game.html`**

Replace the existing manual name + BGG ID form with the HTMX search widget:

```html
{% extends "base.html" %}
{% block title %}Add Game — Game Night{% endblock %}
{% block content %}
<div class="max-w-lg">
  <h1 class="text-2xl font-bold text-stone-800 mb-6">Add a Game</h1>

  <form method="POST" action="{{ url_for('games.add_game') }}">
    <div class="bg-white rounded-xl border border-stone-200 shadow-sm p-6 space-y-5">

      <div>
        <label class="block text-sm font-medium text-stone-700 mb-2">Search BoardGameGeek</label>
        <!-- Search input fires HTMX on keyup -->
        <input type="text"
               id="bgg-query"
               placeholder="Start typing a game name…"
               autocomplete="off"
               class="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent"
               hx-get="{{ url_for('games.bgg_search') }}"
               hx-trigger="keyup changed delay:400ms"
               hx-target="#bgg-results"
               hx-vals='js:{q: document.getElementById("bgg-query").value}'
               />

        <!-- Results drop into this div; clicking a result replaces bgg-search-widget -->
        <div id="bgg-results" class="mt-2"></div>
      </div>

      <!-- Search widget: starts empty, replaced by _bgg_selected.html on selection -->
      <div id="bgg-search-widget"></div>

      <div class="pt-2">
        <button type="submit"
                class="w-full rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 transition-colors">
          Add Game to My Library
        </button>
      </div>
    </div>
  </form>
</div>
{% endblock %}
```

- [ ] **Step 2: Verify the `add_game` route in `games.py` reads `bgg_id` from the form**

The existing `add_game` POST handler should already call `add_game(user_id, game_name, bgg_id)`. Verify it reads `bgg_id` from `request.form.get("bgg_id")`. The `game_name` field is no longer needed since `BGGService.fetch_details` provides the name — ensure `get_or_create_game` handles a `None` game_name when `bgg_id` is provided (it already does per `games_services.py`).

- [ ] **Step 3: Run smoke tests**

```bash
pytest tests/test_smoke.py -v
```
Expected: All pass (the add_game GET route returns 200).

- [ ] **Step 4: Commit**

```bash
git add app/templates/add_game.html
git commit -m "feat: replace manual add_game form with HTMX BGG search widget"
```

---

## Task 5: Update `view_game.html` — async BGG details panel

**Files:**
- Modify: `app/templates/view_game.html`

- [ ] **Step 1: Add BGG details panel to `view_game.html`**

Find the game detail section and add a BGG panel that loads via HTMX after page render:

```html
{% if game.bgg_id %}
<!-- BGG details panel — loaded asynchronously to avoid blocking page render -->
<div class="bg-white rounded-xl border border-stone-200 shadow-sm p-5 mt-4"
     hx-get="{{ url_for('games.bgg_details', game_id=game.id) }}"
     hx-trigger="load"
     hx-swap="innerHTML">
  <div class="text-sm text-stone-400 animate-pulse">Loading BGG data…</div>
</div>
{% endif %}
```

The `hx-trigger="load"` fires the request as soon as the element is added to the DOM. The endpoint returns `_bgg_details.html` or `_bgg_error.html`.

- [ ] **Step 2: Run smoke tests**

```bash
pytest tests/test_smoke.py -v
```
Expected: All pass.

- [ ] **Step 3: Run full test suite**

```bash
pytest -v --cov=app --cov-fail-under=60
```
Expected: All pass, coverage at or above 60%.

- [ ] **Step 4: Final Phase 2 commit**

```bash
git add app/templates/view_game.html
git commit -m "feat: complete phase 2 — BGG integration with search-to-add and async detail pages"
```

---

## Phase 2 Done ✓

BGG integration is fully deployed. Manual game entry is replaced with live search. Game detail pages show BGG rating, complexity, categories, and mechanics. The fragile import chain is gone.

**Before starting Phase 3:** verify all tests pass in CI.
