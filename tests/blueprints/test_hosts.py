"""Night hosts: people with 'Can host' start and run their own nights."""

import datetime as dt

from app.extensions import db as _db
from app.models import GameNight, Person, Poll
from tests.conftest import login


def _host(make_person, name="Hana"):
    p = make_person(name)
    p.can_host = True
    _db.session.commit()
    return p


def test_member_without_can_host_cannot_start(client, make_person):
    ann = make_person("Ann")
    login(client, ann)
    resp = client.get("/game_night/start")
    assert resp.status_code == 302 and "/game_night/start" not in resp.headers["Location"]
    assert "New game night" not in client.get("/").get_data(as_text=True)


def test_host_starts_and_runs_their_night_but_not_others(client, make_person, make_night):
    hana, bo = _host(make_person), make_person("Bo")
    login(client, hana)
    assert "+ New game night" in client.get("/").get_data(as_text=True)
    resp = client.post(
        "/game_night/start",
        data={"date": "2031-11-07", "attendees": [str(bo.id)], "food_mode": "none"},
    )
    gn = GameNight.query.filter_by(date=dt.date(2031, 11, 7)).order_by(GameNight.id.desc()).first()
    assert gn.host_id == hana.id and resp.headers["Location"].endswith(f"/game_night/{gn.id}")

    # Hana isn't playing, but it's her night: she sees it and runs it
    page = client.get(f"/game_night/{gn.id}").get_data(as_text=True)
    assert "Hosted by" in page and "Finalize results" in page and "+ Add a game" in page
    assert "You&#39;re hosting" in client.get("/").get_data(
        as_text=True
    ) or "You're hosting" in client.get("/").get_data(as_text=True)
    assert client.get(f"/game_night/{gn.id}/edit").status_code == 200
    client.post(f"/game_night/{gn.id}/toggle/closed")
    _db.session.refresh(gn)
    assert gn.closed

    # Someone else's night: no admin controls, and the routes refuse
    other = make_night(hana, date=dt.date(2031, 11, 14))
    page = client.get(f"/game_night/{other.id}").get_data(as_text=True)
    assert "Finalize results" not in page
    resp = client.post(f"/game_night/{other.id}/toggle/closed")
    _db.session.refresh(other)
    assert not other.closed and "/game_night/" in resp.headers["Location"]
    assert client.get(f"/game_night/{other.id}/edit").status_code == 302

    _db.session.delete(gn)
    _db.session.commit()


def test_admin_can_make_anyone_host_of_a_night(admin_client, client, make_person, make_night):
    bo = make_person("Bo")  # no Can host switch
    gn = make_night(bo, date=dt.date(2031, 11, 21))
    admin_client.post(
        f"/game_night/{gn.id}/edit",
        data={
            "date": "2031-11-21",
            "attendees": [str(bo.id)],
            "food_mode": "none",
            "host_id": str(bo.id),
        },
    )
    _db.session.refresh(gn)
    assert gn.host_id == bo.id
    from flask import g

    g.pop("_login_user", None)
    login(client, bo)
    assert "Finalize results" in client.get(f"/game_night/{gn.id}").get_data(as_text=True)
    assert client.get("/game_night/start").status_code == 302  # still can't start new ones


def test_only_owner_promotes_admins_can_toggle_hosting(admin_client, make_person):
    bo = make_person("Bo")
    admin_client.post(f"/toggle_admin_status/{bo.id}")
    _db.session.refresh(bo)
    assert not bo.admin  # admins can't promote
    page = admin_client.get("/admin").get_data(as_text=True)
    assert "Promote" not in page and "can host" in page
    admin_client.post(f"/toggle_can_host/{bo.id}")
    _db.session.refresh(bo)
    assert bo.can_host


def test_quick_add_person_from_picker(client, make_person):
    hana = _host(make_person)
    login(client, hana)
    resp = client.post("/people/quick_add", data={"first_name": "Newt", "last_name": "Quickadd"})
    assert resp.status_code == 200
    person = _db.session.get(Person, resp.get_json()["id"])
    assert person.first_name == "Newt" and person.email is None
    again = client.post("/people/quick_add", data={"first_name": "newt", "last_name": "QUICKADD"})
    assert again.get_json()["id"] == person.id  # already here: just pick them
    assert (
        client.post("/people/quick_add", data={"first_name": "", "last_name": "X"}).status_code
        == 400
    )
    _db.session.delete(person)
    _db.session.commit()


def test_hosts_manage_their_own_polls_only(client, make_person):
    from app.services.poll_services import create_poll

    hana, stranger = _host(make_person), make_person("Str")
    mine = create_poll("Hana's poll", None, ["A", "B"], hana.id, False)
    theirs = create_poll("Someone else's", None, ["A", "B"], stranger.id, False)
    login(client, hana)
    listing = client.get("/polls/").get_data(as_text=True)
    assert "Hana&#39;s poll" in listing or "Hana's poll" in listing
    assert "Someone else" not in listing
    assert client.get(f"/polls/{mine.id}/results").status_code == 200
    assert client.get(f"/polls/{theirs.id}/results").status_code == 404
    for poll in (mine, theirs):
        _db.session.delete(_db.session.get(Poll, poll.id))
    _db.session.commit()


def test_reminder_signed_by_host(app, make_person, make_night, monkeypatch):
    import pytz

    from app.services import reminders_services

    hana, bo = _host(make_person), make_person("Bo")
    today = dt.datetime.now(pytz.timezone(app.config["APP_TIMEZONE"])).date()
    gn = make_night(bo, date=today)
    gn.host_id = hana.id
    _db.session.commit()
    sent = {}
    monkeypatch.setattr(reminders_services, "send_email", lambda to, s, b: sent.__setitem__(to, b))
    reminders_services.check_and_send_reminders()
    assert '<strong style="color: #000000;">Hana</strong>' in sent[bo.email]
    assert "Stephen Gammill" not in sent[bo.email]


def test_start_form_preselects_whoever_starts_it(client, make_person):
    hana = _host(make_person)
    login(client, hana)
    page = client.get("/game_night/start").get_data(as_text=True)
    assert f"const selected = new Set([{hana.id}])" in page
