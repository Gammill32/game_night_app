import os
import tempfile
import unittest.mock

import pytest
from flask_sqlalchemy.session import Session as FsaSession
from sqlalchemy import orm as sa_orm

from app import create_app
from app.config import Config
from app.extensions import db as _db


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret-key"
    WTF_CSRF_ENABLED = False
    # Flask-Login 0.6.x caches _login_user in Flask's g (app-context-scoped).
    # Our session-scoped db fixture holds one AppContext open, so test client
    # requests reuse it. Without LOGIN_DISABLED=False, @login_required is
    # bypassed entirely because Flask-Login reads TESTING=True and skips it.
    LOGIN_DISABLED = False
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL")
    BCRYPT_LOG_ROUNDS = 4  # fast hashing in tests
    AUTH_THROTTLE = False  # the suite logs in many times; throttle tests turn it on
    MEDIA_DIR = tempfile.mkdtemp(prefix="gamenight_media_")
    MAIL_DEFAULT_SENDER = "gamenight@test.invalid"  # CI has no .env; share emails need a sender


@pytest.fixture(scope="session")
def app():
    """Create a test Flask app using the test PostgreSQL database."""
    from app.extensions import sess

    # Disable Flask-Session so Flask uses built-in cookie sessions (no file I/O).
    # Patch APScheduler to prevent background threads firing against a closed DB.
    with unittest.mock.patch("app.start_schedulers"), unittest.mock.patch.object(sess, "init_app"):
        application = create_app(TestConfig)

    # Do NOT set SERVER_NAME — it breaks url_for() resolution in tests.
    return application


@pytest.fixture(scope="session")
def db(app):
    """Run all migrations (tables + views) for the test session."""
    from flask_migrate import upgrade

    with app.app_context():
        upgrade()
        yield _db
        _db.session.remove()
        _db.engine.dispose()


class _ConnectionBoundSession(FsaSession):
    """Flask-SQLAlchemy's Session.get_bind() picks an engine from db.engines and
    never looks at Session.bind, so passing bind=connection alone would be ignored
    and every query would check out a fresh pooled connection outside the test's
    transaction. Route everything through the bound connection instead."""

    def get_bind(self, mapper=None, clause=None, bind=None, **kwargs):  # type: ignore[override]
        return bind if bind is not None else self.bind


class _OneSessionPerTest(sa_orm.scoped_session):
    """db.session for one test: the same Session in every app context and thread.

    Flask-SQLAlchemy scopes db.session to the app context and removes it when a
    context is torn down. Many tests open nested `with app.app_context():`
    blocks (and one runs the app in a thread); with a session per context, two
    Sessions would share the test connection and interleave their savepoints
    (one's ROLLBACK TO SAVEPOINT destroys the other's), and tearing an inner
    context down would close objects the test still holds. So every context gets
    this one Session, and remove() waits for the end of the test.
    """

    def remove(self) -> None:
        pass

    def remove_for_real(self) -> None:
        super().remove()


@pytest.fixture(autouse=True)
def _rollback_after_test(request, db):
    """Run each test inside one outer transaction that is rolled back afterwards.

    SQLAlchemy 2.0's recipe "Joining a Session into an External Transaction (such
    as for test suites)": begin a transaction on a Connection, bind the Session
    to that connection with join_transaction_mode="create_savepoint", and roll
    the outer transaction back at the end. The Session then runs its own
    begin/commit/rollback as SAVEPOINT / RELEASE / ROLLBACK TO SAVEPOINT, so
    app code and tests commit and roll back as before (rollback() goes back to
    the last commit), begin_nested() nests further savepoints, and nothing a
    test writes - even if it fails before its own cleanup - outlives it.

    db.session is an attribute that everything (Model.query, app code, tests)
    looks up on each use, so swapping it for the test and restoring it
    afterwards is enough. The Session comes from Flask-SQLAlchemy's own factory
    (same class family, query class and db), with two changes: a get_bind() that
    honours bind= (_ConnectionBoundSession) and one Session for the whole test
    (_OneSessionPerTest).

    Tests marked real_commits opt out and commit for real (and clean up by hand):
    they let a second connection see their rows, which uncommitted data in this
    outer transaction can't do.

    Server-side now() is the transaction's start time, so it stays fixed for the
    whole test; nothing should rely on it advancing between commits.
    """
    if request.node.get_closest_marker("real_commits"):
        yield
        return

    connection = _db.engine.connect()
    outer = connection.begin()
    factory = _db._make_session_factory(
        {
            "bind": connection,
            "join_transaction_mode": "create_savepoint",
            "class_": _ConnectionBoundSession,
        }
    )
    test_session = _OneSessionPerTest(factory, scopefunc=lambda: None)
    real_session = _db.session
    _db.session = test_session
    try:
        yield
    finally:
        test_session.remove_for_real()
        _db.session = real_session
        outer.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def _clear_flask_login_cache(db):
    """Clear Flask-Login's g-cached user before each test.

    Flask-Login 0.6.x caches _login_user in g, which is tied to the AppContext.
    Our session-scoped db fixture holds one AppContext open for the whole session,
    so test client requests reuse it and see stale _login_user from previous tests.
    Clearing it forces _load_user() to re-check the session on each test's first
    request, giving each test a clean auth slate.
    """
    from flask import g

    g.pop("_login_user", None)
    yield
    g.pop("_login_user", None)


@pytest.fixture()
def client(app, db):
    """Flask test client — no nested app_context (session-scoped db already holds one)."""
    with app.test_client() as client:
        yield client


@pytest.fixture()
def auth_client(app, db):
    """Test client pre-logged-in as a standard user."""
    from app.extensions import bcrypt
    from app.models import Person, PollResponse

    def _cleanup():
        _db.session.rollback()
        existing = Person.query.filter_by(email="test@example.com").first()
        if existing:
            # Bulk .delete() bypasses FK cascades; remove dependent rows first.
            PollResponse.query.filter_by(person_id=existing.id).delete()
            _db.session.flush()
            _db.session.delete(existing)
            _db.session.commit()

    _cleanup()

    user = Person(
        first_name="Test",
        last_name="User",
        email="test@example.com",
        password=bcrypt.generate_password_hash("password", rounds=4).decode("utf-8"),
        admin=False,
        owner=False,
    )
    _db.session.add(user)
    _db.session.commit()

    with app.test_client() as client:
        client.post("/login", data={"email": "test@example.com", "password": "password"})
        yield client

    _cleanup()


@pytest.fixture()
def admin_client(app, db):
    """Test client pre-logged-in as an admin user."""
    from app.extensions import bcrypt
    from app.models import Person, Poll

    _db.session.rollback()
    # Must delete polls (and their cascade children) before deleting the person.
    # Bulk .delete() bypasses ORM cascade; load and session.delete() triggers it.
    existing = Person.query.filter_by(email="admin@example.com").first()
    if existing:
        for poll in Poll.query.filter_by(created_by=existing.id).all():
            _db.session.delete(poll)
        _db.session.flush()
        _db.session.delete(existing)
        _db.session.commit()

    admin = Person(
        first_name="Admin",
        last_name="User",
        email="admin@example.com",
        password=bcrypt.generate_password_hash("password", rounds=4).decode("utf-8"),
        admin=True,
        owner=False,
    )
    _db.session.add(admin)
    _db.session.commit()

    with app.test_client() as client:
        client.post("/login", data={"email": "admin@example.com", "password": "password"})
        yield client

    _db.session.rollback()
    existing = Person.query.filter_by(email="admin@example.com").first()
    if existing:
        for poll in Poll.query.filter_by(created_by=existing.id).all():
            _db.session.delete(poll)
        _db.session.flush()
        _db.session.delete(existing)
        _db.session.commit()


@pytest.fixture(scope="session")
def seed_data(db, app):
    """Minimal seed: one Game, one GameNight for routes with path params."""
    import datetime

    from app.models import Game, GameNight

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


@pytest.fixture()
def make_person(app, db):
    """Create throwaway people (unique emails); deleted, with their dependents, afterwards."""
    import uuid

    from app.extensions import bcrypt
    from app.models import Person

    made = []

    def _make(first="Pat", last="Test", admin=False, password="password"):
        person = Person(
            first_name=first,
            last_name=last,
            email=f"{first.lower()}_{uuid.uuid4().hex[:8]}@test.invalid",
            password=bcrypt.generate_password_hash(password, rounds=4).decode("utf-8"),
            admin=admin,
        )
        _db.session.add(person)
        _db.session.commit()
        made.append(person.id)
        return person

    yield _make

    _db.session.rollback()
    for pid in made:
        person = _db.session.get(Person, pid)
        if person is not None:
            _db.session.delete(person)
    _db.session.commit()


def login(client, person, password="password"):
    client.post("/logout")
    client.post("/login", data={"email": person.email, "password": password})


@pytest.fixture()
def make_night(app, db):
    """Create game nights with the given people as players; deleted afterwards."""
    import datetime

    from app.models import GameNight, Player

    made = []

    def _make(*people, date=None, **fields):
        gn = GameNight(date=date or datetime.date.today(), **fields)
        _db.session.add(gn)
        _db.session.flush()
        _db.session.add_all([Player(game_night_id=gn.id, people_id=p.id) for p in people])
        _db.session.commit()
        made.append(gn.id)
        return gn

    yield _make

    _db.session.rollback()
    for gid in made:
        gn = _db.session.get(GameNight, gid)
        if gn is not None:
            from app.models import PersonBadge

            PersonBadge.query.filter_by(game_night_id=gid).delete()  # finalizing awards badges
            for poll in gn.polls:
                _db.session.delete(poll)
            _db.session.delete(gn)
    _db.session.commit()
