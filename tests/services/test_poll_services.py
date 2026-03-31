import uuid
from datetime import datetime, timedelta

import pytest

from app.extensions import db as _db
from app.models import Person, Poll, PollResponse
from app.services.poll_services import (
    create_poll,
    get_results,
    poll_is_active,
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


def test_submit_response_anonymous_single_select(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B"], poll_author.id, False)
        option_id = poll.options[0].id
        success, msg = submit_response(
            poll, option_ids=[option_id], person_id=None, respondent_name="Alice"
        )
        assert success is True
        assert PollResponse.query.filter_by(poll_id=poll.id).count() == 1


def test_submit_response_rejects_duplicate_single_select(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B"], poll_author.id, False)
        option_id = poll.options[0].id
        submit_response(poll, [option_id], None, "Alice")
        success, msg = submit_response(poll, [option_id], None, "Alice")
        assert success is False
        assert "already" in msg.lower()


def test_submit_response_name_matching_is_case_insensitive(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B"], poll_author.id, False)
        option_id = poll.options[0].id
        submit_response(poll, [option_id], None, "Alice")
        success, _ = submit_response(poll, [option_id], None, "ALICE")
        assert success is False


def test_submit_response_replaces_on_multi_select(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B", "C"], poll_author.id, True)
        ids = [poll.options[0].id, poll.options[1].id]
        submit_response(poll, ids, None, "Bob")
        new_ids = [poll.options[2].id]
        success, _ = submit_response(poll, new_ids, None, "Bob")
        assert success is True
        responses = PollResponse.query.filter_by(poll_id=poll.id).all()
        assert len(responses) == 1
        assert responses[0].option_id == poll.options[2].id


def test_submit_response_logged_in_multi_select(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B", "C"], poll_author.id, True)
        ids = [poll.options[0].id, poll.options[1].id]
        submit_response(poll, ids, person_id=poll_author.id, respondent_name=None)
        new_ids = [poll.options[2].id]
        success, _ = submit_response(poll, new_ids, person_id=poll_author.id, respondent_name=None)
        assert success is True
        responses = PollResponse.query.filter_by(poll_id=poll.id, person_id=poll_author.id).all()
        assert len(responses) == 1


def test_create_poll_token_collision_raises(app, db, poll_author):
    from unittest.mock import patch

    with app.app_context():
        existing = create_poll("Existing", None, ["A"], poll_author.id, False)
        with patch.object(Poll, "generate_token", return_value=existing.token):
            with pytest.raises(RuntimeError):
                create_poll("New", None, ["A"], poll_author.id, False)


def test_submit_response_rejected_for_closed_poll(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A"], poll_author.id, False)
        poll.closed = True
        success, msg = submit_response(poll, [poll.options[0].id], None, "Alice")
        assert success is False


def test_get_results_counts_responses(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B"], poll_author.id, False)
        submit_response(poll, [poll.options[0].id], None, "Alice")
        submit_response(poll, [poll.options[0].id], None, "Bob")
        submit_response(poll, [poll.options[1].id], None, "Carol")
        results = get_results(poll)
        a_count = next(r["count"] for r in results if r["label"] == "A")
        b_count = next(r["count"] for r in results if r["label"] == "B")
        assert a_count == 2
        assert b_count == 1
