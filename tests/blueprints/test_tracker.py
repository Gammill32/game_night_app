import datetime
import uuid

import pytest

from app.extensions import db as _db
from app.models import Game, GameNight, GameNightGame, Person, Player, TrackerSession, TrackerField  # noqa: F401


@pytest.fixture()
def auth_tracker_client(app, db):
    """Admin client with a game night + game set up."""
    from app.extensions import bcrypt
    from app.models import Poll
    _db.session.rollback()
    existing = Person.query.filter_by(email="tracker_admin@example.com").first()
    if existing:
        for poll in Poll.query.filter_by(created_by=existing.id).all():
            _db.session.delete(poll)
        _db.session.flush()
        _db.session.delete(existing)
        _db.session.commit()

    admin = Person(
        first_name="Tracker", last_name="Admin", email="tracker_admin@example.com",
        password=bcrypt.generate_password_hash("password", rounds=4).decode("utf-8"),
        admin=True, owner=False,
    )
    _db.session.add(admin)
    _db.session.flush()

    game = Game(name=f"TG {uuid.uuid4().hex[:4]}", bgg_id=None)
    gn = GameNight(date=datetime.date(2024, 6, 1), final=False)
    _db.session.add_all([game, gn])
    _db.session.flush()

    gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
    _db.session.add(gng)
    _db.session.flush()

    player = Player(game_night_id=gn.id, people_id=admin.id)
    _db.session.add(player)
    _db.session.commit()

    with app.test_client() as client:
        client.post("/login", data={"email": "tracker_admin@example.com", "password": "password"})
        yield {"client": client, "gng_id": gng.id, "gn_id": gn.id,
               "player_id": player.id, "admin_id": admin.id, "game": game, "gn": gn, "gng": gng}

    _db.session.rollback()
    TrackerSession.query.filter_by(game_night_game_id=gng.id).delete()
    _db.session.delete(player)
    _db.session.delete(gng)
    _db.session.delete(gn)
    _db.session.delete(game)
    existing = Person.query.filter_by(email="tracker_admin@example.com").first()
    if existing:
        _db.session.delete(existing)
    _db.session.commit()


def test_setup_get_creates_configuring_session(auth_tracker_client):
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    resp = c.get(f"/game_night/{gng_id}/tracker/new")
    assert resp.status_code == 200
    session = TrackerSession.query.filter_by(game_night_game_id=gng_id).first()
    assert session is not None
    assert session.status == "configuring"


def test_setup_get_unauthenticated_redirects(client, db, seed_data):
    resp = client.get(f"/game_night/{seed_data['game_night_id']}/tracker/new")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
