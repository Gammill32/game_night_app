import datetime
import uuid

import pytest

from app.extensions import db as _db
from app.models import (
    Game,
    GameNight,
    GameNightGame,
    Person,
    Player,
    TrackerField,
    TrackerSession,
    TrackerValue,
)


def test_tracker_models_importable():
    from app.models import TrackerField, TrackerSession, TrackerTeam, TrackerValue

    assert TrackerSession.__tablename__ == "tracker_sessions"
    assert TrackerField.__tablename__ == "tracker_fields"
    assert TrackerTeam.__tablename__ == "tracker_teams"
    assert TrackerValue.__tablename__ == "tracker_values"


@pytest.fixture()
def tracker_night(app, db):
    """A game night with one game and two players."""
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

    yield {
        "gng_id": gng.id,
        "gn_id": gn.id,
        "pl1_id": pl1.id,
        "pl2_id": pl2.id,
        "game": game,
        "gn": gn,
        "gng": gng,
        "p1": p1,
        "p2": p2,
    }

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


@pytest.fixture()
def active_session(app, db, tracker_night):
    """A launched tracker session with VP counter (score) and a checkbox."""
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
        launch_session,
    )

    session = get_or_create_configuring_session(tracker_night["gng_id"])
    add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
    add_field(session.id, type="checkbox", label="Crown", starting_value=0, is_score_field=False)
    launch_session(
        session.id,
        mode="individual",
        teams_data=[],
        player_ids=[tracker_night["pl1_id"], tracker_night["pl2_id"]],
    )
    yield {
        "session_id": session.id,
        "pl1_id": tracker_night["pl1_id"],
        "pl2_id": tracker_night["pl2_id"],
        "gng_id": tracker_night["gng_id"],
    }


def test_update_value_increments_counter(app, db, active_session):
    from app.services.tracker_services import update_value

    sid = active_session["session_id"]
    field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
    update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=1)
    update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=1)
    val = TrackerValue.query.filter_by(
        tracker_field_id=field.id, player_id=active_session["pl1_id"]
    ).first()
    assert val.value == "2"


def test_update_value_can_go_negative(app, db, active_session):
    from app.services.tracker_services import update_value

    sid = active_session["session_id"]
    field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
    update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=-1)
    val = TrackerValue.query.filter_by(
        tracker_field_id=field.id, player_id=active_session["pl1_id"]
    ).first()
    assert val.value == "-1"


def test_update_value_sets_checkbox(app, db, active_session):
    from app.services.tracker_services import update_value

    sid = active_session["session_id"]
    field = TrackerField.query.filter_by(tracker_session_id=sid, label="Crown").first()
    update_value(
        sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], value="true"
    )
    val = TrackerValue.query.filter_by(
        tracker_field_id=field.id, player_id=active_session["pl1_id"]
    ).first()
    assert val.value == "true"


def test_update_value_rejects_invalid_counter_value(app, db, active_session):
    from app.services.tracker_services import update_value

    sid = active_session["session_id"]
    field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
    with pytest.raises(ValueError):
        update_value(
            sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], value="banana"
        )


def test_get_or_create_configuring_session_creates_new(app, db, tracker_night):
    from app.services.tracker_services import get_or_create_configuring_session

    session = get_or_create_configuring_session(tracker_night["gng_id"])
    assert session.status == "configuring"
    assert session.mode == "individual"
    assert session.game_night_game_id == tracker_night["gng_id"]


def test_get_or_create_configuring_session_returns_existing(app, db, tracker_night):
    from app.services.tracker_services import get_or_create_configuring_session

    s1 = get_or_create_configuring_session(tracker_night["gng_id"])
    s2 = get_or_create_configuring_session(tracker_night["gng_id"])
    assert s1.id == s2.id


def test_discard_session_removes_session(app, db, tracker_night):
    from app.services.tracker_services import discard_session, get_or_create_configuring_session

    session = get_or_create_configuring_session(tracker_night["gng_id"])
    sid = session.id
    discard_session(sid)
    assert TrackerSession.query.get(sid) is None


def test_add_field_creates_tracker_field(app, db, tracker_night):
    from app.services.tracker_services import add_field, get_or_create_configuring_session

    session = get_or_create_configuring_session(tracker_night["gng_id"])
    field = add_field(
        session.id, type="counter", label="Victory Points", starting_value=0, is_score_field=True
    )
    assert field.label == "Victory Points"
    assert field.type == "counter"
    assert field.is_score_field is True
    assert TrackerField.query.filter_by(tracker_session_id=session.id).count() == 1


def test_launch_session_seeds_values_for_individual(app, db, tracker_night):
    from app.services.tracker_services import (
        add_field,
        get_or_create_configuring_session,
        launch_session,
    )

    session = get_or_create_configuring_session(tracker_night["gng_id"])
    add_field(session.id, type="counter", label="VP", starting_value=5, is_score_field=True)
    add_field(
        session.id, type="checkbox", label="Has Crown", starting_value=0, is_score_field=False
    )
    add_field(
        session.id, type="global_counter", label="Round", starting_value=1, is_score_field=False
    )

    launch_session(
        session.id,
        mode="individual",
        teams_data=[],
        player_ids=[tracker_night["pl1_id"], tracker_night["pl2_id"]],
    )

    session = TrackerSession.query.get(session.id)
    assert session.status == "active"
    assert session.mode == "individual"

    # counter and checkbox → 2 players × 2 fields = 4 per-player values
    # global_counter → 1 global value
    values = TrackerValue.query.filter_by(tracker_session_id=session.id).all()
    assert len(values) == 5

    # Per-player counter starts at 5
    vp_field = TrackerField.query.filter_by(tracker_session_id=session.id, label="VP").first()
    vp_values = TrackerValue.query.filter_by(tracker_field_id=vp_field.id).all()
    assert all(v.value == "5" for v in vp_values)

    # Global counter starts at 1
    round_field = TrackerField.query.filter_by(tracker_session_id=session.id, label="Round").first()
    round_val = TrackerValue.query.filter_by(tracker_field_id=round_field.id).first()
    assert round_val.value == "1"
    assert round_val.player_id is None
    assert round_val.team_id is None


def test_compute_rankings_sorts_descending(app, db, active_session):
    from app.services.tracker_services import compute_rankings, update_value

    sid = active_session["session_id"]
    field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
    update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=10)
    update_value(sid, field.id, entity_type="player", entity_id=active_session["pl2_id"], delta=7)
    rankings = compute_rankings(sid)
    assert rankings[0]["player_id"] == active_session["pl1_id"]
    assert rankings[0]["position"] == 1
    assert rankings[0]["score"] == 10
    assert rankings[1]["player_id"] == active_session["pl2_id"]
    assert rankings[1]["position"] == 2
    assert rankings[1]["score"] == 7


def test_compute_rankings_ties_share_position(app, db, active_session):
    from app.services.tracker_services import compute_rankings, update_value

    sid = active_session["session_id"]
    field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
    update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=5)
    update_value(sid, field.id, entity_type="player", entity_id=active_session["pl2_id"], delta=5)
    rankings = compute_rankings(sid)
    assert rankings[0]["position"] == 1
    assert rankings[1]["position"] == 1


def test_save_results_creates_result_rows(app, db, active_session):
    from app.models import Result
    from app.services.tracker_services import compute_rankings, save_results, update_value

    sid = active_session["session_id"]
    field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
    gng_id = active_session["gng_id"]
    update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=10)
    update_value(sid, field.id, entity_type="player", entity_id=active_session["pl2_id"], delta=7)
    rankings = compute_rankings(sid)
    save_results(sid, rankings)
    results = Result.query.filter_by(game_night_game_id=gng_id).all()
    assert len(results) == 2
    winner = next(r for r in results if r.player_id == active_session["pl1_id"])
    assert winner.position == 1
    assert winner.score == 10
    session = TrackerSession.query.get(sid)
    assert session.status == "completed"


def test_save_results_upserts_existing_rows(app, db, active_session):
    from app.extensions import db as _db
    from app.models import Result
    from app.services.tracker_services import compute_rankings, save_results, update_value

    sid = active_session["session_id"]
    field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
    gng_id = active_session["gng_id"]
    update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=10)
    rankings = compute_rankings(sid)
    save_results(sid, rankings)
    # Save again with different score — reset status first
    session = TrackerSession.query.get(sid)
    session.status = "active"
    _db.session.commit()
    update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=5)
    rankings = compute_rankings(sid)
    save_results(sid, rankings)
    results = Result.query.filter_by(game_night_game_id=gng_id).all()
    # No duplicate rows
    assert len(results) == 2
