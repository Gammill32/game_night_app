import uuid

import pytest

from app.extensions import db as _db
from app.models import Person, Poll, PollResponse
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


def test_poll_page_loads(auth_client, open_poll):
    resp = auth_client.get(f"/poll/{open_poll.token}")
    assert resp.status_code == 200
    assert b"Best Day?" in resp.data
    assert b'name="option_ids"' in resp.data
    assert b'name="respondent_name"' not in resp.data


def test_poll_page_requires_login(client, open_poll):
    resp = client.get(f"/poll/{open_poll.token}")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_anonymous_cannot_submit(client, open_poll):
    resp = client.post(
        f"/poll/{open_poll.token}/respond", data={"option_ids": str(open_poll.options[0].id)}
    )
    assert resp.status_code == 302
    assert PollResponse.query.filter_by(poll_id=open_poll.id).count() == 0


def test_poll_page_404_for_bad_token(auth_client):
    resp = auth_client.get("/poll/notarealtoken")
    assert resp.status_code == 404


def test_poll_page_shows_closed_message(auth_client, closed_poll):
    resp = auth_client.get(f"/poll/{closed_poll.token}")
    assert resp.status_code == 200
    assert b"closed" in resp.data.lower()


def test_submit_response_records_and_shows_results(auth_client, open_poll):
    option_id = open_poll.options[0].id
    resp = auth_client.post(f"/poll/{open_poll.token}/respond", data={"option_ids": str(option_id)})
    assert resp.status_code == 200
    assert b"thank" in resp.data.lower()
    assert b"your-vote" in resp.data


def test_resubmitting_changes_the_answer(auth_client, open_poll):
    first, second = open_poll.options[0].id, open_poll.options[1].id
    auth_client.post(f"/poll/{open_poll.token}/respond", data={"option_ids": str(first)})
    resp = auth_client.post(f"/poll/{open_poll.token}/respond", data={"option_ids": str(second)})
    assert b"updated" in resp.data.lower()
    user = Person.query.filter_by(email="test@example.com").first()
    assert {r.option_id for r in PollResponse.query.filter_by(person_id=user.id)} == {second}


def test_private_poll_hidden_from_non_invitees(auth_client, poll_author):
    poll = create_poll("Secret", None, ["A", "B"], poll_author.id, False, private=True)
    assert auth_client.get(f"/poll/{poll.token}").status_code == 404


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


def test_get_detailed_results_returns_voters(app, db, open_poll, poll_author):
    """Detailed results include voter names per option."""
    submit_response(open_poll, [open_poll.options[0].id], poll_author.id)
    # Responses from before polls needed a login keep the name they gave
    _db.session.add(
        PollResponse(
            poll_id=open_poll.id, option_id=open_poll.options[1].id, respondent_name="Alice"
        )
    )
    _db.session.commit()

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
    submit_response(open_poll, [option_id], poll_author.id)

    result = get_user_responses(open_poll, poll_author.id)
    assert result == {option_id}


def test_get_user_responses_empty_when_not_voted(app, db, open_poll, poll_author):
    """Returns empty set when user has not voted."""
    result = get_user_responses(open_poll, poll_author.id)
    assert result == set()


def test_admin_results_route_shows_voters(admin_client, open_poll, poll_author):
    """Admin can see who voted for each option."""
    submit_response(open_poll, [open_poll.options[0].id], poll_author.id)
    _db.session.add(
        PollResponse(
            poll_id=open_poll.id, option_id=open_poll.options[1].id, respondent_name="Guest"
        )
    )
    _db.session.commit()

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


def test_single_select_shows_form_prechecked_after_voting(auth_client, app, db, open_poll):
    """A logged-in user who voted sees results and can change their answer."""
    user = Person.query.filter_by(email="test@example.com").first()
    option_id = open_poll.options[0].id
    submit_response(open_poll, [option_id], user.id)

    resp = auth_client.get(f"/poll/{open_poll.token}")
    body = " ".join(resp.data.decode().split())
    assert f'value="{option_id}" checked' in body
    assert "Update my answer" in body
    assert "Results" in body


def test_multi_select_allows_revote(auth_client, app, db, poll_author):
    """Multi-select polls always show the form so users can change their vote."""
    multi_poll = create_poll("Multi?", None, ["A", "B", "C"], poll_author.id, True)
    from app.models import Person

    user = Person.query.filter_by(email="test@example.com").first()
    submit_response(multi_poll, [multi_poll.options[0].id], user.id)

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
    submit_response(multi_poll, chosen, user.id)

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
    submit_response(open_poll, [option.id], user.id)

    resp = auth_client.get(f"/poll/{open_poll.token}")
    assert resp.status_code == 200
    # The voted option should have the "your-vote" marker (appears once in class)
    assert resp.data.count(b'class="your-vote') == 1
    # The "Your vote" human-readable label should also appear once
    assert resp.data.count(b"Your vote") == 1


def test_failed_submit_does_not_render_results(auth_client, open_poll):
    resp = auth_client.post(f"/poll/{open_poll.token}/respond", data={})
    assert resp.status_code == 200
    assert b"your-vote" not in resp.data
    assert b"at least one option" in resp.data.lower()


def test_share_email_says_to_sign_in(admin_client, make_person, monkeypatch):
    from app.extensions import mail

    ann = make_person("Ann")
    poll = create_poll("Share me", None, ["A", "B"], ann.id, False)
    sent = []
    monkeypatch.setattr(mail, "send", lambda msg: sent.append(msg))
    page = admin_client.get(f"/polls/{poll.id}/share").get_data(as_text=True)
    assert "people need to sign in" in page
    admin_client.post(f"/polls/{poll.id}/share", data={"person_ids": [str(ann.id)]})
    assert sent and "sign in first" in sent[0].body and f"/poll/{poll.token}" in sent[0].body
    _db.session.delete(poll)
    _db.session.commit()
