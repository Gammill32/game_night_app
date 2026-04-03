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
    assert b"Invalid email or password." in resp.data


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
    """Signup for a pre-created nameless person sets email+password and redirects."""
    from app.models import Person

    # Pre-create the person (as admin would do)
    stub = Person(first_name="New", last_name="Signup")
    _db.session.add(stub)
    _db.session.commit()

    resp = client.post(
        "/signup",
        data={
            "first_name": "New",
            "last_name": "Signup",
            "email": "newsignup@example.com",
            "password": "password123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    person = Person.query.filter_by(email="newsignup@example.com").first()
    assert person is not None
    assert person.temp_pass is False

    _db.session.rollback()
    Person.query.filter_by(email="newsignup@example.com").delete()
    Person.query.filter_by(first_name="New", last_name="Signup", email=None).delete()
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


def test_add_person_post(admin_client, db):
    from app.models import Person

    resp = admin_client.post(
        "/add_person",
        data={"first_name": "Added", "last_name": "PersonQA"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    person = Person.query.filter_by(first_name="Added", last_name="PersonQA").first()
    assert person is not None
    _db.session.delete(person)
    _db.session.commit()


def test_update_password_success(auth_client, db):
    """update_password clears temp_pass and accepts new credentials."""
    from app.extensions import bcrypt
    from app.models import Person

    user = Person.query.filter_by(email="test@example.com").first()
    user.temp_pass = True
    _db.session.commit()

    resp = auth_client.post(
        "/update_password",
        data={
            "current_password": "password",
            "new_password": "newpass123",
            "confirm_password": "newpass123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302

    _db.session.refresh(user)
    assert user.temp_pass is False
    assert bcrypt.check_password_hash(user.password, "newpass123")

    # restore original password so auth_client teardown works
    user.password = bcrypt.generate_password_hash("password", rounds=4).decode()
    _db.session.commit()


def test_update_password_wrong_current(auth_client):
    resp = auth_client.post(
        "/update_password",
        data={
            "current_password": "wrongpassword",
            "new_password": "newpass123",
            "confirm_password": "newpass123",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"Current password is incorrect." in resp.data


def test_update_password_mismatch(auth_client):
    resp = auth_client.post(
        "/update_password",
        data={
            "current_password": "password",
            "new_password": "newpass123",
            "confirm_password": "different456",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert b"New passwords do not match." in resp.data


def test_login_redirects_to_update_password_with_temp_pass(client, db):
    """A user with temp_pass=True is redirected to update_password after login."""
    from app.extensions import bcrypt
    from app.models import Person

    temp_user = Person(
        first_name="Temp",
        last_name="Pass",
        email="temppass@example.com",
        password=bcrypt.generate_password_hash("tempword", rounds=4).decode(),
        temp_pass=True,
    )
    _db.session.add(temp_user)
    _db.session.commit()

    try:
        resp = client.post(
            "/login",
            data={"email": "temppass@example.com", "password": "tempword"},
            follow_redirects=False,
        )
        assert resp.status_code == 302
        assert "/update_password" in resp.headers["Location"]
    finally:
        _db.session.rollback()
        Person.query.filter_by(email="temppass@example.com").delete()
        _db.session.commit()


def test_open_redirect_blocked(client, registered_user):
    """Login should not redirect to external URLs via the `next` param."""
    resp = client.post(
        "/login?next=https://evil.com/phish",
        data={"email": "authtest@example.com", "password": "secret123"},
        follow_redirects=False,
    )
    assert resp.status_code == 302
    location = resp.headers.get("Location", "")
    assert "evil.com" not in location
