# Phase 3: Poll / Availability System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a poll/availability system — admins create polls with shareable token-based URLs, anyone with the link can respond without logging in, results are shown after submission. Active polls are surfaced on the dashboard and in the nav.

**Architecture:** New `polls_bp` blueprint in `app/blueprints/polls.py` owns all poll routes (admin management gated with `@admin_required`, public `/poll/<token>` without auth). Poll service logic in `app/services/poll_services.py`. Three new models (Poll, PollOption, PollResponse) added to `app/models.py` with an Alembic migration. Anonymous session tracking via Flask session cookies.

**Tech Stack:** Flask, SQLAlchemy, Flask-Migrate, HTMX (dynamic option rows), Flask-Mail (optional email share), pytest

**Spec:** `docs/superpowers/specs/2026-03-25-gamenight-redesign-design.md`

**Prerequisite:** Phase 1 and Phase 2 complete, all tests passing.

---

## File Map

### New files
- `app/models.py` — add `Poll`, `PollOption`, `PollResponse` models (modify existing)
- `app/blueprints/polls.py` — polls blueprint
- `app/services/poll_services.py` — poll business logic
- `app/templates/poll_create.html` — admin: create poll form
- `app/templates/poll_list.html` — admin: list all polls
- `app/templates/poll_respond.html` — public: respond to poll
- `app/templates/_poll_option_row.html` — HTMX fragment: dynamic option add/remove
- `app/templates/_poll_results.html` — HTMX fragment: results after submission
- `app/templates/_poll_thanks.html` — HTMX fragment: thank-you state
- `tests/services/test_poll_services.py`
- `tests/blueprints/test_polls.py`

### Modified files
- `app/__init__.py` — register `polls_bp`
- `app/blueprints/__init__.py` — export `polls_bp`
- `app/templates/base.html` — add polls nav item (conditional on active polls)
- `app/templates/index.html` — add active polls section to dashboard
- `app/templates/admin_page.html` — add polls management link/section

---

## Task 1: Poll models + Alembic migration

**Files:**
- Modify: `app/models.py`

- [ ] **Step 1: Add models to `app/models.py`**

Add at the end of the file:

```python
import secrets as _secrets


class Poll(db.Model):
    __tablename__ = "polls"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("people.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=func.current_timestamp())
    closes_at = db.Column(db.DateTime, nullable=True)
    closed = db.Column(db.Boolean, default=False, nullable=False)
    token = db.Column(db.Text, unique=True, nullable=False)
    multi_select = db.Column(db.Boolean, default=False, nullable=False)

    creator = db.relationship("Person", foreign_keys=[created_by])
    options = db.relationship("PollOption", back_populates="poll", cascade="all, delete-orphan",
                              order_by="PollOption.display_order")
    responses = db.relationship("PollResponse", back_populates="poll", cascade="all, delete-orphan")

    @staticmethod
    def generate_token() -> str:
        return _secrets.token_urlsafe(16)


class PollOption(db.Model):
    __tablename__ = "poll_options"

    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey("polls.id"), nullable=False)
    label = db.Column(db.Text, nullable=False)
    display_order = db.Column(db.Integer, default=0, nullable=False)

    poll = db.relationship("Poll", back_populates="options")
    responses = db.relationship("PollResponse", back_populates="option", cascade="all, delete-orphan")


class PollResponse(db.Model):
    __tablename__ = "poll_responses"

    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey("polls.id"), nullable=False)
    option_id = db.Column(db.Integer, db.ForeignKey("poll_options.id"), nullable=False)
    person_id = db.Column(db.Integer, db.ForeignKey("people.id"), nullable=True)
    respondent_name = db.Column(db.Text, nullable=True)  # Stored as entered; compared normalised
    created_at = db.Column(db.DateTime, default=func.current_timestamp())

    poll = db.relationship("Poll", back_populates="responses")
    option = db.relationship("PollOption", back_populates="responses")
    person = db.relationship("Person")
```

- [ ] **Step 2: Generate and apply migration**

```bash
flask db migrate -m "add poll tables"
flask db upgrade
```
Expected: New migration file in `migrations/versions/`, tables created in DB.

- [ ] **Step 3: Verify migration applies cleanly from scratch**

```bash
flask db downgrade -1
flask db upgrade
```
Expected: Both commands succeed with no errors.

- [ ] **Step 4: Commit**

```bash
git add app/models.py migrations/
git commit -m "feat: add Poll, PollOption, PollResponse models and migration"
```

---

## Task 2: Poll service — core logic (TDD)

**Files:**
- Create: `app/services/poll_services.py`
- Create: `tests/services/test_poll_services.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/services/test_poll_services.py
import pytest
from datetime import datetime, timedelta
from app.models import Poll, PollOption, PollResponse, Person
from app.extensions import db as _db
from app.services.poll_services import (
    create_poll,
    poll_is_active,
    get_poll_by_token,
    submit_response,
    get_results,
)


# Note: `app` and `db` fixtures come from tests/conftest.py (Phase 1).
# Before writing these tests, read the Person model in app/models.py to confirm
# the required NOT NULL fields. Person uses first_name + last_name (NOT a name field).

# This fixture is duplicated in test_polls.py. Move it to tests/conftest.py to avoid
# unique email collisions across test runs (both files run in the same session).

@pytest.fixture()
def poll_author(app, db):
    """A real Person to satisfy Poll.created_by NOT NULL FK constraint.
    Uses random email to avoid unique constraint collisions across test runs.
    No manual teardown — Poll rows reference this Person via NOT NULL FK, so
    deleting it while polls exist causes a FK violation. Let db fixture teardown handle it.
    """
    import uuid
    with app.app_context():
        person = Person(
            first_name="Test",
            last_name="Author",
            email=f"author_{uuid.uuid4().hex[:8]}@test.invalid",
        )
        _db.session.add(person)
        _db.session.commit()
        yield person
        # Do NOT manually delete here — Poll.created_by FK constraint will cause
        # an IntegrityError if polls exist. Rely on db fixture's drop_all() teardown.


@pytest.fixture()
def sample_poll(app, db, poll_author):
    """Create a simple single-select poll for testing."""
    with app.app_context():
        poll = create_poll(
            title="Test Poll",
            description="Which day?",
            option_labels=["Friday", "Saturday", "Sunday"],
            created_by_id=poll_author.id,
            multi_select=False,
        )
        yield poll
        # Cleanup handled by db fixture teardown


# ── poll_is_active ──────────────────────────────────────────────────────

def test_poll_is_active_open_poll(app, sample_poll):
    with app.app_context():
        assert poll_is_active(sample_poll) is True


def test_poll_is_active_manually_closed(app, sample_poll):
    with app.app_context():
        sample_poll.closed = True
        assert poll_is_active(sample_poll) is False


def test_poll_is_active_expired(app, sample_poll):
    with app.app_context():
        sample_poll.closes_at = datetime.utcnow() - timedelta(hours=1)
        assert poll_is_active(sample_poll) is False


def test_poll_is_active_not_yet_expired(app, sample_poll):
    with app.app_context():
        sample_poll.closes_at = datetime.utcnow() + timedelta(hours=1)
        assert poll_is_active(sample_poll) is True


def test_poll_is_active_at_exact_boundary(app, sample_poll):
    """Poll expires at closes_at exactly (<=), not after."""
    with app.app_context():
        sample_poll.closes_at = datetime.utcnow()
        assert poll_is_active(sample_poll) is False


# ── create_poll ─────────────────────────────────────────────────────────

def test_create_poll_generates_token(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Availability", None, ["Mon", "Tue"], poll_author.id, False)
        assert poll.token is not None
        assert len(poll.token) >= 16


def test_create_poll_creates_options(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B", "C"], poll_author.id, False)
        assert len(poll.options) == 3
        assert poll.options[0].label == "A"
        assert poll.options[1].display_order == 1


# ── submit_response ─────────────────────────────────────────────────────

def test_submit_response_anonymous_single_select(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B"], poll_author.id, False)
        option_id = poll.options[0].id
        success, msg = submit_response(poll, option_ids=[option_id],
                                       person_id=None, respondent_name="Alice")
        assert success is True
        assert PollResponse.query.filter_by(poll_id=poll.id).count() == 1


def test_submit_response_rejects_duplicate_single_select(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B"], poll_author.id, False)
        option_id = poll.options[0].id
        submit_response(poll, [option_id], None, "Alice")
        success, msg = submit_response(poll, [option_id], None, "Alice")
        assert success is False
        assert "already" in msg.lower()


def test_submit_response_name_matching_is_case_insensitive(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B"], poll_author.id, False)
        option_id = poll.options[0].id
        submit_response(poll, [option_id], None, "Alice")
        success, _ = submit_response(poll, [option_id], None, "ALICE")
        assert success is False


def test_submit_response_replaces_on_multi_select(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B", "C"], poll_author.id, True)
        ids = [poll.options[0].id, poll.options[1].id]
        submit_response(poll, ids, None, "Bob")
        new_ids = [poll.options[2].id]
        success, _ = submit_response(poll, new_ids, None, "Bob")
        assert success is True
        responses = PollResponse.query.filter_by(poll_id=poll.id).all()
        assert len(responses) == 1
        assert responses[0].option_id == poll.options[2].id


def test_submit_response_logged_in_multi_select(app, db, poll_author):
    """A logged-in user submitting multi-select uses person_id for duplicate detection."""
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B", "C"], poll_author.id, True)
        ids = [poll.options[0].id, poll.options[1].id]
        submit_response(poll, ids, person_id=poll_author.id, respondent_name=None)
        new_ids = [poll.options[2].id]
        success, _ = submit_response(poll, new_ids, person_id=poll_author.id, respondent_name=None)
        assert success is True
        responses = PollResponse.query.filter_by(poll_id=poll.id, person_id=poll_author.id).all()
        assert len(responses) == 1


def test_create_poll_token_collision_raises(app, db, poll_author):
    """If generate_token returns a colliding value 3× in a row, RuntimeError is raised."""
    from unittest.mock import patch
    with app.app_context():
        existing = create_poll("Existing", None, ["A"], poll_author.id, False)
        # Force token to always collide with the existing poll
        with patch.object(Poll, "generate_token", return_value=existing.token):
            with pytest.raises(RuntimeError):
                create_poll("New", None, ["A"], poll_author.id, False)


def test_submit_response_rejected_for_closed_poll(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A"], poll_author.id, False)
        poll.closed = True
        success, msg = submit_response(poll, [poll.options[0].id], None, "Alice")
        assert success is False


# ── get_results ─────────────────────────────────────────────────────────

def test_get_results_counts_responses(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B"], poll_author.id, False)
        submit_response(poll, [poll.options[0].id], None, "Alice")
        submit_response(poll, [poll.options[0].id], None, "Bob")
        submit_response(poll, [poll.options[1].id], None, "Carol")
        results = get_results(poll)
        a_count = next(r["count"] for r in results if r["label"] == "A")
        b_count = next(r["count"] for r in results if r["label"] == "B")
        assert a_count == 2
        assert b_count == 1
```

- [ ] **Step 2: Run to confirm failures**

```bash
pytest tests/services/test_poll_services.py -v
```
Expected: `ImportError` (module not created yet).

- [ ] **Step 3: Implement `poll_services.py`**

```python
# app/services/poll_services.py
from datetime import datetime
from typing import Optional

from app.extensions import db
from app.models import Poll, PollOption, PollResponse


def poll_is_active(poll: Poll) -> bool:
    """Single source of truth for whether a poll accepts responses."""
    if poll.closed:
        return False
    if poll.closes_at is not None and poll.closes_at <= datetime.utcnow():
        return False
    return True


def create_poll(
    title: str,
    description: Optional[str],
    option_labels: list[str],
    created_by_id: Optional[int],
    multi_select: bool,
    closes_at: Optional[datetime] = None,
) -> Poll:
    """Create a new poll with options. Returns the saved Poll."""
    for attempt in range(3):
        token = Poll.generate_token()
        if not Poll.query.filter_by(token=token).first():
            break
    else:
        raise RuntimeError("Could not generate a unique poll token after 3 attempts")

    poll = Poll(
        title=title,
        description=description,
        created_by=created_by_id,
        multi_select=multi_select,
        closes_at=closes_at,
        token=token,
    )
    db.session.add(poll)
    db.session.flush()  # Get poll.id before adding options

    for i, label in enumerate(option_labels):
        db.session.add(PollOption(poll_id=poll.id, label=label.strip(), display_order=i))

    db.session.commit()
    return poll


def get_poll_by_token(token: str) -> Optional[Poll]:
    """Fetch a poll by its shareable token."""
    return Poll.query.filter_by(token=token).first()


def has_responded(poll: Poll, person_id: Optional[int], respondent_name: Optional[str]) -> bool:
    """Check if this respondent has already submitted a response."""
    query = PollResponse.query.filter_by(poll_id=poll.id)
    if person_id is not None:
        return query.filter_by(person_id=person_id).first() is not None
    if respondent_name:
        normalised = respondent_name.strip().lower()
        existing = query.filter(PollResponse.person_id.is_(None)).all()
        return any(
            (r.respondent_name or "").strip().lower() == normalised
            for r in existing
        )
    return False


def submit_response(
    poll: Poll,
    option_ids: list[int],
    person_id: Optional[int],
    respondent_name: Optional[str],
) -> tuple[bool, str]:
    """Submit a response. Returns (success, message)."""
    if not poll_is_active(poll):
        return False, "This poll is no longer accepting responses."

    # Store original casing for display; normalised only for duplicate checks.
    # Spec: "respondent_name is stored as entered, normalised for duplicate-prevention lookups only."
    original_name = respondent_name  # Kept as-is from form input
    normalised_name = respondent_name.strip().lower() if respondent_name else None

    if poll.multi_select:
        # Delete existing responses for this respondent and replace (last-write-wins)
        existing = _get_existing_responses(poll, person_id, normalised_name)
        for r in existing:
            db.session.delete(r)
    else:
        if has_responded(poll, person_id, normalised_name):
            return False, "You have already responded to this poll."

    # Validate all option_ids belong to this poll
    valid_ids = {opt.id for opt in poll.options}
    for oid in option_ids:
        if oid not in valid_ids:
            return False, "Invalid option selected."

    for oid in option_ids:
        db.session.add(PollResponse(
            poll_id=poll.id,
            option_id=oid,
            person_id=person_id,
            respondent_name=original_name,  # Store original casing
        ))

    db.session.commit()
    return True, "Response recorded. Thank you!"


def get_results(poll: Poll) -> list[dict]:
    """Return response counts per option, sorted by display_order."""
    results = []
    for option in poll.options:
        count = PollResponse.query.filter_by(poll_id=poll.id, option_id=option.id).count()
        results.append({
            "option_id": option.id,
            "label": option.label,
            "count": count,
        })
    return results


def _get_existing_responses(
    poll: Poll,
    person_id: Optional[int],
    normalised_name: Optional[str],
) -> list[PollResponse]:
    query = PollResponse.query.filter_by(poll_id=poll.id)
    if person_id is not None:
        return query.filter_by(person_id=person_id).all()
    if normalised_name:
        all_anon = query.filter(PollResponse.person_id.is_(None)).all()
        return [r for r in all_anon
                if (r.respondent_name or "").strip().lower() == normalised_name.lower()]
    return []
```

- [ ] **Step 4: Run tests to confirm they pass**

```bash
pytest tests/services/test_poll_services.py -v
```
Expected: All pass.

- [ ] **Step 5: Commit**

```bash
git add app/services/poll_services.py tests/services/test_poll_services.py
git commit -m "feat: implement poll services with TDD (create, respond, results, active check)"
```

---

## Task 3: Polls blueprint + routes (TDD)

**Files:**
- Create: `app/blueprints/polls.py`
- Modify: `app/blueprints/__init__.py`
- Modify: `app/__init__.py`
- Create: `tests/blueprints/test_polls.py`

- [ ] **Step 1: Write failing integration tests**

> **Fixture note:** `client`, `admin_client`, `auth_client`, `app`, and `db` are all defined in `tests/conftest.py` from Phase 1. Do not redefine them here. If `admin_client` or `auth_client` are missing from the Phase 1 conftest, add them there — they create a test user and log in with/without admin privileges.

```python
# tests/blueprints/test_polls.py
# Note: `client`, `admin_client`, `auth_client`, `app`, and `db` fixtures are all
# defined in tests/conftest.py (created in Phase 1). No need to redefine them here.
import pytest
from app.models import Poll, Person
from app.extensions import db as _db
from app.services.poll_services import create_poll


@pytest.fixture()
def poll_author(app, db):
    """A real Person to satisfy Poll.created_by NOT NULL FK constraint.
    IMPORTANT: Move this fixture to tests/conftest.py to share it with
    test_poll_services.py and avoid unique email collisions across test runs.
    """
    import uuid
    with app.app_context():
        person = Person(
            first_name="Poll",
            last_name="Author",
            email=f"pollauthor_{uuid.uuid4().hex[:8]}@test.invalid",
        )
        _db.session.add(person)
        _db.session.commit()
        yield person
        # Do NOT manually delete — Poll.created_by NOT NULL FK will cause IntegrityError.
        # Rely on db fixture's drop_all() for cleanup.


@pytest.fixture()
def open_poll(app, db, poll_author):
    with app.app_context():
        poll = create_poll("Best Day?", None, ["Friday", "Saturday"], poll_author.id, False)
        yield poll


@pytest.fixture()
def closed_poll(app, db, poll_author):
    with app.app_context():
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
    resp = client.post(f"/poll/{open_poll.token}/respond",
                       data={"option_ids": str(option_id), "respondent_name": "Alice"})
    assert resp.status_code == 200
    assert b"Thank you" in resp.data or b"thank" in resp.data.lower()


def test_submit_response_sets_session_cookie(client, open_poll):
    option_id = open_poll.options[0].id
    with client.session_transaction() as sess:
        assert f"poll_{open_poll.token}_responded" not in sess
    client.post(f"/poll/{open_poll.token}/respond",
                data={"option_ids": str(option_id), "respondent_name": "Bob"})
    with client.session_transaction() as sess:
        assert sess.get(f"poll_{open_poll.token}_responded") is True


def test_submit_response_rejects_duplicate(client, open_poll):
    option_id = open_poll.options[0].id
    client.post(f"/poll/{open_poll.token}/respond",
                data={"option_ids": str(option_id), "respondent_name": "Carol"})
    resp = client.post(f"/poll/{open_poll.token}/respond",
                       data={"option_ids": str(option_id), "respondent_name": "Carol"})
    assert resp.status_code == 200
    assert b"already" in resp.data.lower()


def test_admin_can_create_poll(admin_client):
    resp = admin_client.post("/polls/create", data={
        "title": "New Poll",
        "description": "",
        "option_labels": ["Option A", "Option B"],
        "multi_select": "false",
    })
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
    """Anonymous submission without respondent_name should fail gracefully."""
    option_id = open_poll.options[0].id
    resp = client.post(f"/poll/{open_poll.token}/respond",
                       data={"option_ids": str(option_id)})  # No respondent_name
    assert resp.status_code == 200
    # Should show an error, not a thank-you
    assert b"name" in resp.data.lower() or b"error" in resp.data.lower()
```

- [ ] **Step 2: Run to confirm failures**

```bash
pytest tests/blueprints/test_polls.py -v
```
Expected: 404 errors.

- [ ] **Step 3: Create `app/blueprints/polls.py`**

```python
# app/blueprints/polls.py
from flask import Blueprint, render_template, request, redirect, url_for, session, abort
from flask_login import login_required, current_user

from app.services.poll_services import (
    create_poll, get_poll_by_token, poll_is_active, submit_response, get_results
)
from app.utils import admin_required  # Confirmed path — app/utils/__init__.py re-exports this

# No url_prefix — admin routes use /polls/... and public route uses /poll/<token>
# This keeps the shareable URL as /poll/<token> per the spec.
polls_bp = Blueprint("polls", __name__)


# ── Admin routes (login + admin required) ────────────────────────────── #

@polls_bp.route("/polls/")
@login_required
@admin_required
def poll_list():
    from app.models import Poll
    polls = Poll.query.order_by(Poll.created_at.desc()).all()
    return render_template("poll_list.html", polls=polls)


@polls_bp.route("/polls/create", methods=["GET", "POST"])
@login_required
@admin_required
def poll_create():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        option_labels = [
            label.strip()
            for label in request.form.getlist("option_labels")
            if label.strip()
        ]
        multi_select = request.form.get("multi_select") == "true"

        if not title or len(option_labels) < 2:
            return render_template("poll_create.html",
                                   error="A title and at least two options are required.")

        poll = create_poll(title, description, option_labels, current_user.id, multi_select)
        return redirect(url_for("polls.poll_list"))

    return render_template("poll_create.html")


@polls_bp.route("/polls/<int:poll_id>/close", methods=["POST"])
@login_required
@admin_required
def poll_close(poll_id: int):
    from app.models import Poll
    from app.extensions import db
    poll = Poll.query.get_or_404(poll_id)
    poll.closed = True
    db.session.commit()
    return redirect(url_for("polls.poll_list"))


# ── Public routes (no login required) ────────────────────────────────── #
# Shareable URL: /poll/<token> — matches what is shown in the admin panel.

@polls_bp.route("/poll/<token>", endpoint="poll_respond")
def poll_page(token: str):
    """Public poll page — anyone with the link can view and respond."""
    poll = get_poll_by_token(token)
    if poll is None:
        abort(404)

    already_responded = session.get(f"poll_{token}_responded", False)
    results = get_results(poll) if already_responded or not poll_is_active(poll) else None

    return render_template("poll_respond.html",
                           poll=poll,
                           active=poll_is_active(poll),
                           already_responded=already_responded,
                           results=results)


@polls_bp.route("/polls/option-row", endpoint="poll_option_row")
@login_required
@admin_required
def poll_option_row():
    """HTMX fragment: return a new option input row for the create poll form.
    Must be registered here — poll_create.html calls url_for('polls.poll_option_row').
    """
    return render_template("_poll_option_row.html")


@polls_bp.route("/poll/<token>/respond", methods=["POST"], endpoint="poll_submit")
def poll_submit(token: str):
    """HTMX endpoint — submit poll response, return fragment."""
    poll = get_poll_by_token(token)
    if poll is None:
        abort(404)

    person_id = current_user.id if current_user.is_authenticated else None
    respondent_name = request.form.get("respondent_name", "") or None
    option_ids_raw = request.form.getlist("option_ids")

    try:
        option_ids = [int(oid) for oid in option_ids_raw]
    except (ValueError, TypeError):
        return render_template("_poll_thanks.html",
                               success=False, message="Invalid submission.", results=None)

    if not option_ids:
        return render_template("_poll_thanks.html",
                               success=False, message="Please select at least one option.", results=None)

    if person_id is None and not respondent_name:
        return render_template("_poll_thanks.html",
                               success=False, message="Please enter your name.", results=None)

    success, message = submit_response(poll, option_ids, person_id, respondent_name)

    if success:
        session[f"poll_{token}_responded"] = True

    results = get_results(poll)
    return render_template("_poll_thanks.html",
                           success=success, message=message, results=results, poll=poll)
```

- [ ] **Step 4: Register the blueprint**

In `app/blueprints/__init__.py`, add:
```python
from app.blueprints.polls import polls_bp
```

In `app/__init__.py` `register_blueprints`, add:
```python
app.register_blueprint(blueprints.polls_bp)
```

- [ ] **Step 5: Run tests**

```bash
pytest tests/blueprints/test_polls.py -v
```

If tests fail, check these specific issues before debugging generically:
- `ImportError: cannot import name 'admin_required'` → import is `from app.utils import admin_required`
- `404` on `/polls/create` → blueprint not registered in `app/__init__.py`
- `302` on admin POST to `/polls/create` → `admin_client` fixture may not have `admin=True` set on the Person
- `BuildError` for `polls.poll_option_row` → route is missing from `polls.py` (see Step 3 above)
- `IntegrityError` during fixture teardown → `poll_author` fixture is trying to manually delete a Person while polls still reference it via FK; remove the manual delete from the fixture

- [ ] **Step 6: Commit**

```bash
git add app/blueprints/polls.py app/blueprints/__init__.py app/__init__.py tests/blueprints/test_polls.py
git commit -m "feat: add polls blueprint with admin management and public response routes"
```

---

## Task 4: Poll templates

**Files:**
- Create: `app/templates/poll_list.html`
- Create: `app/templates/poll_create.html`
- Create: `app/templates/poll_respond.html`
- Create: `app/templates/_poll_option_row.html`
- Create: `app/templates/_poll_results.html`
- Create: `app/templates/_poll_thanks.html`

- [ ] **Step 1: Create `poll_list.html`** (admin, extends base.html)

```html
{% extends "base.html" %}
{% block title %}Polls — Game Night{% endblock %}
{% block content %}
<div class="flex items-center justify-between mb-6">
  <h1 class="text-2xl font-bold text-stone-800">Polls</h1>
  <a href="{{ url_for('polls.poll_create') }}"
     class="inline-flex items-center rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 transition-colors">
    New Poll
  </a>
</div>

{% if polls %}
<div class="space-y-3">
  {% for poll in polls %}
  <div class="bg-white rounded-xl border border-stone-200 shadow-sm p-5">
    <div class="flex items-start justify-between">
      <div>
        <h2 class="text-base font-semibold text-stone-800">{{ poll.title }}</h2>
        {% if poll.description %}
        <p class="text-sm text-stone-500 mt-0.5">{{ poll.description }}</p>
        {% endif %}
        <div class="flex gap-3 mt-2 text-xs text-stone-400">
          <span>{{ poll.options | length }} options</span>
          {% if poll.closes_at %}<span>Closes {{ poll.closes_at.strftime('%b %-d') }}</span>{% endif %}
          {% if poll.closed %}<span class="text-amber-600 font-medium">Closed</span>{% endif %}
        </div>
      </div>
      <div class="flex gap-2 ml-4">
        <a href="{{ url_for('polls.poll_respond', token=poll.token) }}"
           class="text-xs text-stone-500 hover:text-red-600 underline">View</a>
        {% if not poll.closed %}
        <form method="POST" action="{{ url_for('polls.poll_close', poll_id=poll.id) }}">
          <button type="submit" class="text-xs text-stone-500 hover:text-red-600 underline">Close</button>
        </form>
        {% endif %}
      </div>
    </div>
    <div class="mt-3 pt-3 border-t border-stone-100">
      <span class="text-xs text-stone-500 select-all font-mono bg-stone-50 px-2 py-1 rounded">
        {{ request.host_url }}poll/{{ poll.token }}
      </span>
    </div>
  </div>
  {% endfor %}
</div>
{% else %}
<p class="text-stone-500 text-sm">No polls yet. Create one to get started.</p>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Create `poll_create.html`** (admin, extends base.html)

```html
{% extends "base.html" %}
{% block title %}New Poll — Game Night{% endblock %}
{% block content %}
<div class="max-w-lg">
  <h1 class="text-2xl font-bold text-stone-800 mb-6">Create Poll</h1>

  {% if error %}
  <div class="mb-4 rounded-lg px-4 py-3 text-sm bg-red-50 text-red-800 border border-red-200">{{ error }}</div>
  {% endif %}

  <form method="POST" action="{{ url_for('polls.poll_create') }}">
    <div class="bg-white rounded-xl border border-stone-200 shadow-sm p-6 space-y-5">

      <div>
        <label class="block text-sm font-medium text-stone-700 mb-1">Title <span class="text-red-600">*</span></label>
        <input type="text" name="title" required
               class="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent" />
      </div>

      <div>
        <label class="block text-sm font-medium text-stone-700 mb-1">Description</label>
        <textarea name="description" rows="2"
                  class="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent"></textarea>
      </div>

      <div>
        <label class="block text-sm font-medium text-stone-700 mb-2">Options <span class="text-red-600">*</span></label>
        <div id="options-list" class="space-y-2">
          <div class="flex gap-2">
            <input type="text" name="option_labels" placeholder="Option 1"
                   class="flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent" />
          </div>
          <div class="flex gap-2">
            <input type="text" name="option_labels" placeholder="Option 2"
                   class="flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent" />
          </div>
        </div>
        <button type="button"
                hx-get="{{ url_for('polls.poll_option_row') }}"
                hx-target="#options-list"
                hx-swap="beforeend"
                class="mt-2 text-sm text-red-600 hover:text-red-700 underline">
          + Add option
        </button>
      </div>

      <div class="flex items-center gap-3">
        <label class="text-sm font-medium text-stone-700">Allow multiple selections</label>
        <input type="checkbox" name="multi_select" value="true"
               class="rounded border-stone-300 text-red-600 focus:ring-red-500" />
      </div>

      <div class="flex items-center gap-3">
        <label class="block text-sm font-medium text-stone-700">Close date (optional)</label>
        <input type="datetime-local" name="closes_at"
               class="rounded-lg border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent" />
      </div>

      <button type="submit"
              class="w-full rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 transition-colors">
        Create Poll
      </button>
    </div>
  </form>
</div>
{% endblock %}
```

Add an HTMX endpoint to the blueprint for the "add option" button:

```python
@polls_bp.route("/option-row")
def poll_option_row():
    """HTMX fragment: return a new option input row."""
    return render_template("_poll_option_row.html")
```

- [ ] **Step 3: Create `_poll_option_row.html`**

```html
<div class="flex gap-2">
  <input type="text" name="option_labels" placeholder="Option"
         class="flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent" />
  <button type="button"
          onclick="this.parentElement.remove()"
          class="text-stone-400 hover:text-red-600 px-2">✕</button>
</div>
```

- [ ] **Step 4: Create `poll_respond.html`** (public, no base — standalone page)

This page must work without login. Use a minimal standalone layout similar to `auth_base.html` but without the login card:

```html
<!DOCTYPE html>
<html lang="en" class="h-full bg-stone-50">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{{ poll.title }} — Game Night</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@1.9.12" defer></script>
</head>
<body class="min-h-full bg-stone-50 py-12 px-4">
  <div class="max-w-md mx-auto">
    <div class="text-center mb-8">
      <h1 class="text-2xl font-bold text-stone-800">{{ poll.title }}</h1>
      {% if poll.description %}
      <p class="text-stone-500 mt-2">{{ poll.description }}</p>
      {% endif %}
    </div>

    <div id="poll-body">
      {% if not active %}
        <div class="bg-white rounded-xl border border-stone-200 p-6 text-center">
          <p class="text-stone-500">This poll is closed. {% if results %}See results below.{% endif %}</p>
        </div>
        {% if results %}{% include "_poll_results.html" %}{% endif %}

      {% elif already_responded %}
        <div class="bg-green-50 rounded-xl border border-green-200 p-6 text-center mb-4">
          <p class="text-green-800 font-medium">You've already responded — thanks!</p>
        </div>
        {% if results %}{% include "_poll_results.html" %}{% endif %}

      {% else %}
        <form hx-post="{{ url_for('polls.poll_submit', token=poll.token) }}"
              hx-target="#poll-body"
              hx-swap="innerHTML">
          <div class="bg-white rounded-xl border border-stone-200 shadow-sm p-6 space-y-4">

            <div class="space-y-2">
              {% for option in poll.options %}
              <label class="flex items-center gap-3 p-3 rounded-lg border border-stone-200 cursor-pointer hover:bg-stone-50 transition-colors">
                <input type="{{ 'checkbox' if poll.multi_select else 'radio' }}"
                       name="option_ids" value="{{ option.id }}"
                       class="text-red-600 focus:ring-red-500" />
                <span class="text-sm font-medium text-stone-700">{{ option.label }}</span>
              </label>
              {% endfor %}
            </div>

            {% if not current_user.is_authenticated %}
            <div>
              <label class="block text-sm font-medium text-stone-700 mb-1">Your name <span class="text-red-600">*</span></label>
              <input type="text" name="respondent_name" required placeholder="First name is fine"
                     class="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent" />
            </div>
            {% endif %}

            <button type="submit"
                    class="w-full rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 transition-colors">
              Submit
            </button>
          </div>
        </form>
      {% endif %}
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 5: Create `_poll_results.html`**

```html
<div class="bg-white rounded-xl border border-stone-200 shadow-sm p-5 mt-4">
  <h3 class="text-sm font-semibold text-stone-700 mb-3">Results</h3>
  <div class="space-y-2">
    {% set total = results | sum(attribute='count') %}
    {% for row in results | sort(attribute='count', reverse=true) %}
    <div>
      <div class="flex justify-between text-sm mb-0.5">
        <span class="text-stone-700">{{ row.label }}</span>
        <span class="text-stone-500 font-medium">{{ row.count }}</span>
      </div>
      <div class="h-2 bg-stone-100 rounded-full overflow-hidden">
        <div class="h-full bg-red-500 rounded-full transition-all"
             style="width: {{ ((row.count / total * 100) if total > 0 else 0) | round | int }}%"></div>
      </div>
    </div>
    {% endfor %}
  </div>
</div>
```

- [ ] **Step 6: Create `_poll_thanks.html`**

```html
{% if success %}
<div class="bg-green-50 rounded-xl border border-green-200 p-6 text-center mb-4">
  <p class="text-green-800 font-medium">{{ message }}</p>
</div>
{% include "_poll_results.html" %}
{% else %}
<div class="bg-red-50 rounded-xl border border-red-200 p-6 text-center">
  <p class="text-red-800">{{ message }}</p>
  <button onclick="history.back()" class="mt-3 text-sm text-red-600 underline">Go back</button>
</div>
{% endif %}
```

- [ ] **Step 7: Run tests**

```bash
pytest tests/blueprints/test_polls.py -v
```
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
git add app/templates/poll_*.html app/templates/_poll_*.html
git commit -m "feat: add poll templates (create, list, respond, results)"
```

---

## Task 5: Surface polls on dashboard and nav

**Files:**
- Modify: `app/templates/base.html`
- Modify: `app/templates/index.html`
- Modify: `app/templates/admin_page.html`

- [ ] **Step 1: Add polls link to desktop sidebar and mobile nav in `base.html`**

In the desktop sidebar nav_items loop, add a polls item conditionally (only show if there are active polls — query this in the base template context, or use a template context processor):

Add a context processor in `app/__init__.py` or `app/blueprints/polls.py`:

```python
@polls_bp.app_context_processor
def inject_active_polls_count():
    """Make active poll count available in all templates."""
    from app.models import Poll
    from app.services.poll_services import poll_is_active
    try:
        count = sum(1 for p in Poll.query.filter_by(closed=False).all() if poll_is_active(p))
    except Exception:
        count = 0
    return {"active_polls_count": count}
```

Add the polls nav item in `base.html` nav_items (after Stats):
```
('polls.poll_respond', 'Polls', '<svg-path-for-clipboard-icon>'),
```

Use a clipboard/checklist icon path. SVG path for a clipboard: `M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2`

Nav item behavior: the admin sidebar link goes to `polls.poll_list` and must be guarded with `{% if current_user.is_authenticated and (current_user.admin or current_user.owner) %}`. Regular users clicking an unguarded nav link get silently redirected by `@admin_required`, which is confusing. Do NOT add this to the public nav — the shareable poll URL is sent directly via the context processor on the dashboard, not through navigation.

- [ ] **Step 2: Add active polls section to `index.html`**

First, update the context processor to inject both `active_polls_count` and `active_polls` (the full list for dashboard links):

```python
@polls_bp.app_context_processor
def inject_active_polls():
    """Make active poll count and list available in all templates."""
    from app.models import Poll
    from app.services.poll_services import poll_is_active
    try:
        all_open = Poll.query.filter_by(closed=False).all()
        active = [p for p in all_open if poll_is_active(p)]
        return {"active_polls_count": len(active), "active_polls": active}
    except Exception:
        return {"active_polls_count": 0, "active_polls": []}
```

Then add to `index.html`:

```html
{% if active_polls_count > 0 %}
<div class="mt-6">
  <h2 class="text-lg font-semibold text-stone-800 mb-3">Open Polls</h2>
  <div class="space-y-2">
    {% for poll in active_polls %}
    <a href="{{ url_for('polls.poll_respond', token=poll.token) }}"
       class="flex items-center justify-between bg-white rounded-xl border border-stone-200 px-5 py-3 hover:bg-stone-50 transition-colors">
      <span class="text-sm font-medium text-stone-700">{{ poll.title }}</span>
      <span class="text-xs text-red-600 font-medium">Vote →</span>
    </a>
    {% endfor %}
  </div>
</div>
{% endif %}
```

- [ ] **Step 3: Add polls management link to `admin_page.html`**

Read `admin_page.html` first to find an appropriate insertion point (near other management section links). Add:

```html
<div class="mt-6">
  <h2 class="text-base font-semibold text-stone-800 mb-3">Polls</h2>
  <a href="{{ url_for('polls.poll_list') }}"
     class="inline-flex items-center rounded-lg border border-stone-300 px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 transition-colors">
    Manage Polls
    {% if active_polls_count > 0 %}
    <span class="ml-2 inline-flex items-center justify-center rounded-full bg-red-100 text-red-700 text-xs font-medium px-2 py-0.5">
      {{ active_polls_count }} active
    </span>
    {% endif %}
  </a>
</div>
```

- [ ] **Step 4: Run full test suite**

```bash
pytest -v --cov=app --cov-fail-under=60
```
Expected: All pass.

- [ ] **Step 5: Run linter**

```bash
ruff check .
mypy app/ tests/
```
Fix any issues.

- [ ] **Step 6: Final Phase 3 commit**

```bash
git add app/templates/base.html app/templates/index.html app/templates/admin_page.html app/__init__.py app/blueprints/polls.py
git commit -m "feat: complete phase 3 — poll system with dashboard integration and nav surfacing"
```

---

## Task 6: Update CHANGELOG and push

- [ ] **Step 1: Update `CHANGELOG.md`** — mark Phase 3 complete under `[Unreleased]`

- [ ] **Step 2: Push to GitHub**

```bash
git push origin main
```

- [ ] **Step 3: Verify CI passes** — check GitHub Actions tab, confirm all 5 steps (lint, typecheck, security, docker build, tests) pass green.

- [ ] **Step 4: Deploy to homelab** — [HUMAN ACTION REQUIRED] Follow README deployment instructions. Do not attempt to SSH into the homelab or run deploy commands remotely — this requires manual intervention by the repository owner.

---

## Phase 3 Done ✓

All three phases complete. The app has a modern Tailwind UI, full BGG integration with live search, a poll system with shareable links, a full test suite, and CI running on every push.
