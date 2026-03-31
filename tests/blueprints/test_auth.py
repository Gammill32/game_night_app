# tests/blueprints/test_auth.py
import pytest

from app.extensions import db as _db


@pytest.fixture()
def registered_user(app, db):
    """A committed Person with a known password for login tests."""
    from app.extensions import bcrypt
    from app.models import Person

    _db.session.rollback()
    Person.query.filter_by(email="authtest@example.com").delete()
    _db.session.commit()

    user = Person(
        first_name="Auth",
        last_name="Tester",
        email="authtest@example.com",
        password=bcrypt.generate_password_hash("secret123", rounds=4).decode("utf-8"),
        admin=False,
        owner=False,
    )
    _db.session.add(user)
    _db.session.commit()
    yield user

    _db.session.rollback()
    Person.query.filter_by(email="authtest@example.com").delete()
    _db.session.commit()


def test_login_post_valid_credentials(client, registered_user):
    resp = client.post(
        "/login",
        data={"email": "authtest@example.com", "password": "secret123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def test_login_post_invalid_password(client, registered_user):
    resp = client.post(
        "/login",
        data={"email": "authtest@example.com", "password": "wrong"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert (
        b"error" in resp.data.lower()
        or b"invalid" in resp.data.lower()
        or b"incorrect" in resp.data.lower()
    )


def test_login_post_unknown_email(client, db):
    resp = client.post(
        "/login",
        data={"email": "nobody@example.com", "password": "whatever"},
        follow_redirects=False,
    )
    assert resp.status_code == 200


def test_logout_redirects(auth_client):
    resp = auth_client.post("/logout", follow_redirects=False)
    assert resp.status_code == 302


def test_signup_post_creates_user(client, db):
    from app.models import Person

    resp = client.post(
        "/signup",
        data={
            "first_name": "New",
            "last_name": "User",
            "email": "newuser_smoke@example.com",
            "password": "password123",
        },
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302)
    # Clean up
    _db.session.rollback()
    Person.query.filter_by(email="newuser_smoke@example.com").delete()
    _db.session.commit()


def test_signup_post_duplicate_email(client, registered_user):
    resp = client.post(
        "/signup",
        data={
            "first_name": "Dup",
            "last_name": "User",
            "email": "authtest@example.com",
            "password": "password123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200


def test_admin_page_requires_admin(auth_client):
    """Non-admin user should be redirected or forbidden from /admin."""
    resp = auth_client.get("/admin", follow_redirects=False)
    assert resp.status_code in (302, 403)


def test_admin_page_loads_for_admin(admin_client):
    resp = admin_client.get("/admin")
    assert resp.status_code == 200


def test_add_person_page_loads_for_admin(admin_client):
    resp = admin_client.get("/add_person")
    assert resp.status_code == 200


def test_add_person_post(admin_client):
    resp = admin_client.post(
        "/add_person",
        data={"first_name": "Added", "last_name": "Person"},
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302)
