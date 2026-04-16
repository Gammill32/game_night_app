import uuid

import pytest

from app.extensions import db as _db
from app.models import Person, Poll
from app.services.poll_services import (
    create_poll,
    get_detailed_results,
    get_user_responses,
    submit_response,
)


@pytest.fixture()
def poll_author(app, db):
    person = Person(
        first_name="Poll",
        last_name="Author",
        email=f"pollauthor_{uuid.uuid4().hex[:8]}@test.invalid",
    )
    _db.session.add(person)
    _db.session.commit()
    yield person


@pytest.fixture()
def open_poll(app, db, poll_author):
    poll = create_poll("Best Day?", None, ["Friday", "Saturday"], poll_author.id, False)
    yield poll


@pytest.fixture()
def closed_poll(app, db, poll_author):
    poll = create_poll("Old Poll", None, ["A", "B"], poll_author.id, False)
    poll.closed = True
    _db.session.commit()
    yield poll


def test_poll_page_loads(client, open_poll):
    resp = client.get(f"/poll/{open_poll.token}")
    assert resp.status_code == 200
    assert b"Best Day?" in resp.data
    assert b'name="option_ids"' in resp.data
    assert b'name="respondent_name"' in resp.data


def test_poll_page_404_for_bad_token(client):
    resp = client.get("/poll/notarealtoken")
    assert resp.status_code == 404


def test_poll_page_shows_closed_message(client, closed_poll):
    resp = client.get(f"/poll/{closed_poll.token}")
    assert resp.status_code == 200
    assert b"closed" in resp.data.lower()


def test_submit_response_anonymous(client, open_poll):
    option_id = open_poll.options[0].id
    resp = client.post(
        f"/poll/{open_poll.token}/respond",
        data={"option_ids": str(option_id), "respondent_name": "Alice"},
    )
    assert resp.status_code == 200
    assert b"Thank you" in resp.data or b"thank" in resp.data.lower()


def test_submit_response_sets_session_cookie(client, open_poll):
    option_id = open_poll.options[0].id
    with client.session_transaction() as sess:
        assert f"poll_{open_poll.token}_responded" not in sess
    client.post(
        f"/poll/{open_poll.token}/respond",
        data={"option_ids": str(option_id), "respondent_name": "Bob"},
    )
    with client.session_transaction() as sess:
        assert sess.get(f"poll_{open_poll.token}_responded") is True


def test_submit_response_rejects_duplicate(client, open_poll):
    option_id = open_poll.options[0].id
    client.post(
        f"/poll/{open_poll.token}/respond",
        data={"option_ids": str(option_id), "respondent_name": "Carol"},
    )
    resp = client.post(
        f"/poll/{open_poll.token}/respond",
        data={"option_ids": str(option_id), "respondent_name": "Carol"},
    )
    assert resp.status_code == 200
    assert b"already" in resp.data.lower()


def test_admin_can_create_poll(admin_client):
    resp = admin_client.post(
        "/polls/create",
        data={
            "title": "New Poll",
            "description": "",
            "option_labels": ["Option A", "Option B"],
            "multi_select": "false",
        },
    )
    assert resp.status_code in (200, 302)
    assert Poll.query.filter_by(title="New Poll").first() is not None


def test_non_admin_cannot_access_create(auth_client):
    resp = auth_client.get("/polls/create")
    assert resp.status_code in (302, 403)


def test_admin_poll_list_shows_polls(admin_client, open_poll):
    resp = admin_client.get("/polls/")
    assert resp.status_code == 200
    assert b"Best Day?" in resp.data


def test_submit_response_rejects_missing_name(client, open_poll):
    option_id = open_poll.options[0].id
    resp = client.post(f"/poll/{open_poll.token}/respond", data={"option_ids": str(option_id)})
    assert resp.status_code == 200
    assert b"name" in resp.data.lower() or b"error" in resp.data.lower()


def test_get_detailed_results_returns_voters(app, db, open_poll, poll_author):
    """Detailed results include voter names per option."""
    # Submit as authenticated user
    submit_response(open_poll, [open_poll.options[0].id], poll_author.id, None)
    # Submit as anonymous
    submit_response(open_poll, [open_poll.options[1].id], None, "Alice")

    results = get_detailed_results(open_poll)

    assert len(results) == 2
    first_label = open_poll.options[0].label
    second_label = open_poll.options[1].label
    first_opt = next(r for r in results if r["label"] == first_label)
    second_opt = next(r for r in results if r["label"] == second_label)
    assert first_opt["count"] == 1
    assert first_opt["voters"][0]["name"] == "Poll Author"
    assert first_opt["voters"][0]["person_id"] == poll_author.id
    assert second_opt["count"] == 1
    assert second_opt["voters"][0]["name"] == "Alice"
    assert second_opt["voters"][0]["person_id"] is None


def test_get_user_responses_returns_option_ids(app, db, open_poll, poll_author):
    """Returns set of option IDs the user voted for."""
    option_id = open_poll.options[0].id
    submit_response(open_poll, [option_id], poll_author.id, None)

    result = get_user_responses(open_poll, poll_author.id)
    assert result == {option_id}


def test_get_user_responses_empty_when_not_voted(app, db, open_poll, poll_author):
    """Returns empty set when user has not voted."""
    result = get_user_responses(open_poll, poll_author.id)
    assert result == set()


def test_admin_results_route_shows_voters(admin_client, open_poll, poll_author):
    """Admin can see who voted for each option."""
    submit_response(open_poll, [open_poll.options[0].id], poll_author.id, None)
    submit_response(open_poll, [open_poll.options[1].id], None, "Guest")

    resp = admin_client.get(f"/polls/{open_poll.id}/results")
    assert resp.status_code == 200
    assert b"Poll Author" in resp.data
    assert b"Guest" in resp.data
    assert b"Friday" in resp.data
    assert b"Saturday" in resp.data


def test_admin_results_route_requires_admin(auth_client, open_poll):
    """Non-admin cannot access detailed results."""
    resp = auth_client.get(f"/polls/{open_poll.id}/results")
    assert resp.status_code in (302, 403)


def test_logged_in_user_sees_already_responded_without_session(auth_client, app, db, open_poll):
    """Logged-in user who voted but cleared session still sees 'already responded'."""
    from app.models import Person

    user = Person.query.filter_by(email="test@example.com").first()
    option_id = open_poll.options[0].id
    submit_response(open_poll, [option_id], user.id, None)

    # Clear session to simulate cookie loss
    with auth_client.session_transaction() as sess:
        sess.clear()
    # Re-login (session was cleared)
    auth_client.post("/login", data={"email": "test@example.com", "password": "password"})

    resp = auth_client.get(f"/poll/{open_poll.token}")
    assert resp.status_code == 200
    # Vote form should NOT be present — user already voted
    assert b'name="option_ids"' not in resp.data
    assert b"already responded" in resp.data.lower()


def test_multi_select_allows_revote(auth_client, app, db, poll_author):
    """Multi-select polls always show the form so users can change their vote."""
    multi_poll = create_poll("Multi?", None, ["A", "B", "C"], poll_author.id, True)
    from app.models import Person

    user = Person.query.filter_by(email="test@example.com").first()
    submit_response(multi_poll, [multi_poll.options[0].id], user.id, None)

    resp = auth_client.get(f"/poll/{multi_poll.token}")
    assert resp.status_code == 200
    # Form should still be present for multi-select polls
    assert b'name="option_ids"' in resp.data


def test_multi_select_revote_pre_checks_previous_selections(auth_client, app, db, poll_author):
    """Multi-select revote form should pre-check previously selected options."""
    multi_poll = create_poll("Pick many", None, ["A", "B", "C"], poll_author.id, True)
    from app.models import Person

    user = Person.query.filter_by(email="test@example.com").first()
    chosen = [multi_poll.options[0].id, multi_poll.options[2].id]
    submit_response(multi_poll, chosen, user.id, None)

    resp = auth_client.get(f"/poll/{multi_poll.token}")
    assert resp.status_code == 200
    # Collapse whitespace so attribute order/indentation does not matter
    body = " ".join(resp.data.decode().split())
    for oid in chosen:
        assert f'value="{oid}" checked' in body
    unchosen = multi_poll.options[1].id
    assert f'value="{unchosen}" checked' not in body


def test_logged_in_user_sees_own_vote_highlighted(auth_client, app, db, open_poll):
    """After voting, logged-in user sees their choice marked exactly once."""
    from app.models import Person

    user = Person.query.filter_by(email="test@example.com").first()
    option = open_poll.options[0]
    submit_response(open_poll, [option.id], user.id, None)

    resp = auth_client.get(f"/poll/{open_poll.token}")
    assert resp.status_code == 200
    # The voted option should have the "your-vote" marker (appears once in class)
    assert resp.data.count(b'class="your-vote') == 1
    # The "Your vote" human-readable label should also appear once
    assert resp.data.count(b"Your vote") == 1


def test_anonymous_vote_stored_in_session(client, open_poll):
    """Anonymous user's vote is stored in session AND renders as highlighted."""
    option_id = open_poll.options[0].id
    client.post(
        f"/poll/{open_poll.token}/respond",
        data={"option_ids": str(option_id), "respondent_name": "Dana"},
    )
    with client.session_transaction() as sess:
        assert sess.get(f"poll_{open_poll.token}_votes") == [option_id]

    # Subsequent GET should render the highlight from session data
    resp = client.get(f"/poll/{open_poll.token}")
    assert resp.status_code == 200
    assert b"your-vote" in resp.data


def test_poll_thanks_does_not_render_results_on_failure(client, open_poll):
    """Failure paths pass results=None; template must not attempt to render _poll_results.html."""
    # Submit with no option selected — triggers failure path
    resp = client.post(
        f"/poll/{open_poll.token}/respond",
        data={"respondent_name": "Ella"},
    )
    assert resp.status_code == 200
    # The results partial would include this class on every vote row
    assert b"your-vote" not in resp.data
    # Error message should be present
    assert b"at least one option" in resp.data.lower() or b"error" in resp.data.lower()
