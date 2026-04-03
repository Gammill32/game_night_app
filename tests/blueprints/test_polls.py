import uuid

import pytest

from app.extensions import db as _db
from app.models import Person, Poll
from app.services.poll_services import create_poll


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
