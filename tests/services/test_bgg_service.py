# tests/services/test_bgg_service.py
import pytest
from unittest.mock import patch, MagicMock
from app.services.bgg_service import BGGService


SEARCH_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<items total="2">
  <item type="boardgame" id="13">
    <name type="primary" value="Catan" />
    <yearpublished value="1995" />
  </item>
  <item type="boardgame" id="822">
    <name type="primary" value="Carcassonne" />
    <yearpublished value="2000" />
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


from app.services import bgg_service as _bgg_module


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear module-level BGGService cache between tests."""
    _bgg_module._cache.clear()
    yield
    _bgg_module._cache.clear()


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
    with patch("app.services.bgg_service._RETRY_DELAY", 0):
        details = BGGService.fetch_details(13)
    assert details["name"] == "Catan"
    assert requests_mock.call_count == 2


def test_fetch_details_returns_empty_on_double_202(requests_mock):
    requests_mock.get(
        "https://boardgamegeek.com/xmlapi2/thing",
        status_code=202,
        content=b"",
    )
    with patch("app.services.bgg_service._RETRY_DELAY", 0):
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
    assert requests_mock.call_count == 1


def test_fetch_details_returns_empty_on_timeout(requests_mock):
    import requests
    requests_mock.get(
        "https://boardgamegeek.com/xmlapi2/thing",
        exc=requests.exceptions.Timeout,
    )
    details = BGGService.fetch_details(13)
    assert details == {}


def test_fetch_details_returns_empty_on_connection_error(requests_mock):
    import requests
    requests_mock.get(
        "https://boardgamegeek.com/xmlapi2/thing",
        exc=requests.exceptions.ConnectionError,
    )
    details = BGGService.fetch_details(13)
    assert details == {}


def test_fetch_details_returns_empty_on_500(requests_mock):
    requests_mock.get(
        "https://boardgamegeek.com/xmlapi2/thing",
        status_code=500,
        content=b"",
    )
    details = BGGService.fetch_details(13)
    assert details == {}


def test_search_returns_empty_on_connection_error(requests_mock):
    import requests
    requests_mock.get(
        "https://boardgamegeek.com/xmlapi2/search",
        exc=requests.exceptions.ConnectionError,
    )
    results = BGGService.search("Catan")
    assert results == []


def test_empty_result_not_cached(requests_mock):
    """A {} error result must not be stored in cache — BGG timeouts should not poison cache."""
    import requests
    requests_mock.get(
        "https://boardgamegeek.com/xmlapi2/thing",
        exc=requests.exceptions.Timeout,
    )
    BGGService.fetch_details(13)
    assert 13 not in _bgg_module._cache
