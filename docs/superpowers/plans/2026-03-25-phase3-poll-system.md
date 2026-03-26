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
from app.models import Poll, PollOption, PollResponse
from app.extensions import db
from app.services.poll_services import (
    create_poll,
    poll_is_active,
    get_poll_by_token,
    submit_response,
    get_results,
)


@pytest.fixture()
def sample_poll(app, db):
    """Create a simple single-select poll for testing."""
    with app.app_context():
        poll = create_poll(
            title="Test Poll",
            description="Which day?",
            option_labels=["Friday", "Saturday", "Sunday"],
            created_by_id=None,  # We'll use a real person in integration tests
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


# ── create_poll ─────────────────────────────────────────────────────────

def test_create_poll_generates_token(app, db):
    with app.app_context():
        poll = create_poll("Availability", None, ["Mon", "Tue"], None, False)
        assert poll.token is not None
        assert len(poll.token) >= 16


def test_create_poll_creates_options(app, db):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B", "C"], None, False)
        assert len(poll.options) == 3
        assert poll.options[0].label == "A"
        assert poll.options[1].display_order == 1


# ── submit_response ─────────────────────────────────────────────────────

def test_submit_response_anonymous_single_select(app, db):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B"], None, False)
        option_id = poll.options[0].id
        success, msg = submit_response(poll, option_ids=[option_id],
                                       person_id=None, respondent_name="Alice")
        assert success is True
        assert PollResponse.query.filter_by(poll_id=poll.id).count() == 1


def test_submit_response_rejects_duplicate_single_select(app, db):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B"], None, False)
        option_id = poll.options[0].id
        submit_response(poll, [option_id], None, "Alice")
        success, msg = submit_response(poll, [option_id], None, "Alice")
        assert success is False
        assert "already" in msg.lower()


def test_submit_response_name_matching_is_case_insensitive(app, db):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B"], None, False)
        option_id = poll.options[0].id
        submit_response(poll, [option_id], None, "Alice")
        success, _ = submit_response(poll, [option_id], None, "ALICE")
        assert success is False


def test_submit_response_replaces_on_multi_select(app, db):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B", "C"], None, True)
        ids = [poll.options[0].id, poll.options[1].id]
        submit_response(poll, ids, None, "Bob")
        new_ids = [poll.options[2].id]
        success, _ = submit_response(poll, new_ids, None, "Bob")
        assert success is True
        responses = PollResponse.query.filter_by(poll_id=poll.id).all()
        assert len(responses) == 1
        assert responses[0].option_id == poll.options[2].id


def test_submit_response_rejected_for_closed_poll(app, db):
    with app.app_context():
        poll = create_poll("Q", None, ["A"], None, False)
        poll.closed = True
        success, msg = submit_response(poll, [poll.options[0].id], None, "Alice")
        assert success is False


# ── get_results ─────────────────────────────────────────────────────────

def test_get_results_counts_responses(app, db):
    with app.app_context():
        poll = create_poll("Q", None, ["A", "B"], None, False)
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

    normalised_name = respondent_name.strip() if respondent_name else None

    if poll.multi_select:
        # Delete existing responses for this respondent and replace
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
            respondent_name=normalised_name,
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

```python
# tests/blueprints/test_polls.py
import pytest
from app.models import Poll
from app.services.poll_services import create_poll


@pytest.fixture()
def open_poll(app, db):
    with app.app_context():
        poll = create_poll("Best Day?", None, ["Friday", "Saturday"], None, False)
        yield poll


@pytest.fixture()
def closed_poll(app, db):
    with app.app_context():
        poll = create_poll("Old Poll", None, ["A", "B"], None, False)
        poll.closed = True
        from app.extensions import db as _db
        _db.session.commit()
        yield poll


def test_poll_page_loads(client, open_poll):
    resp = client.get(f"/poll/{open_poll.token}")
    assert resp.status_code == 200
    assert b"Best Day?" in resp.data


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
from app.utils.decorators import admin_required  # Adjust import to match existing decorator path

polls_bp = Blueprint("polls", __name__, url_prefix="/polls")


# ── Admin routes (login + admin required) ────────────────────────────── #

@polls_bp.route("/")
@login_required
@admin_required
def poll_list():
    from app.models import Poll
    polls = Poll.query.order_by(Poll.created_at.desc()).all()
    return render_template("poll_list.html", polls=polls)


@polls_bp.route("/create", methods=["GET", "POST"])
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


@polls_bp.route("/<int:poll_id>/close", methods=["POST"])
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

@polls_bp.route("/respond/<token>", endpoint="poll_respond")
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


@polls_bp.route("/respond/<token>/submit", methods=["POST"], endpoint="poll_submit")
def poll_submit(token: str):
    """HTMX endpoint — submit poll response, return fragment."""
    poll = get_poll_by_token(token)
    if poll is None:
        abort(404)

    person_id = current_user.id if current_user.is_authenticated else None
    respondent_name = request.form.get("respondent_name", "").strip() or None
    option_ids_raw = request.form.getlist("option_ids")

    try:
        option_ids = [int(oid) for oid in option_ids_raw]
    except (ValueError, TypeError):
        return render_template("_poll_thanks.html",
                               success=False, message="Invalid submission.")

    if not option_ids:
        return render_template("_poll_thanks.html",
                               success=False, message="Please select at least one option.")

    if person_id is None and not respondent_name:
        return render_template("_poll_thanks.html",
                               success=False, message="Please enter your name.")

    success, message = submit_response(poll, option_ids, person_id, respondent_name)

    if success:
        session[f"poll_{token}_responded"] = True

    results = get_results(poll)
    return render_template("_poll_thanks.html",
                           success=success, message=message, results=results, poll=poll)
```

Note: the public poll URL is `/polls/respond/<token>`. Register this at `/poll/<token>` by adjusting the blueprint url_prefix or adding an app-level route alias — ensure the shareable URL matches what's shown in the admin panel.

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
Fix any issues (route URL mismatches, missing decorator imports, etc.) then rerun until all pass.

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

Note: `polls.poll_respond` requires a token argument — the nav item should link to the polls list for logged-in users (`polls.poll_list`), not a specific poll. For the mobile bottom nav, only show polls item if `active_polls_count > 0`.

- [ ] **Step 2: Add active polls section to `index.html`**

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

Update the context processor to also inject `active_polls` (the list, not just count) for logged-in users.

- [ ] **Step 3: Add polls management link to `admin_page.html`**

Add a "Polls" section/link to the admin page pointing to `polls.poll_list`.

- [ ] **Step 4: Run full test suite**

```bash
pytest -v --cov=app --cov-fail-under=60
```
Expected: All pass.

- [ ] **Step 5: Run linter**

```bash
ruff check .
mypy app/
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

- [ ] **Step 4: Deploy to homelab** — follow README deployment instructions (or use self-hosted runner if configured).

---

## Phase 3 Done ✓

All three phases complete. The app has a modern Tailwind UI, full BGG integration with live search, a poll system with shareable links, a full test suite, and CI running on every push.
