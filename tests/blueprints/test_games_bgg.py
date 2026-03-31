# tests/blueprints/test_games_bgg.py
from unittest.mock import patch

import pytest


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


@pytest.fixture()
def bgg_game(app):
    """A minimal Game row for BGG details tests."""
    from app.extensions import db as _db
    from app.models import Game

    with app.app_context():
        game = Game(name="Catan", bgg_id=13)
        _db.session.add(game)
        _db.session.commit()
        yield game
        _db.session.delete(game)
        _db.session.commit()


def test_bgg_details_fragment_returns_html(auth_client, bgg_game):
    with patch("app.blueprints.games.BGGService.fetch_details") as mock_fetch:
        mock_fetch.return_value = {
            "bgg_rating": 7.2,
            "complexity": 2.3,
            "bgg_rank": 100,
            "categories": ["Strategy"],
            "mechanics": ["Trading"],
        }
        resp = auth_client.get(f"/games/{bgg_game.id}/bgg-details")
    assert resp.status_code == 200
    assert b"7.2" in resp.data
