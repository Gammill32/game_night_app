def test_tracker_models_importable():
    from app.models import TrackerSession, TrackerField, TrackerTeam, TrackerValue
    assert TrackerSession.__tablename__ == "tracker_sessions"
    assert TrackerField.__tablename__ == "tracker_fields"
    assert TrackerTeam.__tablename__ == "tracker_teams"
    assert TrackerValue.__tablename__ == "tracker_values"


import pytest
from app.extensions import db as _db
from app.models import Game, GameNight, GameNightGame, Person, Player, TrackerSession, TrackerField, TrackerValue
import datetime
import uuid


@pytest.fixture()
def tracker_night(app, db):
    """A game night with one game and two players."""
    with app.app_context():
        game = Game(name=f"TG {uuid.uuid4().hex[:4]}", bgg_id=None)
        gn = GameNight(date=datetime.date(2024, 1, 1), final=False)
        _db.session.add_all([game, gn])
        _db.session.flush()

        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.flush()

        p1 = Person(first_name="A", last_name="A", email=f"a_{uuid.uuid4().hex[:4]}@t.invalid")
        p2 = Person(first_name="B", last_name="B", email=f"b_{uuid.uuid4().hex[:4]}@t.invalid")
        _db.session.add_all([p1, p2])
        _db.session.flush()

        pl1 = Player(game_night_id=gn.id, people_id=p1.id)
        pl2 = Player(game_night_id=gn.id, people_id=p2.id)
        _db.session.add_all([pl1, pl2])
        _db.session.commit()

        yield {"gng_id": gng.id, "gn_id": gn.id, "pl1_id": pl1.id, "pl2_id": pl2.id,
               "game": game, "gn": gn, "gng": gng, "p1": p1, "p2": p2}

        _db.session.rollback()
        TrackerSession.query.filter_by(game_night_game_id=gng.id).delete()
        _db.session.delete(pl1)
        _db.session.delete(pl2)
        _db.session.delete(p1)
        _db.session.delete(p2)
        _db.session.delete(gng)
        _db.session.delete(gn)
        _db.session.delete(game)
        _db.session.commit()


def test_get_or_create_configuring_session_creates_new(app, db, tracker_night):
    from app.services.tracker_services import get_or_create_configuring_session
    with app.app_context():
        session = get_or_create_configuring_session(tracker_night["gng_id"])
        assert session.status == "configuring"
        assert session.mode == "individual"
        assert session.game_night_game_id == tracker_night["gng_id"]


def test_get_or_create_configuring_session_returns_existing(app, db, tracker_night):
    from app.services.tracker_services import get_or_create_configuring_session
    with app.app_context():
        s1 = get_or_create_configuring_session(tracker_night["gng_id"])
        s2 = get_or_create_configuring_session(tracker_night["gng_id"])
        assert s1.id == s2.id


def test_discard_session_removes_session(app, db, tracker_night):
    from app.services.tracker_services import get_or_create_configuring_session, discard_session
    with app.app_context():
        session = get_or_create_configuring_session(tracker_night["gng_id"])
        sid = session.id
        discard_session(sid)
        assert TrackerSession.query.get(sid) is None
