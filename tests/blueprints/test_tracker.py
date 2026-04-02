import datetime
import uuid

import pytest

from app.extensions import db as _db
from app.models import (  # noqa: F401
    Game,
    GameNight,
    GameNightGame,
    Person,
    Player,
    TrackerField,
    TrackerSession,
)


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


def test_live_tracker_loads(app, db, auth_tracker_client):
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
        launch_session,
    )
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
    launch_session(session.id, mode="individual", teams_data=[],
                   player_ids=[auth_tracker_client["player_id"]])
    resp = c.get(f"/tracker/{session.id}")
    assert resp.status_code == 200
    assert b"VP" in resp.data


def test_add_field_htmx_returns_fragment(app, db, auth_tracker_client):
    from app.services.tracker_services import get_or_create_configuring_session
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    resp = c.post(f"/tracker/{session.id}/field", data={
        "type": "counter", "label": "Life", "starting_value": "20", "is_score_field": "true"
    })
    assert resp.status_code == 200
    assert b"Life" in resp.data
    assert TrackerField.query.filter_by(tracker_session_id=session.id, label="Life").first() is not None


def test_value_update_htmx_returns_cell(app, db, auth_tracker_client):
    from app.models import TrackerValue
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
        launch_session,
    )
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    field = add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
    launch_session(session.id, mode="individual", teams_data=[],
                   player_ids=[auth_tracker_client["player_id"]])
    resp = c.post(f"/tracker/{session.id}/value", data={
        "field_id": str(field.id),
        "entity_type": "player",
        "entity_id": str(auth_tracker_client["player_id"]),
        "delta": "1",
    })
    assert resp.status_code == 200
    val = TrackerValue.query.filter_by(tracker_field_id=field.id, player_id=auth_tracker_client["player_id"]).first()
    assert val.value == "1"


def test_end_game_get_returns_rankings(app, db, auth_tracker_client):
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
        launch_session,
        update_value,
    )
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    field = add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
    launch_session(session.id, mode="individual", teams_data=[],
                   player_ids=[auth_tracker_client["player_id"]])
    update_value(session.id, field.id, entity_type="player",
                 entity_id=auth_tracker_client["player_id"], delta=5)
    resp = c.get(f"/tracker/{session.id}/end")
    assert resp.status_code == 200
    assert b"VP" in resp.data
    session_obj = TrackerSession.query.get(session.id)
    assert session_obj.status == "active"  # GET does not mutate status


def test_save_results_marks_completed(app, db, auth_tracker_client):
    from app.models import Result
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
        launch_session,
        update_value,
    )
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    field = add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
    launch_session(session.id, mode="individual", teams_data=[],
                   player_ids=[auth_tracker_client["player_id"]])
    update_value(session.id, field.id, entity_type="player",
                 entity_id=auth_tracker_client["player_id"], delta=5)
    resp = c.post(f"/tracker/{session.id}/save", data={
        f"position_{auth_tracker_client['player_id']}": "1",
        f"score_{auth_tracker_client['player_id']}": "5",
    })
    assert resp.status_code == 302
    session_obj = TrackerSession.query.get(session.id)
    assert session_obj.status == "completed"
    result = Result.query.filter_by(game_night_game_id=gng_id, player_id=auth_tracker_client["player_id"]).first()
    assert result is not None
    assert result.position == 1


def test_discard_deletes_session(app, db, auth_tracker_client):
    from app.services.tracker_services import get_or_create_configuring_session
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    sid = session.id
    resp = c.post(f"/tracker/{sid}/discard")
    assert resp.status_code == 302
    assert TrackerSession.query.get(sid) is None


def test_track_button_visible_on_active_game_night(auth_tracker_client):
    c = auth_tracker_client["client"]
    gn_id = auth_tracker_client["gn_id"]
    resp = c.get(f"/game_night/{gn_id}")
    assert resp.status_code == 200
    assert b"Track" in resp.data


def test_track_button_not_visible_on_finalized_game_night(auth_tracker_client):
    from app.extensions import db as _db
    from app.models import GameNight
    c = auth_tracker_client["client"]
    gn_id = auth_tracker_client["gn_id"]
    gn = GameNight.query.get(gn_id)
    gn.final = True
    _db.session.commit()
    try:
        resp = c.get(f"/game_night/{gn_id}")
        assert resp.status_code == 200
        assert b"/tracker/new" not in resp.data
    finally:
        gn = GameNight.query.get(gn_id)
        gn.final = False
        _db.session.commit()
