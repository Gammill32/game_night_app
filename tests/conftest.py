import os
import unittest.mock
import pytest
from app import create_app
from app.extensions import db as _db
from app.config import Config


class TestConfig(Config):
    TESTING = True
    SESSION_TYPE = "null"
    WTF_CSRF_ENABLED = False


@pytest.fixture(scope="session")
def app():
    """Create a test Flask app using the test PostgreSQL database."""
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    os.environ["FLASK_DEBUG"] = "1"
    os.environ["SECRET_KEY"] = "test-secret-key"

    # Patch APScheduler before create_app() — background threads fire during teardown
    # and hit a closed DB connection, causing noisy errors in CI logs.
    with unittest.mock.patch("app.start_schedulers"):
        application = create_app(TestConfig)

    # Do NOT set SERVER_NAME — it breaks url_for() resolution in tests.
    return application


@pytest.fixture(scope="session")
def db(app):
    """Create all tables for the test session, drop on teardown."""
    with app.app_context():
        _db.create_all()
        yield _db
        _db.drop_all()


@pytest.fixture()
def client(app, db):
    """Flask test client with application context."""
    with app.test_client() as client:
        with app.app_context():
            yield client


@pytest.fixture()
def auth_client(app, db):
    """Test client pre-logged-in as a standard user."""
    from app.models import Person
    from app.extensions import bcrypt

    with app.app_context():
        user = Person(
            first_name="Test",
            last_name="User",
            email="test@example.com",
            password=bcrypt.generate_password_hash("password").decode("utf-8"),
            admin=False,
            owner=False,
        )
        _db.session.add(user)
        _db.session.commit()

        with app.test_client() as client:
            # auth_bp has no url_prefix — login route is /login, not /auth/login
            client.post("/login", data={"email": "test@example.com", "password": "password"})
            yield client

        _db.session.delete(user)
        _db.session.commit()


@pytest.fixture()
def admin_client(app, db):
    """Test client pre-logged-in as an admin user."""
    from app.models import Person
    from app.extensions import bcrypt

    with app.app_context():
        admin = Person(
            first_name="Admin",
            last_name="User",
            email="admin@example.com",
            password=bcrypt.generate_password_hash("password").decode("utf-8"),
            admin=True,
            owner=False,
        )
        _db.session.add(admin)
        _db.session.commit()

        with app.test_client() as client:
            # auth_bp has no url_prefix — login route is /login, not /auth/login
            client.post("/login", data={"email": "admin@example.com", "password": "password"})
            yield client

        _db.session.delete(admin)
        _db.session.commit()


@pytest.fixture(scope="session")
def seed_data(db, app):
    """Minimal seed: one Game, one GameNight for routes with path params."""
    from app.models import Game, GameNight
    import datetime

    with app.app_context():
        game = Game(name="Test Game", bgg_id=1)
        _db.session.add(game)
        _db.session.flush()

        game_night = GameNight(date=datetime.date.today())
        _db.session.add(game_night)
        _db.session.commit()

        yield {"game_id": game.id, "game_night_id": game_night.id}

        _db.session.delete(game_night)
        _db.session.delete(game)
        _db.session.commit()
