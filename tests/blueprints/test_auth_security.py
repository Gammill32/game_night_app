# tests/blueprints/test_auth_security.py
"""Login redirects, password policy, reset tokens, sessions, throttling, invites."""

import pytest

from tests.conftest import login


@pytest.mark.parametrize(
    "next_url",
    [
        "/\\evil.com",
        "\\\\evil.com",
        "/\\/evil.com",
        "//evil.com",
        "https://evil.com",
        "javascript:alert(1)",
        "http:/evil.com",
    ],
)
def test_login_rejects_offsite_next(client, make_person, next_url):
    ann = make_person("Ann")
    resp = client.post(
        "/login",
        query_string={"next": next_url},
        data={"email": ann.email, "password": "password"},
    )
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/"


def test_login_keeps_local_next(client, make_person):
    ann = make_person("Ann")
    resp = client.post(
        "/login",
        query_string={"next": "/games?sort=name"},
        data={"email": ann.email, "password": "password"},
    )
    assert resp.headers["Location"] == "/games?sort=name"


@pytest.mark.parametrize("data", [{"email": "x@test.invalid"}, {}, {"password": "pw"}])
def test_login_with_missing_fields_is_a_friendly_error(client, make_person, data):
    ann = make_person("Ann")
    data = {k: (ann.email if k == "email" else v) for k, v in data.items()}
    resp = client.post("/login", data=data)
    assert resp.status_code == 200
    assert b"Enter your email and password." in resp.data


def test_password_policy_is_shared():
    from app.services.auth_services import password_problem

    assert password_problem(None) and password_problem("") and password_problem("seven77")
    assert password_problem("é" * 37)  # 74 bytes: bcrypt refuses more than 72
    assert password_problem("eight888") is None


def test_update_password_enforces_policy(client, make_person):
    ann = make_person("Ann")
    login(client, ann)
    old = ann.password
    resp = client.post(
        "/update_password",
        data={"current_password": "password", "new_password": "short", "confirm_password": "short"},
    )
    assert b"at least 8 characters" in resp.data
    assert ann.password == old


def test_profile_enforces_policy(client, make_person):
    ann = make_person("Ann")
    login(client, ann)
    old = ann.password
    resp = client.post(
        "/manage_user",
        data={
            "current_password": "password",
            "email": ann.email,
            "new_password": "x" * 80,
            "confirm_password": "x" * 80,
        },
        follow_redirects=True,
    )
    assert b"too long" in resp.data
    assert ann.password == old


def test_signup_enforces_policy(make_stub):
    from app.services import auth_services

    invite = auth_services.make_invite_token(
        make_stub("Shorty", "Pw"), make_stub("Ad", "Min", admin=True)
    )
    ok, message = auth_services.signup("shorty@test.invalid", "abc", invite=invite)
    assert not ok and "at least 8 characters" in message


def test_reset_token_does_not_carry_the_password_hash(make_person):
    from itsdangerous import URLSafeTimedSerializer

    from app.services import auth_services

    ann = make_person("Ann")
    token = auth_services.make_reset_token(ann)
    payload = URLSafeTimedSerializer("x").loads_unsafe(token)[1]
    assert ann.password[-12:] not in str(payload)
    assert auth_services.user_for_reset_token(token) == ann
    ann.password = auth_services.hash_password("another-password")
    assert auth_services.user_for_reset_token(token) is None


def _fresh_request():
    from flask import g

    g.pop("_login_user", None)  # the suite shares one app context; see conftest


def _logged_in(client):
    _fresh_request()
    return client.get("/manage_user").status_code == 200


@pytest.mark.parametrize("route", ["/update_password", "/manage_user"])
def test_changing_password_logs_out_other_sessions(app, make_person, route):
    ann = make_person("Ann")
    here, there = app.test_client(), app.test_client()
    login(here, ann)
    login(there, ann)
    assert _logged_in(here) and _logged_in(there)
    data = {
        "current_password": "password",
        "new_password": "new-password-1",
        "confirm_password": "new-password-1",
        "email": ann.email,
    }
    _fresh_request()
    here.post(route, data=data)
    assert _logged_in(here)
    assert not _logged_in(there)


def test_reset_and_deactivation_log_out_sessions(app, make_person, make_night):
    from app.services import admin_services, auth_services

    ann, adm = make_person("Ann"), make_person("Adm", admin=True)
    make_night(ann)
    c = app.test_client()
    login(c, ann)
    auth_services.reset_password(ann, "reset-password", "reset-password")
    assert not _logged_in(c)
    login(c, ann, "reset-password")
    assert _logged_in(c)
    admin_services.remove_user(ann.id, adm.id)
    admin_services.restore_user(ann.id)
    assert not _logged_in(c)


def test_sessions_from_before_tokens_still_work_until_a_change(app, make_person):
    """Sessions holding the bare id (from before this change) stay valid
    until the person's token is first set."""
    from app.extensions import db

    ann = make_person("Ann")
    assert ann.session_token is None and ann.get_id() == str(ann.id)
    c = app.test_client()
    with c.session_transaction() as sess:
        sess["_user_id"] = str(ann.id)
        sess["_fresh"] = True
    assert _logged_in(c)
    ann.rotate_session_token()
    db.session.commit()
    assert not _logged_in(c)


@pytest.fixture()
def throttled(app, db):
    from app.models import AuthThrottle

    AuthThrottle.query.delete()
    db.session.commit()
    app.config["AUTH_THROTTLE"] = True
    yield
    app.config["AUTH_THROTTLE"] = False
    db.session.rollback()
    AuthThrottle.query.delete()
    db.session.commit()


def test_login_is_throttled_per_email(client, make_person, throttled):
    from app.services import auth_services

    ann = make_person("Ann")
    for _ in range(auth_services.LOGIN_EMAIL_LIMIT):
        resp = client.post("/login", data={"email": ann.email, "password": "wrong-guess"})
        assert b"Invalid email or password." in resp.data
    resp = client.post("/login", data={"email": ann.email, "password": "password"})
    assert resp.status_code == 429 and b"Too many sign-in attempts" in resp.data


def test_guessing_from_one_address_doesnt_lock_the_owner_out_elsewhere(
    client, make_person, throttled
):
    from app.services import auth_services

    ann = make_person("Ann")
    attacker = {"REMOTE_ADDR": "203.0.113.9"}
    for _ in range(auth_services.LOGIN_EMAIL_LIMIT + 2):
        client.post("/login", data={"email": ann.email, "password": "wrong"}, environ_base=attacker)
    resp = client.post(
        "/login",
        data={"email": ann.email, "password": "password"},
        environ_base={"REMOTE_ADDR": "198.51.100.7"},
    )
    assert resp.status_code == 302


def test_an_old_temporary_password_no_longer_signs_in(client, make_person):
    from app.extensions import db as _db

    ann = make_person("Ann")
    ann.temp_pass = True
    _db.session.commit()
    resp = client.post("/login", data={"email": ann.email, "password": "password"})
    assert resp.status_code == 200 and b"temporary password" in resp.data


def test_login_is_throttled_per_address(client, make_person, throttled, monkeypatch):
    from app.services import auth_services

    monkeypatch.setattr(auth_services, "LOGIN_IP_LIMIT", 3)
    for n in range(3):
        client.post("/login", data={"email": f"nobody{n}@test.invalid", "password": "x"})
    ann = make_person("Ann")
    resp = client.post("/login", data={"email": ann.email, "password": "password"})
    assert resp.status_code == 429


def test_forgot_password_is_throttled_and_answers_the_same(
    client, make_person, throttled, monkeypatch
):
    from markupsafe import escape

    from app.services import auth_services

    ann = make_person("Ann")
    sent = []
    monkeypatch.setattr(auth_services, "send_email", lambda to, subj, body: sent.append(to))
    answers = set()
    for _ in range(auth_services.FORGOT_EMAIL_LIMIT + 2):
        resp = client.post("/forgot_password", data={"email": ann.email}, follow_redirects=True)
        answers.add(str(escape(auth_services.FORGOT_MESSAGE)) in resp.get_data(as_text=True))
    resp = client.post(
        "/forgot_password", data={"email": "nobody@test.invalid"}, follow_redirects=True
    )
    answers.add(str(escape(auth_services.FORGOT_MESSAGE)) in resp.get_data(as_text=True))
    assert answers == {True}
    assert len(sent) == auth_services.FORGOT_EMAIL_LIMIT


# --- Invite links --------------------------------------------------------------


@pytest.fixture()
def make_stub(db):
    """Unclaimed people (name only, as Add Person / quick add make them)."""
    from app.models import Person

    made = []

    def _make(first, last, **fields):
        person = Person(first_name=first, last_name=last, **fields)
        db.session.add(person)
        db.session.commit()
        made.append(person.id)
        return person

    yield _make
    db.session.rollback()
    for pid in made:
        person = db.session.get(Person, pid)
        if person is not None:
            db.session.delete(person)
    db.session.commit()


def _signup(client, invite=None, **fields):
    data = {
        "first_name": "Someone",
        "last_name": "Else",
        "email": "someone.else@test.invalid",
        "password": "good-password",
    }
    data.update(fields)
    if invite:
        data["invite"] = invite
    return client.post("/signup", data=data, follow_redirects=True)


def _cleanup_email(db, email):
    from app.models import Person

    db.session.rollback()
    for person in Person.query.filter_by(email=email).all():
        db.session.delete(person)
    db.session.commit()


def test_signup_by_name_never_claims_an_existing_person(client, db, make_stub):
    stub = make_stub("Claimable", "Admin", admin=True)
    resp = _signup(client, first_name="claimable", last_name="ADMIN")
    assert b"invite link" in resp.data
    assert stub.email is None and stub.password is None
    from app.models import Person

    assert Person.query.filter_by(email="someone.else@test.invalid").count() == 0


def test_signup_without_invite_creates_nobody(client, db):
    from app.models import Person

    try:
        resp = _signup(client, first_name="Brand", last_name="Newcomer")
        assert b"Sign-up is by invite" in resp.data
        assert Person.query.filter_by(email="someone.else@test.invalid").count() == 0
        assert Person.query.filter_by(first_name="Brand", last_name="Newcomer").count() == 0
    finally:
        _cleanup_email(db, "someone.else@test.invalid")


def test_signup_page_without_invite_shows_no_form(client, db):
    resp = client.get("/signup")
    assert b"Sign-up is by invite" in resp.data
    assert b'name="password"' not in resp.data


def _invite_from(page):
    import re

    match = re.search(r'value="(http://localhost/signup\?invite=[^"]+)"', page)
    assert match, "no invite link on the page"
    return match.group(1).split("invite=", 1)[1]


def test_invite_link_claims_that_person_with_their_rights(admin_client, db, make_stub):
    stub = make_stub("Invited", "Admin", admin=True, can_host=True)
    token = _invite_from(admin_client.get("/admin").get_data(as_text=True))
    admin_client.post("/logout")
    client = admin_client
    try:
        page = client.get(f"/signup?invite={token}").get_data(as_text=True)
        assert "invited as <strong>Invited Admin</strong>" in page

        resp = _signup(client, invite=token, first_name="Not", last_name="Me")
        assert b"You can now log in" in resp.data
        db.session.refresh(stub)
        assert stub.email == "someone.else@test.invalid"
        assert (stub.first_name, stub.admin, stub.can_host) == ("Invited", True, True)

        # Used up: the person is claimed now
        resp = client.get(f"/signup?invite={token}", follow_redirects=True)
        assert b"expired or was already used" in resp.data
        resp = _signup(client, invite=token, email="second@test.invalid")
        assert b"expired or was already used" in resp.data
    finally:
        _cleanup_email(db, "someone.else@test.invalid")


def test_invite_links_expire_and_cannot_be_forged(client, db, make_stub, make_person, monkeypatch):
    from app.services import auth_services

    stub = make_stub("Expiring", "Invite")
    token = auth_services.make_invite_token(stub, make_person("Adm", admin=True))
    assert auth_services.person_for_invite(token) == stub
    assert auth_services.person_for_invite(token[:-2] + "xx") is None
    assert auth_services.person_for_invite("garbage") is None
    monkeypatch.setattr(auth_services, "INVITE_MAX_AGE", -1)
    assert auth_services.person_for_invite(token) is None


def test_deactivating_someone_voids_their_old_invite(db, make_stub, make_person, make_night):
    from app.services import admin_services, auth_services

    stub, adm = make_stub("Gone", "ForNow"), make_person("Adm", admin=True)
    make_night(stub)
    token = auth_services.make_invite_token(stub, adm)
    admin_services.remove_user(stub.id, adm.id)
    admin_services.restore_user(stub.id)
    assert auth_services.person_for_invite(token) is None
    assert auth_services.person_for_invite(auth_services.make_invite_token(stub, adm)) == stub


def test_who_can_invite(db, make_stub, make_person, make_night):
    from app.services.auth_services import can_invite

    adm, member = make_person("Adm", admin=True), make_person("Mem")
    host = make_person("Hoster")
    host.can_host = True
    guest, stranger = make_stub("Guest", "OfHost"), make_stub("Not", "TheirGuest")
    vip = make_stub("Made", "Admin", admin=True)
    regular = make_stub("Plays", "Everywhere")
    make_night(guest, vip, regular, host_id=host.id)
    make_night(stranger, regular)

    assert can_invite(adm, guest) and can_invite(adm, stranger) and can_invite(adm, vip)
    assert can_invite(host, guest)
    assert not can_invite(host, stranger)  # not on a night they host
    assert not can_invite(host, vip)  # admin rights come from an admin's link only
    assert not can_invite(host, regular)  # has history at other nights: not just their guest
    assert not can_invite(member, guest)
    assert not can_invite(adm, member)  # already signed up


def test_hosts_get_invite_links_for_their_guests(client, db, make_stub, make_person, make_night):
    host = make_person("Hoster")
    host.can_host = True
    guest, stranger = make_stub("Guest", "OfHost"), make_stub("Not", "TheirGuest")
    make_night(guest, host_id=host.id)
    make_night(stranger)
    login(client, host)
    page = client.get("/invites").get_data(as_text=True)
    assert "Guest OfHost" in page and "TheirGuest" not in page
    from app.services.auth_services import person_for_invite

    assert person_for_invite(_invite_from(page)) == guest

    member = make_person("Mem")
    login(client, member)
    assert client.get("/invites").status_code == 302


def test_a_hosts_old_link_dies_when_an_admin_gives_the_guest_rights(
    db, make_stub, make_person, make_night
):
    from app.services import auth_services

    host = make_person("Hoster")
    host.can_host = True
    guest = make_stub("Guest", "Promoted")
    make_night(guest, host_id=host.id)
    token = auth_services.make_invite_token(guest, host)
    assert auth_services.person_for_invite(token) == guest
    guest.admin = True  # an admin promotes them before they sign up
    db.session.commit()
    assert auth_services.person_for_invite(token) is None


def test_a_link_dies_when_its_maker_loses_hosting(db, make_stub, make_person, make_night):
    from app.services import auth_services

    host = make_person("Hoster")
    host.can_host = True
    guest = make_stub("Guest", "Orphan")
    make_night(guest, host_id=host.id)
    token = auth_services.make_invite_token(guest, host)
    host.can_host = False
    db.session.commit()
    assert auth_services.person_for_invite(token) is None
