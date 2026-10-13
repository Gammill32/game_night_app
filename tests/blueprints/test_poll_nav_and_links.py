"""The nav's open-poll count, and which nights a poll can be linked to."""

import datetime as dt
import logging
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from sqlalchemy import event

from app.extensions import db as _db
from app.models import Poll
from app.services import poll_services
from app.services.poll_services import can_view, create_poll, open_polls_for, poll_is_active
from tests.conftest import login


@contextmanager
def count_queries():
    seen: list[str] = []

    def before(conn, cursor, statement, *args):
        seen.append(statement)

    event.listen(_db.engine, "before_cursor_execute", before)
    try:
        yield seen
    finally:
        event.remove(_db.engine, "before_cursor_execute", before)


def _host(make_person, name="Hana"):
    p = make_person(name)
    p.can_host = True
    _db.session.commit()
    return p


@pytest.fixture()
def made_polls():
    made: list[int] = []
    yield made
    _db.session.rollback()
    for pid in made:
        poll = _db.session.get(Poll, pid)
        if poll is not None:
            _db.session.delete(poll)
    _db.session.commit()


# ── nav count ──────────────────────────────────────────────────────────── #


def test_nav_count_skipped_for_htmx_fragments(client, make_person, monkeypatch):
    calls = []
    monkeypatch.setattr(poll_services, "count_open_polls_for", lambda user: calls.append(user) or 0)
    login(client, _host(make_person))
    assert client.get("/polls/option-row", headers={"HX-Request": "true"}).status_code == 200
    assert calls == []
    assert client.get("/polls/option-row").status_code == 200
    assert len(calls) == 1


def test_nav_count_skipped_when_logged_out(client, monkeypatch):
    calls = []
    monkeypatch.setattr(poll_services, "count_open_polls_for", lambda user: calls.append(user) or 0)
    client.post("/logout")
    assert client.get("/login").status_code == 200
    assert calls == []


def test_nav_count_failure_is_logged_not_raised(client, make_person, monkeypatch, caplog):
    def boom(user):
        raise RuntimeError("db went away")

    monkeypatch.setattr(poll_services, "count_open_polls_for", boom)
    login(client, _host(make_person))
    with caplog.at_level(logging.ERROR):
        resp = client.get("/polls/option-row")
    assert resp.status_code == 200
    assert "db went away" in caplog.text


def test_nav_shows_count_to_hosts_only(client, make_person, made_polls, monkeypatch):
    hana, ann = _host(make_person), make_person("Ann")
    made_polls.append(create_poll("Nav count?", None, ["A", "B"], hana.id, False).id)
    login(client, hana)
    expected = poll_services.count_open_polls_for(hana)
    assert expected >= 1
    page = client.get("/games").get_data(as_text=True)
    assert f"Polls ({expected})" in page

    calls = []
    monkeypatch.setattr(poll_services, "count_open_polls_for", lambda user: calls.append(user) or 0)
    login(client, ann)  # no Polls link in her nav, so nothing to count
    assert client.get("/games").status_code == 200
    assert calls == []


# ── open_polls_for ─────────────────────────────────────────────────────── #


def _user(person, admin=False):
    return SimpleNamespace(is_authenticated=True, id=person.id, admin=admin, owner=False)


def test_open_polls_for_matches_can_view(make_person, make_night, made_polls):
    """Every kind of poll: general, private, linked, hosted, closed, expired."""
    ann, bo, cy, hana = (make_person(n) for n in ("Ann", "Bo", "Cy", "Hana"))
    night = make_night(ann)
    hosted = make_night(bo, host_id=hana.id)
    past = dt.datetime.utcnow() - dt.timedelta(hours=1)
    future = dt.datetime.utcnow() + dt.timedelta(days=1)
    polls = [
        create_poll("general", None, ["A", "B"], cy.id, False),
        create_poll("private", None, ["A", "B"], cy.id, False, private=True, invitee_ids=[bo.id]),
        create_poll("linked", None, ["A", "B"], cy.id, False, game_night_id=night.id),
        create_poll("hosted", None, ["A", "B"], cy.id, False, game_night_id=hosted.id),
        create_poll(
            "private+linked",
            None,
            ["A", "B"],
            cy.id,
            False,
            private=True,
            invitee_ids=[ann.id],
            game_night_id=hosted.id,
        ),
        create_poll("expired", None, ["A", "B"], cy.id, False, closes_at=past),
        create_poll("closes later", None, ["A", "B"], cy.id, False, closes_at=future),
        create_poll("mine", None, ["A", "B"], ann.id, False, private=True),
    ]
    closed = create_poll("closed", None, ["A", "B"], cy.id, False)
    closed.closed = True
    _db.session.commit()
    polls.append(closed)
    made_polls.extend(p.id for p in polls)

    everything = Poll.query.order_by(Poll.created_at.desc()).all()
    for person, admin in ((ann, False), (bo, False), (cy, False), (hana, False), (bo, True)):
        user = _user(person, admin)
        expected = [p.id for p in everything if poll_is_active(p) and can_view(p, user)]
        got = [p.id for p in open_polls_for(user)]
        assert sorted(got) == sorted(expected), (person.first_name, admin)
        assert poll_services.count_open_polls_for(user) == len(expected)


def test_open_polls_for_query_count_does_not_grow(make_person, make_night, made_polls):
    ann, cy = make_person("Ann"), make_person("Cy")

    def add_polls(n):
        for _ in range(n):
            night = make_night(ann)
            made_polls.append(
                create_poll("linked", None, ["A", "B"], cy.id, False, game_night_id=night.id).id
            )
        poll = create_poll("private", None, ["A"], cy.id, False, private=True, invitee_ids=[ann.id])
        made_polls.append(poll.id)

    add_polls(1)
    _db.session.expire_all()
    with count_queries() as few:
        open_polls_for(_user(ann))
    add_polls(5)
    _db.session.expire_all()
    with count_queries() as many:
        open_polls_for(_user(ann))
    assert len(many) == len(few) <= 2


# ── linking a poll to a night ──────────────────────────────────────────── #


def test_host_cannot_link_poll_to_someone_elses_night(client, make_person, make_night, made_polls):
    hana, other = _host(make_person), _host(make_person, "Otto")
    mine, theirs = make_night(host_id=hana.id), make_night(host_id=other.id)
    login(client, hana)

    def create(night_id):
        return client.post(
            "/polls/create",
            data={
                "title": f"Link {night_id}",
                "option_labels": ["A", "B"],
                "game_night_id": night_id,
            },
        )

    assert create(theirs.id).status_code == 400
    assert Poll.query.filter_by(title=f"Link {theirs.id}").count() == 0
    assert create(999_999_999).status_code == 400  # no such night: was an FK 500
    assert create(mine.id).status_code == 302
    poll = Poll.query.filter_by(title=f"Link {mine.id}").one()
    made_polls.append(poll.id)
    assert poll.game_night_id == mine.id

    def edit(night_id):
        return client.post(
            f"/polls/{poll.id}/edit", data={"title": "Edited", "game_night_id": night_id}
        )

    assert edit(theirs.id).status_code == 400
    assert edit(999_999_999).status_code == 400
    _db.session.expire_all()
    assert _db.session.get(Poll, poll.id).game_night_id == mine.id
    assert edit("").status_code == 302  # unlinking is fine
    _db.session.expire_all()
    assert _db.session.get(Poll, poll.id).game_night_id is None


def test_edit_keeps_a_link_the_editor_could_not_make(client, make_person, make_night, made_polls):
    """An admin linked Hana's poll to a finalized night; Hana can still save her poll."""
    hana = _host(make_person)
    final_night = make_night(final=True)
    poll = create_poll("Old link", None, ["A", "B"], hana.id, False, game_night_id=final_night.id)
    made_polls.append(poll.id)
    login(client, hana)
    resp = client.post(
        f"/polls/{poll.id}/edit", data={"title": "Still linked", "game_night_id": final_night.id}
    )
    assert resp.status_code == 302
    _db.session.expire_all()
    assert _db.session.get(Poll, poll.id).game_night_id == final_night.id
