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
        first_name="Tracker",
        last_name="Admin",
        email="tracker_admin@example.com",
        password=bcrypt.generate_password_hash("password", rounds=4).decode("utf-8"),
        admin=True,
        owner=False,
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
        yield {
            "client": client,
            "gng_id": gng.id,
            "gn_id": gn.id,
            "player_id": player.id,
            "admin_id": admin.id,
            "game": game,
            "gn": gn,
            "gng": gng,
        }

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


@pytest.fixture()
def non_participant_client(app, db, auth_tracker_client):
    """Logged-in client for a user who is NOT a participant in auth_tracker_client's game night."""
    from app.extensions import bcrypt

    _db.session.rollback()
    Person.query.filter_by(email="outsider@example.com").delete()
    _db.session.commit()

    outsider = Person(
        first_name="Out",
        last_name="Sider",
        email="outsider@example.com",
        password=bcrypt.generate_password_hash("password", rounds=4).decode("utf-8"),
        admin=False,
        owner=False,
    )
    _db.session.add(outsider)
    _db.session.commit()

    with app.test_client() as client:
        client.post("/login", data={"email": "outsider@example.com", "password": "password"})
        yield client

    _db.session.rollback()
    Person.query.filter_by(email="outsider@example.com").delete()
    _db.session.commit()


# ── setup / auth ──────────────────────────────────────────────────────────────


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


def test_setup_get_non_participant_forbidden(auth_tracker_client, non_participant_client):
    """Non-participant cannot access setup page (S-2)."""
    gng_id = auth_tracker_client["gng_id"]
    resp = non_participant_client.get(f"/game_night/{gng_id}/tracker/new")
    assert resp.status_code == 403


def test_setup_get_completed_session_redirects(app, db, auth_tracker_client):
    """setup_tracker redirects to game night view when session is completed (M-1)."""
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
        launch_session,
        save_results,
        update_value,
    )

    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    field = add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
    launch_session(
        session.id, mode="individual", teams_data=[], player_ids=[auth_tracker_client["player_id"]]
    )
    update_value(
        session.id,
        field.id,
        entity_type="player",
        entity_id=auth_tracker_client["player_id"],
        delta=3,
    )
    save_results(
        session.id,
        [
            {
                "player_id": auth_tracker_client["player_id"],
                "team_id": None,
                "position": 1,
                "score": 3,
            }
        ],
    )
    resp = c.get(f"/game_night/{gng_id}/tracker/new")
    assert resp.status_code == 302
    assert f"/game_night/{auth_tracker_client['gn_id']}" in resp.headers["Location"]


# ── launch ────────────────────────────────────────────────────────────────────


def test_launch_tracker_idor_protection(app, db, auth_tracker_client):
    """launch_tracker rejects session_id belonging to a different gng (S-3)."""
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
    )

    # Create a second game / gng so we have a different gng_id
    game2 = Game(name=f"TG2 {uuid.uuid4().hex[:4]}", bgg_id=None)
    gn2 = GameNight(date=datetime.date(2024, 7, 1), final=False)
    _db.session.add_all([game2, gn2])
    _db.session.flush()
    gng2 = GameNightGame(game_night_id=gn2.id, game_id=game2.id, round=1)
    _db.session.add(gng2)
    _db.session.commit()

    try:
        # Create a session on gng2
        session2 = get_or_create_configuring_session(gng2.id)
        add_field(session2.id, type="counter", label="VP", starting_value=0, is_score_field=True)

        # Try to launch session2 via gng1's URL — should get 400
        c = auth_tracker_client["client"]
        gng1_id = auth_tracker_client["gng_id"]
        resp = c.post(
            f"/game_night/{gng1_id}/tracker",
            data={
                "session_id": str(session2.id),
                "mode": "individual",
                "player_ids": [str(auth_tracker_client["player_id"])],
            },
        )
        assert resp.status_code == 400
    finally:
        TrackerSession.query.filter_by(game_night_game_id=gng2.id).delete()
        _db.session.delete(gng2)
        _db.session.delete(gn2)
        _db.session.delete(game2)
        _db.session.commit()


def test_launch_without_score_field_flashes_error(app, db, auth_tracker_client):
    """launch_tracker redirects back with an error when no score field exists (C-3 / I-1)."""
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
    )

    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    # Add a field that is NOT a score field
    add_field(session.id, type="counter", label="HP", starting_value=10, is_score_field=False)
    resp = c.post(
        f"/game_night/{gng_id}/tracker",
        data={
            "session_id": str(session.id),
            "mode": "individual",
            "player_ids": [str(auth_tracker_client["player_id"])],
        },
    )
    # Should redirect back to setup, not to live tracker
    assert resp.status_code == 302
    assert "/tracker/new" in resp.headers["Location"]
    # Session must remain configuring
    _db.session.expire(session)
    assert session.status == "configuring"


# ── live tracker ──────────────────────────────────────────────────────────────


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
    launch_session(
        session.id, mode="individual", teams_data=[], player_ids=[auth_tracker_client["player_id"]]
    )
    resp = c.get(f"/tracker/{session.id}")
    assert resp.status_code == 200
    assert b"VP" in resp.data


# ── add field ─────────────────────────────────────────────────────────────────


def test_add_field_htmx_returns_fragment(app, db, auth_tracker_client):
    from app.services.tracker_services import get_or_create_configuring_session

    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    resp = c.post(
        f"/tracker/{session.id}/field",
        data={"type": "counter", "label": "Life", "starting_value": "20", "is_score_field": "true"},
    )
    assert resp.status_code == 200
    assert b"Life" in resp.data
    assert (
        TrackerField.query.filter_by(tracker_session_id=session.id, label="Life").first()
        is not None
    )


def test_add_field_on_active_session_returns_400(app, db, auth_tracker_client):
    """Adding a field to an active session is rejected (C-2)."""
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
        launch_session,
    )

    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
    launch_session(
        session.id, mode="individual", teams_data=[], player_ids=[auth_tracker_client["player_id"]]
    )
    resp = c.post(
        f"/tracker/{session.id}/field",
        data={"type": "counter", "label": "HP", "starting_value": "10", "is_score_field": "false"},
    )
    assert resp.status_code == 400


def test_add_field_unknown_type_returns_400(app, db, auth_tracker_client):
    """Unknown field type is rejected (S-6)."""
    from app.services.tracker_services import get_or_create_configuring_session

    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    resp = c.post(
        f"/tracker/{session.id}/field",
        data={
            "type": "sql_injection",
            "label": "Bad",
            "starting_value": "0",
            "is_score_field": "false",
        },
    )
    assert resp.status_code == 400


def test_add_field_empty_label_returns_400(app, db, auth_tracker_client):
    """Empty label is rejected (M-5)."""
    from app.services.tracker_services import get_or_create_configuring_session

    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    resp = c.post(
        f"/tracker/{session.id}/field",
        data={"type": "counter", "label": "", "starting_value": "0", "is_score_field": "false"},
    )
    assert resp.status_code == 400


# ── value update ──────────────────────────────────────────────────────────────


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
    launch_session(
        session.id, mode="individual", teams_data=[], player_ids=[auth_tracker_client["player_id"]]
    )
    resp = c.post(
        f"/tracker/{session.id}/value",
        data={
            "field_id": str(field.id),
            "entity_type": "player",
            "entity_id": str(auth_tracker_client["player_id"]),
            "delta": "1",
        },
    )
    assert resp.status_code == 200
    val = TrackerValue.query.filter_by(
        tracker_field_id=field.id, player_id=auth_tracker_client["player_id"]
    ).first()
    assert val.value == "1"


def test_value_update_cross_session_field_rejected(app, db, auth_tracker_client):
    """Submitting a field_id from a different session returns 400 (S-4)."""
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
        launch_session,
    )

    # Create a second game/gng/session
    game2 = Game(name=f"TG2 {uuid.uuid4().hex[:4]}", bgg_id=None)
    gn2 = GameNight(date=datetime.date(2024, 8, 1), final=False)
    _db.session.add_all([game2, gn2])
    _db.session.flush()
    gng2 = GameNightGame(game_night_id=gn2.id, game_id=game2.id, round=1)
    player2 = Player(game_night_id=gn2.id, people_id=auth_tracker_client["admin_id"])
    _db.session.add_all([gng2, player2])
    _db.session.flush()
    _db.session.commit()

    try:
        gng_id = auth_tracker_client["gng_id"]
        # Session A with one field
        session_a = get_or_create_configuring_session(gng_id)
        add_field(session_a.id, type="counter", label="VP", starting_value=0, is_score_field=True)
        launch_session(
            session_a.id,
            mode="individual",
            teams_data=[],
            player_ids=[auth_tracker_client["player_id"]],
        )

        # Session B with its own field
        session_b = get_or_create_configuring_session(gng2.id)
        field_b = add_field(
            session_b.id, type="counter", label="VP2", starting_value=0, is_score_field=True
        )
        launch_session(session_b.id, mode="individual", teams_data=[], player_ids=[player2.id])

        # Try to update session_b's field via session_a's URL
        c = auth_tracker_client["client"]
        resp = c.post(
            f"/tracker/{session_a.id}/value",
            data={
                "field_id": str(field_b.id),
                "entity_type": "player",
                "entity_id": str(auth_tracker_client["player_id"]),
                "delta": "1",
            },
        )
        assert resp.status_code == 400
    finally:
        TrackerSession.query.filter_by(game_night_game_id=gng2.id).delete()
        _db.session.delete(player2)
        _db.session.delete(gng2)
        _db.session.delete(gn2)
        _db.session.delete(game2)
        _db.session.commit()


# ── end game ──────────────────────────────────────────────────────────────────


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
    launch_session(
        session.id, mode="individual", teams_data=[], player_ids=[auth_tracker_client["player_id"]]
    )
    update_value(
        session.id,
        field.id,
        entity_type="player",
        entity_id=auth_tracker_client["player_id"],
        delta=5,
    )
    resp = c.get(f"/tracker/{session.id}/end")
    assert resp.status_code == 200
    assert b"VP" in resp.data
    session_obj = TrackerSession.query.get(session.id)
    assert session_obj.status == "active"  # GET does not mutate status


def test_end_game_completed_session_redirects(app, db, auth_tracker_client):
    """end_game redirects when session is already completed (M-3)."""
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
        launch_session,
        save_results,
        update_value,
    )

    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    field = add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
    launch_session(
        session.id, mode="individual", teams_data=[], player_ids=[auth_tracker_client["player_id"]]
    )
    update_value(
        session.id,
        field.id,
        entity_type="player",
        entity_id=auth_tracker_client["player_id"],
        delta=3,
    )
    save_results(
        session.id,
        [
            {
                "player_id": auth_tracker_client["player_id"],
                "team_id": None,
                "position": 1,
                "score": 3,
            }
        ],
    )
    resp = c.get(f"/tracker/{session.id}/end")
    assert resp.status_code == 302


# ── save results ──────────────────────────────────────────────────────────────


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
    launch_session(
        session.id, mode="individual", teams_data=[], player_ids=[auth_tracker_client["player_id"]]
    )
    update_value(
        session.id,
        field.id,
        entity_type="player",
        entity_id=auth_tracker_client["player_id"],
        delta=5,
    )
    player_id = auth_tracker_client["player_id"]
    resp = c.post(
        f"/tracker/{session.id}/save",
        data={
            f"position_p_{player_id}": "1",
            f"score_p_{player_id}": "5",
        },
    )
    assert resp.status_code == 302
    session_obj = TrackerSession.query.get(session.id)
    assert session_obj.status == "completed"
    result = Result.query.filter_by(game_night_game_id=gng_id, player_id=player_id).first()
    assert result is not None
    assert result.position == 1


def test_save_results_arbitrary_player_id_rejected(app, db, auth_tracker_client):
    """save_results rejects player IDs not in the session (S-5)."""
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
        launch_session,
    )

    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
    launch_session(
        session.id, mode="individual", teams_data=[], player_ids=[auth_tracker_client["player_id"]]
    )
    # Submit a fabricated player_id that was never seeded
    resp = c.post(
        f"/tracker/{session.id}/save",
        data={
            "position_p_99999": "1",
            "score_p_99999": "10",
        },
    )
    # Should redirect back to end_game with error
    assert resp.status_code == 302
    assert "/end" in resp.headers["Location"]


# ── discard ───────────────────────────────────────────────────────────────────


def test_discard_deletes_session(app, db, auth_tracker_client):
    from app.services.tracker_services import get_or_create_configuring_session

    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    sid = session.id
    resp = c.post(f"/tracker/{sid}/discard")
    assert resp.status_code == 302
    assert TrackerSession.query.get(sid) is None


# ── view_game_night integration ───────────────────────────────────────────────


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


# ── team mode ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def team_tracker_client(app, db):
    """Admin client with two players set up for team-mode tracking."""
    from app.extensions import bcrypt
    from app.models import Poll

    _db.session.rollback()
    for email in ["team_admin@example.com", "team_player2@example.com"]:
        existing = Person.query.filter_by(email=email).first()
        if existing:
            for poll in Poll.query.filter_by(created_by=existing.id).all():
                _db.session.delete(poll)
            _db.session.flush()
            _db.session.delete(existing)
    _db.session.commit()

    admin = Person(
        first_name="Team",
        last_name="Admin",
        email="team_admin@example.com",
        password=bcrypt.generate_password_hash("password", rounds=4).decode("utf-8"),
        admin=True,
        owner=False,
    )
    player2_person = Person(
        first_name="Player",
        last_name="Two",
        email="team_player2@example.com",
        password=bcrypt.generate_password_hash("password", rounds=4).decode("utf-8"),
        admin=False,
        owner=False,
    )
    _db.session.add_all([admin, player2_person])
    _db.session.flush()

    game = Game(name=f"TM {uuid.uuid4().hex[:4]}", bgg_id=None)
    gn = GameNight(date=datetime.date(2024, 9, 1), final=False)
    _db.session.add_all([game, gn])
    _db.session.flush()

    gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
    _db.session.add(gng)
    _db.session.flush()

    p1 = Player(game_night_id=gn.id, people_id=admin.id)
    p2 = Player(game_night_id=gn.id, people_id=player2_person.id)
    _db.session.add_all([p1, p2])
    _db.session.commit()

    with app.test_client() as client:
        client.post("/login", data={"email": "team_admin@example.com", "password": "password"})
        yield {
            "client": client,
            "gng_id": gng.id,
            "gn_id": gn.id,
            "player1_id": p1.id,
            "player2_id": p2.id,
            "gng": gng,
            "gn": gn,
            "game": game,
            "admin": admin,
            "player2_person": player2_person,
        }

    _db.session.rollback()
    TrackerSession.query.filter_by(game_night_game_id=gng.id).delete()
    _db.session.delete(p1)
    _db.session.delete(p2)
    _db.session.delete(gng)
    _db.session.delete(gn)
    _db.session.delete(game)
    for email in ["team_admin@example.com", "team_player2@example.com"]:
        existing = Person.query.filter_by(email=email).first()
        if existing:
            _db.session.delete(existing)
    _db.session.commit()


def test_team_mode_live_tracker_loads(app, db, team_tracker_client):
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
        launch_session,
    )

    c = team_tracker_client["client"]
    gng_id = team_tracker_client["gng_id"]
    p1_id = team_tracker_client["player1_id"]
    p2_id = team_tracker_client["player2_id"]

    session = get_or_create_configuring_session(gng_id)
    add_field(session.id, type="counter", label="Score", starting_value=0, is_score_field=True)
    launch_session(
        session.id,
        mode="teams",
        teams_data=[
            {"name": "Red", "player_ids": [p1_id]},
            {"name": "Blue", "player_ids": [p2_id]},
        ],
        player_ids=[],
    )
    resp = c.get(f"/tracker/{session.id}")
    assert resp.status_code == 200
    assert b"Red" in resp.data
    assert b"Blue" in resp.data


def test_team_mode_save_results_writes_all_members(app, db, team_tracker_client):
    """Team save_results writes Result rows for each team member (C-1)."""
    from app.models import Result, TrackerSession, TrackerTeam
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
        launch_session,
        update_value,
    )

    c = team_tracker_client["client"]
    gng_id = team_tracker_client["gng_id"]
    p1_id = team_tracker_client["player1_id"]
    p2_id = team_tracker_client["player2_id"]

    session = get_or_create_configuring_session(gng_id)
    field = add_field(
        session.id, type="counter", label="Score", starting_value=0, is_score_field=True
    )
    launch_session(
        session.id,
        mode="teams",
        teams_data=[
            {"name": "Red", "player_ids": [p1_id]},
            {"name": "Blue", "player_ids": [p2_id]},
        ],
        player_ids=[],
    )

    # Update scores for both teams
    teams = TrackerTeam.query.filter_by(tracker_session_id=session.id).all()
    red = next(t for t in teams if t.name == "Red")
    blue = next(t for t in teams if t.name == "Blue")
    update_value(session.id, field.id, entity_type="team", entity_id=red.id, delta=10)
    update_value(session.id, field.id, entity_type="team", entity_id=blue.id, delta=5)

    resp = c.post(
        f"/tracker/{session.id}/save",
        data={
            f"position_t_{red.id}": "1",
            f"score_t_{red.id}": "10",
            f"position_t_{blue.id}": "2",
            f"score_t_{blue.id}": "5",
        },
    )
    assert resp.status_code == 302

    session_obj = TrackerSession.query.get(session.id)
    assert session_obj.status == "completed"
    # Both players should have Result rows
    r1 = Result.query.filter_by(game_night_game_id=gng_id, player_id=p1_id).first()
    r2 = Result.query.filter_by(game_night_game_id=gng_id, player_id=p2_id).first()
    assert r1 is not None and r1.position == 1 and r1.score == 10
    assert r2 is not None and r2.position == 2 and r2.score == 5


def test_team_mode_compute_rankings(app, db, team_tracker_client):
    """compute_rankings works correctly for team mode."""
    from app.models import TrackerTeam
    from app.services.tracker_services import (
        add_field,
        compute_rankings,
        get_or_create_configuring_session,
        launch_session,
        update_value,
    )

    gng_id = team_tracker_client["gng_id"]
    p1_id = team_tracker_client["player1_id"]
    p2_id = team_tracker_client["player2_id"]

    session = get_or_create_configuring_session(gng_id)
    field = add_field(
        session.id, type="counter", label="Score", starting_value=0, is_score_field=True
    )
    launch_session(
        session.id,
        mode="teams",
        teams_data=[
            {"name": "Alpha", "player_ids": [p1_id]},
            {"name": "Beta", "player_ids": [p2_id]},
        ],
        player_ids=[],
    )

    teams = TrackerTeam.query.filter_by(tracker_session_id=session.id).all()
    alpha = next(t for t in teams if t.name == "Alpha")
    beta = next(t for t in teams if t.name == "Beta")
    update_value(session.id, field.id, entity_type="team", entity_id=alpha.id, delta=7)
    update_value(session.id, field.id, entity_type="team", entity_id=beta.id, delta=3)

    rankings = compute_rankings(session.id)
    assert len(rankings) == 2
    assert rankings[0]["score"] == 7
    assert rankings[0]["position"] == 1
    assert rankings[1]["score"] == 3
    assert rankings[1]["position"] == 2
