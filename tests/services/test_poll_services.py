import uuid
from datetime import datetime, timedelta

import pytest

from app.extensions import db as _db
from app.models import Person, Poll, PollResponse
from app.services.poll_services import (
    can_view,
    create_availability_poll,
    create_poll,
    get_results,
    parse_closes_at,
    poll_is_active,
    rsvps_for_night,
    submit_response,
)


@pytest.fixture()
def poll_author(app, db):
    with app.app_context():
        person = Person(
            first_name="Test",
            last_name="Author",
            email=f"author_{uuid.uuid4().hex[:8]}@test.invalid",
        )
        _db.session.add(person)
        _db.session.commit()
        yield person


@pytest.fixture()
def sample_poll(app, db, poll_author):
    with app.app_context():
        poll = create_poll(
            title="Test Poll",
            description="Which day?",
            option_labels=["Friday", "Saturday", "Sunday"],
            created_by_id=poll_author.id,
            multi_select=False,
        )
        yield poll


def test_poll_is_active_open_poll(app, sample_poll):
    with app.app_context():
        assert poll_is_active(sample_poll) is True


def test_poll_is_active_manually_closed(app, sample_poll):
    with app.app_context():
        sample_poll.closed = True
        assert poll_is_active(sample_poll) is False


def test_poll_is_active_expired(app, sample_poll):
    with app.app_context():
        sample_poll.closes_at = datetime.utcnow() - timedelta(hours=1)
        assert poll_is_active(sample_poll) is False


def test_poll_is_active_not_yet_expired(app, sample_poll):
    with app.app_context():
        sample_poll.closes_at = datetime.utcnow() + timedelta(hours=1)
        assert poll_is_active(sample_poll) is True


def test_poll_is_active_at_exact_boundary(app, sample_poll):
    with app.app_context():
        sample_poll.closes_at = datetime.utcnow()
        assert poll_is_active(sample_poll) is False


def test_create_poll_generates_token(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Availability", None, ["Mon", "Tue"], poll_author.id, False)
        assert poll.token is not None
        assert len(poll.token) >= 16


def test_create_poll_creates_options(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B", "C"], poll_author.id, False)
        assert len(poll.options) == 3
        assert poll.options[0].label == "A"
        assert poll.options[1].display_order == 1


@pytest.fixture()
def voters(app, db):
    people = [
        Person(first_name=n, last_name="Voter", email=f"{n}_{uuid.uuid4().hex[:8]}@test.invalid")
        for n in ("Alice", "Bob", "Carol")
    ]
    _db.session.add_all(people)
    _db.session.commit()
    return people


def test_submit_response_single_select(app, db, poll_author, voters):
    poll = create_poll("Q", None, ["A", "B"], poll_author.id, False)
    success, msg = submit_response(poll, [poll.options[0].id], voters[0].id)
    assert success is True
    assert PollResponse.query.filter_by(poll_id=poll.id).count() == 1


def test_submit_response_second_answer_replaces_first(app, db, poll_author, voters):
    poll = create_poll("Q", None, ["A", "B"], poll_author.id, False)
    submit_response(poll, [poll.options[0].id], voters[0].id)
    success, msg = submit_response(poll, [poll.options[1].id], voters[0].id)
    assert success is True
    assert "updated" in msg.lower()
    responses = PollResponse.query.filter_by(poll_id=poll.id).all()
    assert [r.option_id for r in responses] == [poll.options[1].id]


def test_submit_response_single_select_rejects_two_options(app, db, poll_author, voters):
    poll = create_poll("Q", None, ["A", "B"], poll_author.id, False)
    ids = [poll.options[0].id, poll.options[1].id]
    success, _ = submit_response(poll, ids, voters[0].id)
    assert success is False


def test_submit_response_replaces_on_multi_select(app, db, poll_author):
    poll = create_poll("Q", None, ["A", "B", "C"], poll_author.id, True)
    ids = [poll.options[0].id, poll.options[1].id]
    submit_response(poll, ids, poll_author.id)
    success, _ = submit_response(poll, [poll.options[2].id], poll_author.id)
    assert success is True
    responses = PollResponse.query.filter_by(poll_id=poll.id, person_id=poll_author.id).all()
    assert [r.option_id for r in responses] == [poll.options[2].id]


def test_create_poll_token_collision_raises(app, db, poll_author):
    from unittest.mock import patch

    existing = create_poll("Existing", None, ["A"], poll_author.id, False)
    with patch.object(Poll, "generate_token", return_value=existing.token):
        with pytest.raises(RuntimeError):
            create_poll("New", None, ["A"], poll_author.id, False)


def test_submit_response_rejected_for_closed_poll(app, db, poll_author):
    poll = create_poll("Q", None, ["A"], poll_author.id, False)
    poll.closed = True
    success, msg = submit_response(poll, [poll.options[0].id], poll_author.id)
    assert success is False


def test_get_results_counts_responses(app, db, poll_author, voters):
    poll = create_poll("Q", None, ["A", "B"], poll_author.id, False)
    submit_response(poll, [poll.options[0].id], voters[0].id)
    submit_response(poll, [poll.options[0].id], voters[1].id)
    submit_response(poll, [poll.options[1].id], voters[2].id)
    results = get_results(poll)
    a_count = next(r["count"] for r in results if r["label"] == "A")
    b_count = next(r["count"] for r in results if r["label"] == "B")
    assert a_count == 2
    assert b_count == 1


def test_parse_closes_at_treats_input_as_local_time(app, db):
    # 7pm Chicago in October is CDT (UTC-5) → midnight UTC
    assert parse_closes_at("2026-10-04T19:00") == datetime(2026, 10, 5, 0, 0)
    assert parse_closes_at("") is None
    with pytest.raises(ValueError):
        parse_closes_at("not a date")


def test_rsvps_come_from_availability_poll(app, db, poll_author, voters):
    import datetime as dt

    from app.models import GameNight, Player

    gn = GameNight(date=dt.date(2026, 10, 4))
    _db.session.add(gn)
    _db.session.flush()
    _db.session.add_all([Player(game_night_id=gn.id, people_id=v.id) for v in voters])
    _db.session.commit()

    ok, _ = create_availability_poll(gn.id, poll_author.id)
    assert ok
    poll = gn.availability_poll
    assert poll.availability and poll.game_night_id == gn.id
    ok, msg = create_availability_poll(gn.id, poll_author.id)
    assert not ok and "already" in msg

    submit_response(poll, [poll.options[0].id], voters[0].id)
    submit_response(poll, [poll.options[2].id], voters[1].id)
    assert rsvps_for_night(gn) == {voters[0].id: "Can Make It", voters[1].id: "Can't Make It"}


def test_linked_poll_visible_only_to_that_nights_players(app, db, poll_author, voters):
    import datetime as dt
    from types import SimpleNamespace

    from app.models import GameNight, Player

    gn = GameNight(date=dt.date(2026, 10, 11))
    _db.session.add(gn)
    _db.session.flush()
    _db.session.add(Player(game_night_id=gn.id, people_id=voters[0].id))
    _db.session.commit()
    poll = create_poll("Which game?", None, ["A", "B"], poll_author.id, False, game_night_id=gn.id)

    def user(person, admin=False):
        return SimpleNamespace(is_authenticated=True, id=person.id, admin=admin, owner=False)

    assert can_view(poll, user(voters[0]))
    assert not can_view(poll, user(voters[1]))
    assert can_view(poll, user(voters[1], admin=True))
    assert not can_view(poll, SimpleNamespace(is_authenticated=False))
