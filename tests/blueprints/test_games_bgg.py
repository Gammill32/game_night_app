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


def test_bgg_search_short_query_skips_bgg(auth_client, monkeypatch):
    from app.services.bgg_service import BGGService

    assert auth_client.get("/games/bgg-search?q=a").data.strip() == b""
    monkeypatch.setattr(BGGService, "search", classmethod(lambda cls, q: 1 / 0))
    resp = auth_client.get("/games/bgg-search?q=ab")  # library only, no BGG call
    assert resp.status_code == 200 and b"Keep typing" in resp.data


def test_bgg_search_requires_login(client):
    resp = client.get("/games/bgg-search?q=Catan")
    assert resp.status_code in (302, 401)


@pytest.fixture()
def bgg_game(app, db):
    """A minimal Game row for BGG details tests."""
    from app.extensions import db as _db
    from app.models import Game

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


def test_find_game_marks_library_and_adds_by_pick(client, make_person, monkeypatch):
    from app.extensions import db as _db
    from app.models import Game, OwnedBy, Wishlist
    from app.services.bgg_service import BGGService
    from tests.conftest import login

    ann, bo = make_person("Ann"), make_person("Bo")
    known = Game(name="Findable Cascadia", bgg_id=900001)
    _db.session.add(known)
    _db.session.flush()
    _db.session.add(OwnedBy(game_id=known.id, person_id=bo.id))
    _db.session.commit()
    monkeypatch.setattr(
        BGGService,
        "search",
        classmethod(
            lambda cls, q: [
                {"bgg_id": 900001, "name": "Findable Cascadia", "year": "2021", "thumbnail": ""},
                {"bgg_id": 900002, "name": "Findable Junior", "year": "2025", "thumbnail": ""},
            ]
        ),
    )
    login(client, ann)
    html = client.get("/games/bgg-search?q=Findable&mode=own").get_data(as_text=True)
    assert "Already in the group" in html and "Bo owns it" in html
    assert "From BoardGameGeek" in html and "Findable Junior" in html
    assert html.count("Findable Cascadia") == 1  # not listed twice

    resp = client.post("/game/add", data={"game_id": str(known.id)})
    assert resp.headers["Location"].endswith(f"/game/{known.id}")
    assert OwnedBy.query.filter_by(game_id=known.id, person_id=ann.id).count() == 1
    html = client.get("/games/bgg-search?q=Findable&mode=wish").get_data(as_text=True)
    assert "You own it" in html and "disabled" in html

    resp = client.post("/wishlist/add", data={"name": "Homemade Findable"})
    made = Game.query.filter_by(name="Homemade Findable").one()
    assert Wishlist.query.filter_by(game_id=made.id, person_id=ann.id).count() == 1
    resp = client.post("/wishlist/add", data={"game_id": str(known.id)})
    assert Wishlist.query.filter_by(game_id=known.id, person_id=ann.id).count() == 0  # owns it

    Wishlist.query.filter_by(person_id=ann.id).delete()
    OwnedBy.query.filter(OwnedBy.game_id.in_([known.id, made.id])).delete()
    _db.session.delete(known)
    _db.session.delete(made)
    _db.session.commit()
