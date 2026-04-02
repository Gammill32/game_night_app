# Live Game Night Tracker — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an optional per-game live tracker that lets a host track scores in real time and push results directly into the existing finalization flow.

**Architecture:** Server-side state in PostgreSQL. Each host action fires an HTMX POST; the server updates the value and returns a refreshed HTML fragment. Session is created in `"configuring"` state on setup page load; fields are added via HTMX; launching the session seeds all `TrackerValue` rows and sets status to `"active"`. Results are saved using the same fetch-or-create upsert pattern as `log_results`.

**Tech Stack:** Flask 2.3.2, Flask-SQLAlchemy 3.0.3, PostgreSQL 15, Alembic/Flask-Migrate, HTMX, Tailwind CSS, SortableJS (CDN)

---

## File Map

| File | Action | Purpose |
|---|---|---|
| `app/models.py` | Modify | Add 4 new models + join table |
| `migrations/versions/<rev>_add_tracker_tables.py` | Create | Migration with raw DDL for NULLS NOT DISTINCT + partial index |
| `app/services/tracker_services.py` | Create | All tracker business logic |
| `app/blueprints/tracker.py` | Create | All tracker routes |
| `app/blueprints/__init__.py` | Modify | Export `tracker_bp` |
| `app/__init__.py` | Modify | Register `tracker_bp` |
| `app/templates/tracker_setup.html` | Create | Setup page |
| `app/templates/tracker_live.html` | Create | Live tracker page |
| `app/templates/tracker_confirm.html` | Create | End-game confirmation |
| `app/templates/_tracker_cell.html` | Create | HTMX cell fragment (returned by value POST) |
| `app/templates/_tracker_field_row.html` | Create | HTMX field row fragment (returned by field-add POST) |
| `app/templates/view_game_night.html` | Modify | Add Track / Resume Tracker buttons per game |
| `tests/services/test_tracker_services.py` | Create | Service unit tests |
| `tests/blueprints/test_tracker.py` | Create | Blueprint integration tests |

---

## Task 1: Add tracker models to app/models.py

**Files:**
- Modify: `app/models.py`

- [ ] **Step 1: Write the failing import test**

In `tests/services/test_tracker_services.py` (create file):

```python
def test_tracker_models_importable():
    from app.models import TrackerSession, TrackerField, TrackerTeam, TrackerValue
    assert TrackerSession.__tablename__ == "tracker_sessions"
    assert TrackerField.__tablename__ == "tracker_fields"
    assert TrackerTeam.__tablename__ == "tracker_teams"
    assert TrackerValue.__tablename__ == "tracker_values"
```

- [ ] **Step 2: Run test to verify it fails**

```
pytest tests/services/test_tracker_services.py::test_tracker_models_importable -v
```

Expected: `ImportError: cannot import name 'TrackerSession'`

- [ ] **Step 3: Add models to app/models.py**

Add the following at the bottom of `app/models.py` (after `PersonBadge`):

```python
# ---------------------------------------------------------------------------
# Live Tracker
# ---------------------------------------------------------------------------

tracker_team_players = db.Table(
    "tracker_team_players",
    db.Column("team_id", db.Integer, db.ForeignKey("tracker_teams.id", ondelete="CASCADE"), primary_key=True),
    db.Column("player_id", db.Integer, db.ForeignKey("players.id"), primary_key=True),
)


class TrackerSession(db.Model):
    __tablename__ = "tracker_sessions"

    id = db.Column(db.Integer, primary_key=True)
    game_night_game_id = db.Column(
        db.Integer, db.ForeignKey("gamenightgames.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    mode = db.Column(db.String, nullable=False)   # "individual" or "teams"
    status = db.Column(db.String, nullable=False)  # "configuring", "active", "completed"
    created_at = db.Column(db.DateTime, server_default=func.now())

    game_night_game = relationship("GameNightGame", back_populates="tracker_session")
    fields = relationship("TrackerField", back_populates="session", cascade="all, delete-orphan", order_by="TrackerField.sort_order")
    teams = relationship("TrackerTeam", back_populates="session", cascade="all, delete-orphan")
    values = relationship("TrackerValue", back_populates="session", cascade="all, delete-orphan")


class TrackerField(db.Model):
    __tablename__ = "tracker_fields"

    id = db.Column(db.Integer, primary_key=True)
    tracker_session_id = db.Column(
        db.Integer, db.ForeignKey("tracker_sessions.id", ondelete="CASCADE"), nullable=False
    )
    type = db.Column(db.String, nullable=False)
    label = db.Column(db.String, nullable=False)
    starting_value = db.Column(db.Integer, default=0)
    is_score_field = db.Column(db.Boolean, default=False, nullable=False)
    sort_order = db.Column(db.Integer, default=0)

    session = relationship("TrackerSession", back_populates="fields")
    values = relationship("TrackerValue", back_populates="field", cascade="all, delete-orphan")


class TrackerTeam(db.Model):
    __tablename__ = "tracker_teams"

    id = db.Column(db.Integer, primary_key=True)
    tracker_session_id = db.Column(
        db.Integer, db.ForeignKey("tracker_sessions.id", ondelete="CASCADE"), nullable=False
    )
    name = db.Column(db.String, nullable=False)

    session = relationship("TrackerSession", back_populates="teams")
    players = relationship("Player", secondary=tracker_team_players)
    values = relationship("TrackerValue", back_populates="team", cascade="all, delete-orphan")


class TrackerValue(db.Model):
    __tablename__ = "tracker_values"

    id = db.Column(db.Integer, primary_key=True)
    tracker_session_id = db.Column(
        db.Integer, db.ForeignKey("tracker_sessions.id", ondelete="CASCADE"), nullable=False
    )
    tracker_field_id = db.Column(
        db.Integer, db.ForeignKey("tracker_fields.id", ondelete="CASCADE"), nullable=False
    )
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=True)
    team_id = db.Column(db.Integer, db.ForeignKey("tracker_teams.id", ondelete="CASCADE"), nullable=True)
    value = db.Column(db.Text, nullable=False, default="0")

    session = relationship("TrackerSession", back_populates="values")
    field = relationship("TrackerField", back_populates="values")
    player = relationship("Player")
    team = relationship("TrackerTeam", back_populates="values")
```

Also add `tracker_session` back-ref to `GameNightGame` (find the `GameNightGame` class and add):

```python
    tracker_session = relationship("TrackerSession", back_populates="game_night_game", uselist=False, cascade="all, delete-orphan")
```

- [ ] **Step 4: Run test to verify it passes**

```
pytest tests/services/test_tracker_services.py::test_tracker_models_importable -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add app/models.py tests/services/test_tracker_services.py
git commit -m "feat: add TrackerSession, TrackerField, TrackerTeam, TrackerValue models"
```

---

## Task 2: Alembic migration for tracker tables

**Files:**
- Create: `migrations/versions/<rev>_add_tracker_tables.py` (run `flask db migrate` to generate, then edit)

- [ ] **Step 1: Generate migration**

```bash
flask db migrate -m "add tracker tables"
```

This creates a file in `migrations/versions/`. Open it — it will have auto-generated `upgrade()` and `downgrade()` functions. **Replace the entire file body** with the following (keep the revision ID that was generated):

```python
"""add tracker tables

Revision ID: <keep generated value>
Revises: 8b9f3a3784a3
Create Date: <keep generated value>

"""
from alembic import op
import sqlalchemy as sa

revision = '<keep generated value>'
down_revision = '8b9f3a3784a3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tracker_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_night_game_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["game_night_game_id"], ["gamenightgames.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_night_game_id"),
    )

    op.create_table(
        "tracker_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracker_session_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("starting_value", sa.Integer(), server_default="0"),
        sa.Column("is_score_field", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.ForeignKeyConstraint(["tracker_session_id"], ["tracker_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Enforce exactly one score field per session
    op.execute("""
        CREATE UNIQUE INDEX uq_one_score_field
        ON tracker_fields (tracker_session_id)
        WHERE is_score_field = true
    """)

    op.create_table(
        "tracker_teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracker_session_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["tracker_session_id"], ["tracker_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "tracker_team_players",
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["tracker_teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("team_id", "player_id"),
    )

    op.create_table(
        "tracker_values",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracker_session_id", sa.Integer(), nullable=False),
        sa.Column("tracker_field_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("value", sa.Text(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["tracker_session_id"], ["tracker_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tracker_field_id"], ["tracker_fields.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["tracker_teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # NULLS NOT DISTINCT so global fields (both NULLs) are also deduplicated (PostgreSQL 15+)
    op.execute("""
        ALTER TABLE tracker_values
        ADD CONSTRAINT uq_tracker_value
        UNIQUE NULLS NOT DISTINCT (tracker_field_id, player_id, team_id)
    """)
    op.create_index("ix_tracker_values_field_id", "tracker_values", ["tracker_field_id"])
    op.create_index("ix_tracker_values_player_id", "tracker_values", ["player_id"])


def downgrade():
    op.drop_table("tracker_team_players")
    op.drop_table("tracker_values")
    op.drop_table("tracker_teams")
    op.drop_table("tracker_fields")
    op.drop_table("tracker_sessions")
```

- [ ] **Step 2: Verify migration applies cleanly**

```bash
flask db upgrade
```

Expected: no errors, all 5 tables created.

- [ ] **Step 3: Commit**

```bash
git add migrations/versions/
git commit -m "feat: migration — add tracker tables with NULLS NOT DISTINCT and partial unique index"
```

---

## Task 3: tracker_services — create_session, get_or_create_configuring_session, discard_session

**Files:**
- Create: `app/services/tracker_services.py`
- Modify: `tests/services/test_tracker_services.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/services/test_tracker_services.py`:

```python
import pytest
from app.extensions import db as _db
from app.models import Game, GameNight, GameNightGame, Person, Player, TrackerSession, TrackerField, TrackerValue
import datetime
import uuid


@pytest.fixture()
def tracker_night(app, db):
    """A game night with one game and two players."""
    with app.app_context():
        game = Game(name=f"TG {uuid.uuid4().hex[:4]}", bgg_id=None)
        gn = GameNight(date=datetime.date(2024, 1, 1), final=False)
        _db.session.add_all([game, gn])
        _db.session.flush()

        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.flush()

        p1 = Person(first_name="A", last_name="A", email=f"a_{uuid.uuid4().hex[:4]}@t.invalid")
        p2 = Person(first_name="B", last_name="B", email=f"b_{uuid.uuid4().hex[:4]}@t.invalid")
        _db.session.add_all([p1, p2])
        _db.session.flush()

        pl1 = Player(game_night_id=gn.id, people_id=p1.id)
        pl2 = Player(game_night_id=gn.id, people_id=p2.id)
        _db.session.add_all([pl1, pl2])
        _db.session.commit()

        yield {"gng_id": gng.id, "gn_id": gn.id, "pl1_id": pl1.id, "pl2_id": pl2.id,
               "game": game, "gn": gn, "gng": gng, "p1": p1, "p2": p2}

        _db.session.rollback()
        TrackerSession.query.filter_by(game_night_game_id=gng.id).delete()
        _db.session.delete(pl1)
        _db.session.delete(pl2)
        _db.session.delete(p1)
        _db.session.delete(p2)
        _db.session.delete(gng)
        _db.session.delete(gn)
        _db.session.delete(game)
        _db.session.commit()


def test_get_or_create_configuring_session_creates_new(app, db, tracker_night):
    from app.services.tracker_services import get_or_create_configuring_session
    with app.app_context():
        session = get_or_create_configuring_session(tracker_night["gng_id"])
        assert session.status == "configuring"
        assert session.mode == "individual"
        assert session.game_night_game_id == tracker_night["gng_id"]


def test_get_or_create_configuring_session_returns_existing(app, db, tracker_night):
    from app.services.tracker_services import get_or_create_configuring_session
    with app.app_context():
        s1 = get_or_create_configuring_session(tracker_night["gng_id"])
        s2 = get_or_create_configuring_session(tracker_night["gng_id"])
        assert s1.id == s2.id


def test_discard_session_removes_session(app, db, tracker_night):
    from app.services.tracker_services import get_or_create_configuring_session, discard_session
    with app.app_context():
        session = get_or_create_configuring_session(tracker_night["gng_id"])
        sid = session.id
        discard_session(sid)
        assert TrackerSession.query.get(sid) is None
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/services/test_tracker_services.py -k "configuring or discard_session" -v
```

Expected: `ImportError: cannot import name 'get_or_create_configuring_session'`

- [ ] **Step 3: Create app/services/tracker_services.py**

```python
from app.extensions import db
from app.models import (
    Player,
    Result,
    TrackerField,
    TrackerSession,
    TrackerTeam,
    TrackerValue,
    tracker_team_players,
)


def get_or_create_configuring_session(game_night_game_id):
    """Return the existing configuring session or create a fresh one."""
    session = TrackerSession.query.filter_by(
        game_night_game_id=game_night_game_id, status="configuring"
    ).first()
    if session:
        return session
    session = TrackerSession(
        game_night_game_id=game_night_game_id,
        mode="individual",
        status="configuring",
    )
    db.session.add(session)
    db.session.commit()
    return session


def discard_session(session_id):
    """Delete a tracker session and all its children (cascade handles FK children)."""
    session = TrackerSession.query.get(session_id)
    if session:
        db.session.delete(session)
        db.session.commit()
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/services/test_tracker_services.py -k "configuring or discard_session" -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add app/services/tracker_services.py tests/services/test_tracker_services.py
git commit -m "feat: tracker_services scaffold — get_or_create_configuring_session, discard_session"
```

---

## Task 4: tracker_services — add_field, launch_session

**Files:**
- Modify: `app/services/tracker_services.py`
- Modify: `tests/services/test_tracker_services.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/services/test_tracker_services.py`:

```python
def test_add_field_creates_tracker_field(app, db, tracker_night):
    from app.services.tracker_services import get_or_create_configuring_session, add_field
    with app.app_context():
        session = get_or_create_configuring_session(tracker_night["gng_id"])
        field = add_field(session.id, type="counter", label="Victory Points", starting_value=0, is_score_field=True)
        assert field.label == "Victory Points"
        assert field.type == "counter"
        assert field.is_score_field is True
        assert TrackerField.query.filter_by(tracker_session_id=session.id).count() == 1


def test_launch_session_seeds_values_for_individual(app, db, tracker_night):
    from app.services.tracker_services import get_or_create_configuring_session, add_field, launch_session
    with app.app_context():
        session = get_or_create_configuring_session(tracker_night["gng_id"])
        add_field(session.id, type="counter", label="VP", starting_value=5, is_score_field=True)
        add_field(session.id, type="checkbox", label="Has Crown", starting_value=0, is_score_field=False)
        add_field(session.id, type="global_counter", label="Round", starting_value=1, is_score_field=False)

        launch_session(session.id, mode="individual", teams_data=[],
                       player_ids=[tracker_night["pl1_id"], tracker_night["pl2_id"]])

        session = TrackerSession.query.get(session.id)
        assert session.status == "active"
        assert session.mode == "individual"

        # counter and checkbox → 2 players × 2 fields = 4 per-player values
        # global_counter → 1 global value
        values = TrackerValue.query.filter_by(tracker_session_id=session.id).all()
        assert len(values) == 5

        # Per-player counter starts at 5
        vp_field = TrackerField.query.filter_by(tracker_session_id=session.id, label="VP").first()
        vp_values = TrackerValue.query.filter_by(tracker_field_id=vp_field.id).all()
        assert all(v.value == "5" for v in vp_values)

        # Global counter starts at 1
        round_field = TrackerField.query.filter_by(tracker_session_id=session.id, label="Round").first()
        round_val = TrackerValue.query.filter_by(tracker_field_id=round_field.id).first()
        assert round_val.value == "1"
        assert round_val.player_id is None
        assert round_val.team_id is None
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/services/test_tracker_services.py -k "add_field or launch_session" -v
```

Expected: `ImportError: cannot import name 'add_field'`

- [ ] **Step 3: Add add_field and launch_session to tracker_services.py**

```python
GLOBAL_FIELD_TYPES = {"global_counter", "global_notes"}
PER_PLAYER_FIELD_TYPES = {"counter", "checkbox", "player_notes"}


def add_field(session_id, *, type, label, starting_value=0, is_score_field=False):
    """Add a TrackerField to a configuring session. Does not seed values yet."""
    existing_count = TrackerField.query.filter_by(tracker_session_id=session_id).count()
    field = TrackerField(
        tracker_session_id=session_id,
        type=type,
        label=label,
        starting_value=starting_value if type in ("counter", "global_counter") else 0,
        is_score_field=is_score_field,
        sort_order=existing_count,
    )
    db.session.add(field)
    db.session.commit()
    return field


def launch_session(session_id, *, mode, teams_data, player_ids):
    """
    Activate a configuring session. Seeds all TrackerValue rows.

    teams_data: list of {"name": str, "player_ids": [int]} — only used when mode="teams"
    player_ids: list of Player.id — all players for the game night (individual mode)
    """
    session = TrackerSession.query.get_or_404(session_id)
    session.mode = mode
    session.status = "active"

    # Build teams if needed
    entity_map = []  # list of (player_id, team_id) pairs representing entities
    if mode == "teams":
        for td in teams_data:
            team = TrackerTeam(tracker_session_id=session_id, name=td["name"])
            db.session.add(team)
            db.session.flush()
            for pid in td["player_ids"]:
                db.session.execute(
                    tracker_team_players.insert().values(team_id=team.id, player_id=pid)
                )
            entity_map.append(("team", team.id))
    else:
        entity_map = [("player", pid) for pid in player_ids]

    # Seed TrackerValue rows
    for field in TrackerField.query.filter_by(tracker_session_id=session_id).all():
        if field.type in GLOBAL_FIELD_TYPES:
            _seed_value(session_id, field, player_id=None, team_id=None)
        else:
            for entity_type, entity_id in entity_map:
                if entity_type == "player":
                    _seed_value(session_id, field, player_id=entity_id, team_id=None)
                else:
                    _seed_value(session_id, field, player_id=None, team_id=entity_id)

    db.session.commit()
    return session


def _seed_value(session_id, field, *, player_id, team_id):
    initial = str(field.starting_value) if field.type in ("counter", "global_counter") else (
        "false" if field.type == "checkbox" else ""
    )
    v = TrackerValue(
        tracker_session_id=session_id,
        tracker_field_id=field.id,
        player_id=player_id,
        team_id=team_id,
        value=initial,
    )
    db.session.add(v)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/services/test_tracker_services.py -k "add_field or launch_session" -v
```

Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add app/services/tracker_services.py tests/services/test_tracker_services.py
git commit -m "feat: tracker_services — add_field, launch_session with value seeding"
```

---

## Task 5: tracker_services — update_value

**Files:**
- Modify: `app/services/tracker_services.py`
- Modify: `tests/services/test_tracker_services.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/services/test_tracker_services.py`:

```python
@pytest.fixture()
def active_session(app, db, tracker_night):
    """A launched tracker session with VP counter (score) and a checkbox."""
    from app.services.tracker_services import get_or_create_configuring_session, add_field, launch_session
    with app.app_context():
        session = get_or_create_configuring_session(tracker_night["gng_id"])
        add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
        add_field(session.id, type="checkbox", label="Crown", starting_value=0, is_score_field=False)
        launch_session(session.id, mode="individual", teams_data=[],
                       player_ids=[tracker_night["pl1_id"], tracker_night["pl2_id"]])
        yield {"session_id": session.id, "pl1_id": tracker_night["pl1_id"],
               "pl2_id": tracker_night["pl2_id"], "gng_id": tracker_night["gng_id"]}


def test_update_value_increments_counter(app, db, active_session):
    from app.services.tracker_services import update_value
    from app.models import TrackerField
    with app.app_context():
        sid = active_session["session_id"]
        field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
        update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=1)
        update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=1)
        val = TrackerValue.query.filter_by(tracker_field_id=field.id, player_id=active_session["pl1_id"]).first()
        assert val.value == "2"


def test_update_value_can_go_negative(app, db, active_session):
    from app.services.tracker_services import update_value
    from app.models import TrackerField
    with app.app_context():
        sid = active_session["session_id"]
        field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
        update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=-1)
        val = TrackerValue.query.filter_by(tracker_field_id=field.id, player_id=active_session["pl1_id"]).first()
        assert val.value == "-1"


def test_update_value_sets_checkbox(app, db, active_session):
    from app.services.tracker_services import update_value
    from app.models import TrackerField
    with app.app_context():
        sid = active_session["session_id"]
        field = TrackerField.query.filter_by(tracker_session_id=sid, label="Crown").first()
        update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], value="true")
        val = TrackerValue.query.filter_by(tracker_field_id=field.id, player_id=active_session["pl1_id"]).first()
        assert val.value == "true"


def test_update_value_rejects_invalid_counter_value(app, db, active_session):
    from app.services.tracker_services import update_value
    from app.models import TrackerField
    with app.app_context():
        sid = active_session["session_id"]
        field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
        with pytest.raises(ValueError):
            update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], value="banana")
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/services/test_tracker_services.py -k "update_value" -v
```

Expected: `ImportError: cannot import name 'update_value'`

- [ ] **Step 3: Add update_value to tracker_services.py**

```python
def update_value(session_id, field_id, *, entity_type, entity_id=None, delta=None, value=None):
    """
    Update a single TrackerValue.

    entity_type: "player", "team", or "global"
    entity_id: Player.id or TrackerTeam.id (ignored for global)
    delta: +1 or -1 for counter fields
    value: new string value for checkbox/notes fields
    """
    field = TrackerField.query.get_or_404(field_id)

    player_id = entity_id if entity_type == "player" else None
    team_id = entity_id if entity_type == "team" else None

    tv = TrackerValue.query.filter_by(
        tracker_field_id=field_id,
        player_id=player_id,
        team_id=team_id,
    ).first_or_404()

    if delta is not None:
        # Counter update
        current = int(tv.value)
        tv.value = str(current + delta)
    elif value is not None:
        # Validate type
        if field.type in ("counter", "global_counter"):
            try:
                int(value)
            except ValueError:
                raise ValueError(f"Counter field '{field.label}' requires an integer value, got: {value!r}")
        elif field.type == "checkbox":
            if value not in ("true", "false"):
                raise ValueError(f"Checkbox field '{field.label}' requires 'true' or 'false', got: {value!r}")
        tv.value = value

    db.session.commit()
    return tv
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/services/test_tracker_services.py -k "update_value" -v
```

Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add app/services/tracker_services.py tests/services/test_tracker_services.py
git commit -m "feat: tracker_services — update_value with type validation"
```

---

## Task 6: tracker_services — compute_rankings, save_results

**Files:**
- Modify: `app/services/tracker_services.py`
- Modify: `tests/services/test_tracker_services.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/services/test_tracker_services.py`:

```python
def test_compute_rankings_sorts_descending(app, db, active_session):
    from app.services.tracker_services import update_value, compute_rankings
    from app.models import TrackerField
    with app.app_context():
        sid = active_session["session_id"]
        field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
        update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=10)
        update_value(sid, field.id, entity_type="player", entity_id=active_session["pl2_id"], delta=7)
        rankings = compute_rankings(sid)
        assert rankings[0]["player_id"] == active_session["pl1_id"]
        assert rankings[0]["position"] == 1
        assert rankings[0]["score"] == 10
        assert rankings[1]["player_id"] == active_session["pl2_id"]
        assert rankings[1]["position"] == 2
        assert rankings[1]["score"] == 7


def test_compute_rankings_ties_share_position(app, db, active_session):
    from app.services.tracker_services import update_value, compute_rankings
    from app.models import TrackerField
    with app.app_context():
        sid = active_session["session_id"]
        field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
        update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=5)
        update_value(sid, field.id, entity_type="player", entity_id=active_session["pl2_id"], delta=5)
        rankings = compute_rankings(sid)
        assert rankings[0]["position"] == 1
        assert rankings[1]["position"] == 1


def test_save_results_creates_result_rows(app, db, active_session):
    from app.services.tracker_services import update_value, compute_rankings, save_results
    from app.models import TrackerField, Result, Player
    with app.app_context():
        sid = active_session["session_id"]
        field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
        gng_id = active_session["gng_id"]
        update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=10)
        update_value(sid, field.id, entity_type="player", entity_id=active_session["pl2_id"], delta=7)
        rankings = compute_rankings(sid)
        save_results(sid, rankings)
        results = Result.query.filter_by(game_night_game_id=gng_id).all()
        assert len(results) == 2
        winner = next(r for r in results if r.player_id == active_session["pl1_id"])
        assert winner.position == 1
        assert winner.score == 10
        session = TrackerSession.query.get(sid)
        assert session.status == "completed"


def test_save_results_upserts_existing_rows(app, db, active_session):
    from app.services.tracker_services import update_value, compute_rankings, save_results
    from app.models import TrackerField, Result
    with app.app_context():
        sid = active_session["session_id"]
        field = TrackerField.query.filter_by(tracker_session_id=sid, label="VP").first()
        gng_id = active_session["gng_id"]
        update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=10)
        rankings = compute_rankings(sid)
        save_results(sid, rankings)
        # Save again with different score
        session = TrackerSession.query.get(sid)
        session.status = "active"
        _db.session.commit()
        update_value(sid, field.id, entity_type="player", entity_id=active_session["pl1_id"], delta=5)
        rankings = compute_rankings(sid)
        save_results(sid, rankings)
        results = Result.query.filter_by(game_night_game_id=gng_id).all()
        # No duplicate rows
        assert len(results) == 2
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/services/test_tracker_services.py -k "rankings or save_results" -v
```

Expected: `ImportError: cannot import name 'compute_rankings'`

- [ ] **Step 3: Add compute_rankings and save_results to tracker_services.py**

```python
def compute_rankings(session_id):
    """
    Return a list of dicts sorted descending by score field value.
    Each dict: {"player_id": int, "team_id": int|None, "position": int, "score": int}
    Ties share a position with a gap (two 1sts → next is 3rd).
    """
    session = TrackerSession.query.get_or_404(session_id)
    score_field = TrackerField.query.filter_by(
        tracker_session_id=session_id, is_score_field=True
    ).first_or_404()

    values = (
        TrackerValue.query
        .filter_by(tracker_field_id=score_field.id)
        .all()
    )
    # Sort descending by integer score
    sorted_vals = sorted(values, key=lambda v: int(v.value), reverse=True)

    rankings = []
    pos = 1
    for i, v in enumerate(sorted_vals):
        if i > 0 and int(v.value) < int(sorted_vals[i - 1].value):
            pos = i + 1
        rankings.append({
            "player_id": v.player_id,
            "team_id": v.team_id,
            "position": pos,
            "score": int(v.value),
        })
    return rankings


def save_results(session_id, rankings):
    """
    Write Result rows using fetch-or-create upsert. Mirrors log_results pattern.
    In team mode, all team members get the team's position and score.
    Marks session status = "completed".
    """
    session = TrackerSession.query.get_or_404(session_id)
    gng_id = session.game_night_game.id

    for entry in rankings:
        if entry["player_id"] is not None:
            # Individual mode
            _upsert_result(gng_id, entry["player_id"], entry["position"], entry["score"])
        elif entry["team_id"] is not None:
            # Team mode — award same position/score to every team member
            team = TrackerTeam.query.get(entry["team_id"])
            for player in team.players:
                _upsert_result(gng_id, player.id, entry["position"], entry["score"])

    session.status = "completed"
    db.session.commit()


def _upsert_result(game_night_game_id, player_id, position, score):
    result = Result.query.filter_by(
        game_night_game_id=game_night_game_id, player_id=player_id
    ).first()
    if not result:
        result = Result(game_night_game_id=game_night_game_id, player_id=player_id)
        db.session.add(result)
    result.position = position
    result.score = score
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/services/test_tracker_services.py -v
```

Expected: all service tests PASSED

- [ ] **Step 5: Commit**

```bash
git add app/services/tracker_services.py tests/services/test_tracker_services.py
git commit -m "feat: tracker_services — compute_rankings (ties + gap), save_results (upsert)"
```

---

## Task 7: Blueprint — registration + setup routes

**Files:**
- Create: `app/blueprints/tracker.py`
- Modify: `app/blueprints/__init__.py`
- Modify: `app/__init__.py`
- Create: `tests/blueprints/test_tracker.py`

- [ ] **Step 1: Write failing blueprint tests**

Create `tests/blueprints/test_tracker.py`:

```python
import datetime
import uuid

import pytest

from app.extensions import db as _db
from app.models import Game, GameNight, GameNightGame, Person, Player, TrackerSession, TrackerField


@pytest.fixture()
def auth_tracker_client(app, db):
    """Admin client with a game night + game set up."""
    from app.extensions import bcrypt
    from app.models import Poll
    _db.session.rollback()
    existing = Person.query.filter_by(email="tracker_admin@example.com").first()
    if existing:
        for poll in Poll.query.filter_by(created_by=existing.id).all():
            _db.session.delete(poll)
        _db.session.flush()
        _db.session.delete(existing)
        _db.session.commit()

    admin = Person(
        first_name="Tracker", last_name="Admin", email="tracker_admin@example.com",
        password=bcrypt.generate_password_hash("password", rounds=4).decode("utf-8"),
        admin=True, owner=False,
    )
    _db.session.add(admin)
    _db.session.flush()

    game = Game(name=f"TG {uuid.uuid4().hex[:4]}", bgg_id=None)
    gn = GameNight(date=datetime.date(2024, 6, 1), final=False)
    _db.session.add_all([game, gn])
    _db.session.flush()

    gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
    _db.session.add(gng)
    _db.session.flush()

    player = Player(game_night_id=gn.id, people_id=admin.id)
    _db.session.add(player)
    _db.session.commit()

    with app.test_client() as client:
        client.post("/login", data={"email": "tracker_admin@example.com", "password": "password"})
        yield {"client": client, "gng_id": gng.id, "gn_id": gn.id,
               "player_id": player.id, "admin_id": admin.id, "game": game, "gn": gn, "gng": gng}

    _db.session.rollback()
    TrackerSession.query.filter_by(game_night_game_id=gng.id).delete()
    _db.session.delete(player)
    _db.session.delete(gng)
    _db.session.delete(gn)
    _db.session.delete(game)
    existing = Person.query.filter_by(email="tracker_admin@example.com").first()
    if existing:
        _db.session.delete(existing)
    _db.session.commit()


def test_setup_get_creates_configuring_session(auth_tracker_client):
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    resp = c.get(f"/game_night/{gng_id}/tracker/new")
    assert resp.status_code == 200
    session = TrackerSession.query.filter_by(game_night_game_id=gng_id).first()
    assert session is not None
    assert session.status == "configuring"


def test_setup_get_unauthenticated_redirects(client, db, seed_data):
    resp = client.get(f"/game_night/{seed_data['game_night_id']}/tracker/new")
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/blueprints/test_tracker.py -v
```

Expected: `404` or blueprint not registered error

- [ ] **Step 3: Create app/blueprints/tracker.py with setup routes**

```python
from flask import abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import GameNight, GameNightGame, Player, TrackerField, TrackerSession, TrackerValue
from app.services import tracker_services
from flask import Blueprint

tracker_bp = Blueprint("tracker", __name__)


def _get_session_or_404(session_id):
    return TrackerSession.query.get_or_404(session_id)


def _assert_participant_or_admin(session):
    """Abort 403 if current user is not a participant of the session's game night or admin."""
    if current_user.admin:
        return
    gng = session.game_night_game
    is_participant = Player.query.filter_by(
        game_night_id=gng.game_night_id, people_id=current_user.id
    ).first()
    if not is_participant:
        abort(403)


@tracker_bp.route("/game_night/<int:gng_id>/tracker/new")
@login_required
def setup_tracker(gng_id):
    gng = GameNightGame.query.get_or_404(gng_id)
    gn = gng.game_night
    if gn.final:
        abort(400, "Cannot start a tracker for a finalized game night.")
    # Resume active session if one exists
    active = TrackerSession.query.filter_by(game_night_game_id=gng_id, status="active").first()
    if active:
        return redirect(url_for("tracker.live_tracker", session_id=active.id))
    session = tracker_services.get_or_create_configuring_session(gng_id)
    players = Player.query.filter_by(game_night_id=gn.id).all()
    fields = TrackerField.query.filter_by(tracker_session_id=session.id).order_by(TrackerField.sort_order).all()
    return render_template("tracker_setup.html", session=session, gng=gng, gn=gn, players=players, fields=fields)


@tracker_bp.route("/game_night/<int:gng_id>/tracker", methods=["POST"])
@login_required
def launch_tracker(gng_id):
    gng = GameNightGame.query.get_or_404(gng_id)
    session_id = int(request.form["session_id"])
    session = TrackerSession.query.get_or_404(session_id)
    mode = request.form.get("mode", "individual")
    player_ids = [int(pid) for pid in request.form.getlist("player_ids")]

    teams_data = []
    if mode == "teams":
        team_names = request.form.getlist("team_names")
        for i, name in enumerate(team_names):
            t_player_ids = [int(pid) for pid in request.form.getlist(f"team_{i}_player_ids")]
            teams_data.append({"name": name, "player_ids": t_player_ids})

    tracker_services.launch_session(session_id, mode=mode, teams_data=teams_data, player_ids=player_ids)
    return redirect(url_for("tracker.live_tracker", session_id=session_id))
```

- [ ] **Step 4: Register blueprint**

In `app/blueprints/__init__.py`, add:
```python
from .tracker import tracker_bp as tracker_bp
```

In `app/__init__.py`, inside `register_blueprints`, add:
```python
    app.register_blueprint(blueprints.tracker_bp)
```

- [ ] **Step 5: Run tests to verify they pass**

```
pytest tests/blueprints/test_tracker.py::test_setup_get_creates_configuring_session tests/blueprints/test_tracker.py::test_setup_get_unauthenticated_redirects -v
```

Expected: 2 PASSED

- [ ] **Step 6: Commit**

```bash
git add app/blueprints/tracker.py app/blueprints/__init__.py app/__init__.py tests/blueprints/test_tracker.py
git commit -m "feat: tracker blueprint — setup routes + registration"
```

---

## Task 8: Blueprint — live tracker, field-add, value update (HTMX)

**Files:**
- Modify: `app/blueprints/tracker.py`
- Modify: `tests/blueprints/test_tracker.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/blueprints/test_tracker.py`:

```python
def test_live_tracker_loads(auth_tracker_client):
    from app.services.tracker_services import get_or_create_configuring_session, add_field, launch_session
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    with auth_tracker_client["gn"].__class__._sa_class_manager.mapper.persist_selectable.bind.connect():
        pass  # ensure app context is active via the client
    session = get_or_create_configuring_session(gng_id)
    add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
    launch_session(session.id, mode="individual", teams_data=[],
                   player_ids=[auth_tracker_client["player_id"]])
    resp = c.get(f"/tracker/{session.id}")
    assert resp.status_code == 200
    assert b"VP" in resp.data


def test_add_field_htmx_returns_fragment(auth_tracker_client):
    from app.services.tracker_services import get_or_create_configuring_session
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    resp = c.post(f"/tracker/{session.id}/field", data={
        "type": "counter", "label": "Life", "starting_value": "20", "is_score_field": "true"
    })
    assert resp.status_code == 200
    assert b"Life" in resp.data
    assert TrackerField.query.filter_by(tracker_session_id=session.id, label="Life").first() is not None


def test_value_update_htmx_returns_cell(auth_tracker_client):
    from app.services.tracker_services import get_or_create_configuring_session, add_field, launch_session
    from app.models import TrackerValue
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    field = add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
    launch_session(session.id, mode="individual", teams_data=[],
                   player_ids=[auth_tracker_client["player_id"]])
    resp = c.post(f"/tracker/{session.id}/value", data={
        "field_id": str(field.id),
        "entity_type": "player",
        "entity_id": str(auth_tracker_client["player_id"]),
        "delta": "1",
    })
    assert resp.status_code == 200
    val = TrackerValue.query.filter_by(tracker_field_id=field.id, player_id=auth_tracker_client["player_id"]).first()
    assert val.value == "1"
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/blueprints/test_tracker.py -k "live_tracker or add_field_htmx or value_update" -v
```

Expected: 404s (routes not yet defined)

- [ ] **Step 3: Add routes to tracker.py**

```python
@tracker_bp.route("/tracker/<int:session_id>")
@login_required
def live_tracker(session_id):
    session = _get_session_or_404(session_id)
    _assert_participant_or_admin(session)
    gn = session.game_night_game.game_night
    if gn.final:
        return redirect(url_for("game_night.view_game_night", game_night_id=gn.id))
    # Batch-load all values for this session in one query
    all_values = TrackerValue.query.filter_by(tracker_session_id=session_id).all()
    # Build value lookup: {(field_id, player_id, team_id): TrackerValue}
    value_map = {(v.tracker_field_id, v.player_id, v.team_id): v for v in all_values}
    players = Player.query.filter_by(game_night_id=gn.id).all() if session.mode == "individual" else []
    teams = session.teams if session.mode == "teams" else []
    global_fields = [f for f in session.fields if f.type in ("global_counter", "global_notes")]
    player_fields = [f for f in session.fields if f.type not in ("global_counter", "global_notes")]
    return render_template(
        "tracker_live.html",
        session=session, gn=gn, players=players, teams=teams,
        global_fields=global_fields, player_fields=player_fields, value_map=value_map,
    )


@tracker_bp.route("/tracker/<int:session_id>/field", methods=["POST"])
@login_required
def add_field(session_id):
    session = _get_session_or_404(session_id)
    _assert_participant_or_admin(session)
    field_type = request.form["type"]
    label = request.form["label"]
    starting_value = int(request.form.get("starting_value", 0))
    is_score_field = request.form.get("is_score_field", "false").lower() == "true"
    field = tracker_services.add_field(
        session_id, type=field_type, label=label,
        starting_value=starting_value, is_score_field=is_score_field,
    )
    return render_template("_tracker_field_row.html", field=field, session=session)


@tracker_bp.route("/tracker/<int:session_id>/value", methods=["POST"])
@login_required
def update_value(session_id):
    session = _get_session_or_404(session_id)
    _assert_participant_or_admin(session)
    field_id = int(request.form["field_id"])
    entity_type = request.form["entity_type"]
    entity_id = int(request.form["entity_id"]) if request.form.get("entity_id") else None
    delta = int(request.form["delta"]) if request.form.get("delta") else None
    value = request.form.get("value")
    tv = tracker_services.update_value(
        session_id, field_id, entity_type=entity_type, entity_id=entity_id,
        delta=delta, value=value,
    )
    field = TrackerField.query.get(field_id)
    return render_template("_tracker_cell.html", tv=tv, field=field, session=session,
                           entity_type=entity_type, entity_id=entity_id)
```

- [ ] **Step 4: Run tests to verify they pass**

```
pytest tests/blueprints/test_tracker.py -k "live_tracker or add_field_htmx or value_update" -v
```

Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add app/blueprints/tracker.py tests/blueprints/test_tracker.py
git commit -m "feat: tracker blueprint — live tracker page, field-add HTMX, value update HTMX"
```

---

## Task 9: Blueprint — end-game, save, discard routes

**Files:**
- Modify: `app/blueprints/tracker.py`
- Modify: `tests/blueprints/test_tracker.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/blueprints/test_tracker.py`:

```python
def test_end_game_get_returns_rankings(auth_tracker_client):
    from app.services.tracker_services import get_or_create_configuring_session, add_field, launch_session, update_value
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    field = add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
    launch_session(session.id, mode="individual", teams_data=[],
                   player_ids=[auth_tracker_client["player_id"]])
    update_value(session.id, field.id, entity_type="player",
                 entity_id=auth_tracker_client["player_id"], delta=5)
    resp = c.get(f"/tracker/{session.id}/end")
    assert resp.status_code == 200
    assert b"VP" in resp.data
    session_obj = TrackerSession.query.get(session.id)
    assert session_obj.status == "active"  # GET does not mutate status


def test_save_results_marks_completed(auth_tracker_client):
    from app.services.tracker_services import get_or_create_configuring_session, add_field, launch_session, update_value, compute_rankings
    from app.models import Result
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    field = add_field(session.id, type="counter", label="VP", starting_value=0, is_score_field=True)
    launch_session(session.id, mode="individual", teams_data=[],
                   player_ids=[auth_tracker_client["player_id"]])
    update_value(session.id, field.id, entity_type="player",
                 entity_id=auth_tracker_client["player_id"], delta=5)
    rankings = compute_rankings(session.id)
    resp = c.post(f"/tracker/{session.id}/save", data={
        f"position_{auth_tracker_client['player_id']}": "1",
        f"score_{auth_tracker_client['player_id']}": "5",
    })
    assert resp.status_code == 302
    session_obj = TrackerSession.query.get(session.id)
    assert session_obj.status == "completed"
    result = Result.query.filter_by(game_night_game_id=gng_id, player_id=auth_tracker_client["player_id"]).first()
    assert result is not None
    assert result.position == 1


def test_discard_deletes_session(auth_tracker_client):
    from app.services.tracker_services import get_or_create_configuring_session
    c = auth_tracker_client["client"]
    gng_id = auth_tracker_client["gng_id"]
    session = get_or_create_configuring_session(gng_id)
    sid = session.id
    resp = c.post(f"/tracker/{sid}/discard")
    assert resp.status_code == 302
    assert TrackerSession.query.get(sid) is None
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/blueprints/test_tracker.py -k "end_game or save_results or discard" -v
```

Expected: 404s

- [ ] **Step 3: Add end/save/discard routes to tracker.py**

```python
@tracker_bp.route("/tracker/<int:session_id>/end")
@login_required
def end_game(session_id):
    session = _get_session_or_404(session_id)
    _assert_participant_or_admin(session)
    rankings = tracker_services.compute_rankings(session_id)
    gng = session.game_night_game
    has_existing_results = gng.results  # non-empty list = pre-existing results
    return render_template(
        "tracker_confirm.html",
        session=session, rankings=rankings,
        has_existing_results=bool(has_existing_results),
    )


@tracker_bp.route("/tracker/<int:session_id>/save", methods=["POST"])
@login_required
def save_results(session_id):
    session = _get_session_or_404(session_id)
    _assert_participant_or_admin(session)
    # Build rankings from the confirmed positions submitted by the host
    rankings = []
    for key, pos in request.form.items():
        if key.startswith("position_"):
            player_id = int(key.split("_", 1)[1])
            score = int(request.form.get(f"score_{player_id}", 0))
            rankings.append({"player_id": player_id, "team_id": None,
                              "position": int(pos), "score": score})
    tracker_services.save_results(session_id, rankings)
    gn_id = session.game_night_game.game_night_id
    return redirect(url_for("game_night.view_game_night", game_night_id=gn_id))


@tracker_bp.route("/tracker/<int:session_id>/discard", methods=["POST"])
@login_required
def discard_tracker(session_id):
    session = _get_session_or_404(session_id)
    _assert_participant_or_admin(session)
    gn_id = session.game_night_game.game_night_id
    tracker_services.discard_session(session_id)
    return redirect(url_for("game_night.view_game_night", game_night_id=gn_id))
```

- [ ] **Step 4: Run all blueprint tests**

```
pytest tests/blueprints/test_tracker.py -v
```

Expected: all PASSED

- [ ] **Step 5: Commit**

```bash
git add app/blueprints/tracker.py tests/blueprints/test_tracker.py
git commit -m "feat: tracker blueprint — end-game, save results, discard routes"
```

---

## Task 10: Templates — tracker_setup.html

**Files:**
- Create: `app/templates/tracker_setup.html`

- [ ] **Step 1: Create tracker_setup.html**

```html
{% extends "base.html" %}

{% block title %}Set Up Tracker — {{ gng.game.name }}{% endblock %}

{% block head %}
<script src="https://cdn.jsdelivr.net/npm/sortablejs@1.15.2/Sortable.min.js"></script>
{% endblock %}

{% block content %}
<div class="max-w-2xl mx-auto space-y-6">
  <div>
    <a href="{{ url_for('game_night.view_game_night', game_night_id=gn.id) }}"
       class="text-sm text-stone-500 hover:text-red-600 inline-block mb-3">&larr; Back to Game Night</a>
    <h1 class="text-2xl font-bold text-stone-800">Set Up Tracker</h1>
    <p class="text-stone-500 text-sm mt-1">{{ gng.game.name }} &mdash; {{ gn.date.strftime('%B %d, %Y') }}</p>
  </div>

  <!-- Mode -->
  <div class="bg-white rounded-xl shadow-sm border border-stone-200 p-5">
    <h2 class="font-semibold text-stone-700 mb-3">Play Mode</h2>
    <div class="flex gap-4">
      <label class="flex items-center gap-2 cursor-pointer">
        <input type="radio" name="mode_choice" value="individual" checked
               onchange="document.getElementById('teams-section').classList.add('hidden')"
               class="accent-red-600"> Individual
      </label>
      <label class="flex items-center gap-2 cursor-pointer">
        <input type="radio" name="mode_choice" value="teams"
               onchange="document.getElementById('teams-section').classList.remove('hidden')"
               class="accent-red-600"> Teams
      </label>
    </div>
  </div>

  <!-- Tracking Fields -->
  <div class="bg-white rounded-xl shadow-sm border border-stone-200 p-5">
    <h2 class="font-semibold text-stone-700 mb-1">Tracking Fields</h2>
    <p class="text-xs text-stone-500 mb-4">Add the stats you want to track. Drag to reorder. At least one Counter must be marked as the Score field.</p>

    <ul id="fields-list" class="space-y-2 mb-4">
      {% for field in fields %}
        {% include "_tracker_field_row.html" %}
      {% endfor %}
    </ul>

    <!-- Add Field Form (HTMX) -->
    <div class="border border-dashed border-stone-300 rounded-lg p-4">
      <div class="grid grid-cols-2 gap-3 mb-3">
        <div>
          <label class="text-xs font-medium text-stone-600 block mb-1">Type</label>
          <select id="new-field-type" class="w-full border border-stone-300 rounded px-3 py-1.5 text-sm">
            <option value="counter">Counter (per player)</option>
            <option value="checkbox">Checkbox (per player)</option>
            <option value="player_notes">Notes (per player)</option>
            <option value="global_counter">Counter (global)</option>
            <option value="global_notes">Notes (global)</option>
          </select>
        </div>
        <div>
          <label class="text-xs font-medium text-stone-600 block mb-1">Label</label>
          <input id="new-field-label" type="text" placeholder="e.g. Victory Points"
                 class="w-full border border-stone-300 rounded px-3 py-1.5 text-sm">
        </div>
        <div>
          <label class="text-xs font-medium text-stone-600 block mb-1">Starting Value</label>
          <input id="new-field-start" type="number" value="0"
                 class="w-full border border-stone-300 rounded px-3 py-1.5 text-sm">
        </div>
        <div class="flex items-end">
          <label class="flex items-center gap-2 text-sm cursor-pointer">
            <input id="new-field-score" type="checkbox" class="accent-red-600"> Score field (used for ranking)
          </label>
        </div>
      </div>
      <button
        hx-post="{{ url_for('tracker.add_field', session_id=session.id) }}"
        hx-target="#fields-list"
        hx-swap="beforeend"
        hx-include="[id^='new-field']"
        hx-vals='js:{
          "type": document.getElementById("new-field-type").value,
          "label": document.getElementById("new-field-label").value,
          "starting_value": document.getElementById("new-field-start").value,
          "is_score_field": document.getElementById("new-field-score").checked ? "true" : "false"
        }'
        class="bg-stone-800 text-white text-sm px-4 py-1.5 rounded hover:bg-stone-700">
        + Add Field
      </button>
    </div>
  </div>

  <!-- Teams section (hidden by default) -->
  <div id="teams-section" class="hidden bg-white rounded-xl shadow-sm border border-stone-200 p-5">
    <h2 class="font-semibold text-stone-700 mb-3">Teams</h2>
    <p class="text-xs text-stone-500 mb-4">Assign each player to a team.</p>
    <div id="teams-list" class="space-y-4">
      <div class="border border-stone-200 rounded-lg p-3">
        <input type="text" name="team_names" placeholder="Team name"
               class="border border-stone-300 rounded px-3 py-1 text-sm mb-2 w-full">
        {% for player in players %}
        <label class="flex items-center gap-2 text-sm">
          <input type="checkbox" name="team_0_player_ids" value="{{ player.id }}" class="accent-red-600">
          {{ player.person.first_name }} {{ player.person.last_name }}
        </label>
        {% endfor %}
      </div>
    </div>
  </div>

  <!-- Launch Form -->
  <form action="{{ url_for('tracker.launch_tracker', gng_id=gng.id) }}" method="POST">
    <input type="hidden" name="session_id" value="{{ session.id }}">
    <input type="hidden" id="launch-mode" name="mode" value="individual">
    {% for player in players %}
    <input type="hidden" name="player_ids" value="{{ player.id }}">
    {% endfor %}
    <!-- Hidden field order for sort_order -->
    <input type="hidden" id="field-order" name="field_order" value="">
    <div class="flex gap-3">
      <button type="submit"
              class="bg-red-600 text-white font-semibold px-6 py-2 rounded-lg hover:bg-red-700">
        Launch Tracker →
      </button>
      <form action="{{ url_for('tracker.discard_tracker', session_id=session.id) }}" method="POST" class="inline">
        <button type="submit" class="text-stone-500 hover:text-stone-700 px-4 py-2 text-sm">Discard</button>
      </form>
    </div>
  </form>
</div>

<script>
  // Keep mode hidden input in sync with radio
  document.querySelectorAll('[name="mode_choice"]').forEach(r => {
    r.addEventListener('change', () => {
      document.getElementById('launch-mode').value = r.value;
    });
  });
  // SortableJS for field reordering
  new Sortable(document.getElementById('fields-list'), {
    animation: 150,
    onEnd: function() {
      const ids = [...document.querySelectorAll('#fields-list [data-field-id]')].map(el => el.dataset.fieldId);
      document.getElementById('field-order').value = ids.join(',');
    }
  });
</script>
{% endblock %}
```

- [ ] **Step 2: Smoke-test the setup page renders**

```
pytest tests/blueprints/test_tracker.py::test_setup_get_creates_configuring_session -v
```

Expected: PASSED (already passing, confirms template renders without 500)

- [ ] **Step 3: Commit**

```bash
git add app/templates/tracker_setup.html
git commit -m "feat: tracker setup page template with HTMX field-adding and SortableJS reorder"
```

---

## Task 11: Templates — tracker_live.html + _tracker_cell.html

**Files:**
- Create: `app/templates/tracker_live.html`
- Create: `app/templates/_tracker_cell.html`

- [ ] **Step 1: Create _tracker_cell.html (partial returned by HTMX value POST)**

```html
{# Partial: single tracker cell. Rendered by POST /tracker/<session_id>/value #}
{# Variables: tv, field, session, entity_type, entity_id #}
<div id="cell-{{ field.id }}-{{ entity_type }}-{{ entity_id or 'global' }}"
     class="flex items-center justify-center">
  {% if field.type in ('counter', 'global_counter') %}
    <button
      hx-post="{{ url_for('tracker.update_value', session_id=session.id) }}"
      hx-target="#cell-{{ field.id }}-{{ entity_type }}-{{ entity_id or 'global' }}"
      hx-swap="outerHTML"
      hx-vals='{"field_id": "{{ field.id }}", "entity_type": "{{ entity_type }}", "entity_id": "{{ entity_id or '' }}", "delta": "-1"}'
      class="bg-stone-700 text-stone-200 border border-stone-600 rounded w-7 h-7 text-sm hover:bg-stone-600">−</button>
    <span class="font-bold text-lg min-w-[2.5rem] text-center text-stone-100">{{ tv.value }}</span>
    <button
      hx-post="{{ url_for('tracker.update_value', session_id=session.id) }}"
      hx-target="#cell-{{ field.id }}-{{ entity_type }}-{{ entity_id or 'global' }}"
      hx-swap="outerHTML"
      hx-vals='{"field_id": "{{ field.id }}", "entity_type": "{{ entity_type }}", "entity_id": "{{ entity_id or '' }}", "delta": "1"}'
      class="bg-stone-700 text-stone-200 border border-stone-600 rounded w-7 h-7 text-sm hover:bg-stone-600">+</button>
  {% elif field.type == 'checkbox' %}
    <input type="checkbox" {% if tv.value == 'true' %}checked{% endif %}
           class="w-5 h-5 accent-blue-500 cursor-pointer"
           hx-post="{{ url_for('tracker.update_value', session_id=session.id) }}"
           hx-target="#cell-{{ field.id }}-{{ entity_type }}-{{ entity_id or 'global' }}"
           hx-swap="outerHTML"
           hx-vals='js:{"field_id": "{{ field.id }}", "entity_type": "{{ entity_type }}", "entity_id": "{{ entity_id or '' }}", "value": this.checked ? "false" : "true"}'>
  {% else %}
    {# player_notes or global_notes #}
    <input type="text" value="{{ tv.value }}"
           class="bg-stone-800 border border-stone-600 rounded px-2 py-1 text-sm text-stone-300 w-full"
           hx-post="{{ url_for('tracker.update_value', session_id=session.id) }}"
           hx-target="#cell-{{ field.id }}-{{ entity_type }}-{{ entity_id or 'global' }}"
           hx-swap="outerHTML"
           hx-trigger="change"
           hx-vals='js:{"field_id": "{{ field.id }}", "entity_type": "{{ entity_type }}", "entity_id": "{{ entity_id or '' }}", "value": this.value}'>
  {% endif %}
</div>
```

- [ ] **Step 2: Create tracker_live.html**

```html
{% extends "base.html" %}

{% block title %}Live Tracker — {{ session.game_night_game.game.name }}{% endblock %}

{% block content %}
<div class="max-w-5xl mx-auto">

  {# Global fields bar — only shown if global fields exist #}
  {% if global_fields %}
  <div class="bg-stone-900 border-b border-stone-700 px-4 py-3 flex flex-wrap gap-6 items-center">
    <span class="text-stone-500 text-xs uppercase tracking-wide font-medium">Global</span>
    {% for field in global_fields %}
      {% set tv = value_map.get((field.id, None, None)) %}
      {% if tv %}
        <div class="flex items-center gap-2">
          <span class="text-stone-300 text-sm">{{ field.label }}</span>
          {% set entity_type = "global" %}
          {% set entity_id = None %}
          {% include "_tracker_cell.html" %}
        </div>
      {% endif %}
    {% endfor %}
  </div>
  {% endif %}

  {# Player / Team grid #}
  <div class="overflow-x-auto bg-stone-950">
    <table class="w-full border-collapse">
      <thead class="bg-stone-900">
        <tr>
          <th class="text-left px-4 py-3 text-stone-400 text-xs uppercase tracking-wide w-36">
            {% if session.mode == 'teams' %}Team{% else %}Player{% endif %}
          </th>
          {% for field in player_fields %}
          <th class="px-4 py-3 text-xs uppercase tracking-wide text-center
                     {% if field.is_score_field %}text-yellow-400{% else %}text-stone-400{% endif %}">
            {{ field.label }}{% if field.is_score_field %} ★{% endif %}
          </th>
          {% endfor %}
        </tr>
      </thead>
      <tbody>
        {% set entities = teams if session.mode == 'teams' else players %}
        {% for entity in entities %}
        <tr class="border-t border-stone-800 {% if loop.index is odd %}bg-stone-950{% else %}bg-stone-900{% endif %}">
          <td class="px-4 py-3 font-semibold text-stone-100 text-sm">
            {% if session.mode == 'teams' %}
              {{ entity.name }}
            {% else %}
              {{ entity.person.first_name }} {{ entity.person.last_name }}
            {% endif %}
          </td>
          {% for field in player_fields %}
            {% if session.mode == 'teams' %}
              {% set tv = value_map.get((field.id, None, entity.id)) %}
              {% set entity_type = "team" %}
              {% set entity_id = entity.id %}
            {% else %}
              {% set tv = value_map.get((field.id, entity.id, None)) %}
              {% set entity_type = "player" %}
              {% set entity_id = entity.id %}
            {% endif %}
            <td class="px-4 py-3 text-center">
              {% if tv %}{% include "_tracker_cell.html" %}{% endif %}
            </td>
          {% endfor %}
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  {# Footer #}
  <div class="bg-stone-900 border-t border-stone-700 px-4 py-3 flex justify-between items-center">
    <span class="text-stone-500 text-sm">
      {{ entities | length }} {{ 'team' if session.mode == 'teams' else 'player' }}s &middot;
      {{ session.mode | capitalize }} &middot;
      Score: {{ player_fields | selectattr('is_score_field') | map(attribute='label') | first | default('—') }}
    </span>
    <div class="flex gap-3">
      <form action="{{ url_for('tracker.discard_tracker', session_id=session.id) }}" method="POST">
        <button class="text-stone-500 hover:text-stone-300 text-sm px-3 py-1.5">Discard</button>
      </form>
      <a href="{{ url_for('tracker.end_game', session_id=session.id) }}"
         class="bg-red-600 text-white font-semibold px-5 py-1.5 rounded-lg hover:bg-red-700 text-sm">
        End Game →
      </a>
    </div>
  </div>

</div>
{% endblock %}
```

- [ ] **Step 3: Smoke-test live tracker renders**

```
pytest tests/blueprints/test_tracker.py::test_live_tracker_loads -v
```

Expected: PASSED

- [ ] **Step 4: Commit**

```bash
git add app/templates/tracker_live.html app/templates/_tracker_cell.html
git commit -m "feat: live tracker template + HTMX cell partial"
```

---

## Task 12: Templates — tracker_confirm.html + _tracker_field_row.html

**Files:**
- Create: `app/templates/tracker_confirm.html`
- Create: `app/templates/_tracker_field_row.html`

- [ ] **Step 1: Create _tracker_field_row.html (partial returned by field-add HTMX)**

```html
{# Partial: one row in the setup fields list. Returned by POST /tracker/<id>/field #}
<li data-field-id="{{ field.id }}"
    class="flex items-center gap-3 bg-stone-50 border border-stone-200 rounded-lg px-3 py-2 cursor-move">
  <span class="text-stone-400 select-none">⠿</span>
  <span class="text-sm font-medium text-stone-700 flex-1">{{ field.label }}</span>
  <span class="text-xs px-2 py-0.5 rounded-full bg-stone-200 text-stone-600">{{ field.type.replace('_', ' ') }}</span>
  {% if field.type in ('counter', 'global_counter') %}
    <span class="text-xs text-stone-500">starts at {{ field.starting_value }}</span>
  {% endif %}
  {% if field.is_score_field %}
    <span class="text-xs text-yellow-600 font-semibold">★ score</span>
  {% endif %}
</li>
```

- [ ] **Step 2: Create tracker_confirm.html**

```html
{% extends "base.html" %}

{% block title %}Confirm Results — {{ session.game_night_game.game.name }}{% endblock %}

{% block content %}
<div class="max-w-2xl mx-auto space-y-6">
  <div>
    <a href="{{ url_for('tracker.live_tracker', session_id=session.id) }}"
       class="text-sm text-stone-500 hover:text-red-600 inline-block mb-3">&larr; Back to Tracker</a>
    <h1 class="text-2xl font-bold text-stone-800">Confirm Results</h1>
    <p class="text-stone-500 text-sm mt-1">{{ session.game_night_game.game.name }} — auto-ranked by
      <strong>{{ session.fields | selectattr('is_score_field') | map(attribute='label') | first }}</strong>
    </p>
  </div>

  {% if has_existing_results %}
  <div class="bg-yellow-50 border border-yellow-200 rounded-lg px-4 py-3 text-sm text-yellow-800">
    ⚠ Results already exist for this game. Saving will overwrite them.
  </div>
  {% endif %}

  <form action="{{ url_for('tracker.save_results', session_id=session.id) }}" method="POST">
    <div class="bg-white rounded-xl shadow-sm border border-stone-200 overflow-hidden">
      <table class="w-full border-collapse">
        <thead class="bg-stone-50">
          <tr>
            <th class="text-left px-4 py-3 text-stone-500 text-xs uppercase tracking-wide w-24">Position</th>
            <th class="text-left px-4 py-3 text-stone-500 text-xs uppercase tracking-wide">Player</th>
            <th class="text-center px-4 py-3 text-yellow-600 text-xs uppercase tracking-wide">
              {{ session.fields | selectattr('is_score_field') | map(attribute='label') | first }} ★
            </th>
          </tr>
        </thead>
        <tbody>
          {% for entry in rankings %}
          <tr class="border-t border-stone-100 {% if loop.index is odd %}bg-white{% else %}bg-stone-50{% endif %}">
            <td class="px-4 py-3">
              <select name="position_{{ entry.player_id }}"
                      class="border border-stone-300 rounded px-2 py-1 text-sm font-semibold">
                {% for i in range(1, rankings | length + 1) %}
                <option value="{{ i }}" {% if i == entry.position %}selected{% endif %}>
                  {{ i }}{{ 'st' if i == 1 else ('nd' if i == 2 else ('rd' if i == 3 else 'th')) }}
                </option>
                {% endfor %}
              </select>
            </td>
            <td class="px-4 py-3 font-medium text-stone-800 text-sm">
              {% if entry.position == 1 %}🏆 {% endif %}
              {% if entry.player_id %}
                {{ entry.player.person.first_name }} {{ entry.player.person.last_name }}
              {% else %}
                {{ entry.team.name }}
              {% endif %}
              <input type="hidden" name="score_{{ entry.player_id }}" value="{{ entry.score }}">
            </td>
            <td class="px-4 py-3 text-center font-bold text-stone-800">{{ entry.score }}</td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>

    <div class="flex justify-between mt-4">
      <form action="{{ url_for('tracker.discard_tracker', session_id=session.id) }}" method="POST" class="inline">
        <button type="submit" class="text-stone-500 hover:text-stone-700 text-sm px-4 py-2">Discard</button>
      </form>
      <button type="submit"
              class="bg-green-600 text-white font-semibold px-6 py-2 rounded-lg hover:bg-green-700">
        Save Results →
      </button>
    </div>
  </form>
</div>
{% endblock %}
```

Note: `entry.player` and `entry.team` are not currently in the `rankings` dict — update `compute_rankings` in `tracker_services.py` to include them:

```python
# In compute_rankings, update the rankings.append call:
rankings.append({
    "player_id": v.player_id,
    "team_id": v.team_id,
    "player": v.player,   # ORM object, may be None
    "team": v.team,        # ORM object, may be None
    "position": pos,
    "score": int(v.value),
})
```

- [ ] **Step 3: Smoke-test confirm page renders**

```
pytest tests/blueprints/test_tracker.py::test_end_game_get_returns_rankings -v
```

Expected: PASSED

- [ ] **Step 4: Commit**

```bash
git add app/templates/tracker_confirm.html app/templates/_tracker_field_row.html app/services/tracker_services.py
git commit -m "feat: end-game confirmation template + field row partial; add player/team to rankings"
```

---

## Task 13: Integration — add Track button to view_game_night.html

**Files:**
- Modify: `app/templates/view_game_night.html`

- [ ] **Step 1: Write integration test**

Add to `tests/blueprints/test_tracker.py`:

```python
def test_track_button_visible_on_active_game_night(auth_tracker_client):
    c = auth_tracker_client["client"]
    gn_id = auth_tracker_client["gn_id"]
    resp = c.get(f"/game_night/{gn_id}")
    assert resp.status_code == 200
    assert b"Track" in resp.data


def test_track_button_not_visible_on_finalized_game_night(app, db, auth_tracker_client):
    from app.models import GameNight
    c = auth_tracker_client["client"]
    gn_id = auth_tracker_client["gn_id"]
    with app.app_context():
        gn = GameNight.query.get(gn_id)
        gn.final = True
        _db.session.commit()
    resp = c.get(f"/game_night/{gn_id}")
    assert resp.status_code == 200
    assert b"/tracker/new" not in resp.data
    # Reset
    with app.app_context():
        gn = GameNight.query.get(gn_id)
        gn.final = False
        _db.session.commit()
```

- [ ] **Step 2: Run to verify failure**

```
pytest tests/blueprints/test_tracker.py -k "track_button" -v
```

Expected: `AssertionError: b"Track" not in resp.data`

- [ ] **Step 3: Add Track button to view_game_night.html**

Find the section in `app/templates/view_game_night.html` where each game (`gng`) is rendered — around the line with `url_for('game_night.log_results', ...)`. Add the Track button inside the `{% if not game_night.final %}` section, next to the existing log results button:

```html
{% if not game_night.final %}
  {# Existing log results form — keep as-is #}
  <form action="{{ url_for('game_night.log_results', game_night_id=game_night.id, game_night_game_id=gng.game_night_game_id) }}" method="GET">
    ...
  </form>
  {# NEW: Track button #}
  {% set tracker_session = gng.tracker_session %}
  {% if tracker_session and tracker_session.status == 'active' %}
    <a href="{{ url_for('tracker.live_tracker', session_id=tracker_session.id) }}"
       class="inline-flex items-center gap-1 text-xs font-medium px-3 py-1.5 rounded border border-blue-300 text-blue-600 hover:bg-blue-50">
      ▶ Resume Tracker
    </a>
  {% else %}
    <a href="{{ url_for('tracker.setup_tracker', gng_id=gng.game_night_game_id) }}"
       class="inline-flex items-center gap-1 text-xs font-medium px-3 py-1.5 rounded border border-stone-300 text-stone-600 hover:bg-stone-50">
      📊 Track
    </a>
  {% endif %}
{% endif %}
```

Note: `gng.tracker_session` works because `GameNightGameResults` (the SQL view) may not include the relationship. Access via the ORM `GameNightGame` model relationship instead — the route passes the full `gng` object. If `gng` is from the view (no ORM relationship), look up the session directly:

```html
{% set tracker_session = gng.game_night_game_id | get_tracker_session %}
```

Simpler alternative: look up active sessions in the route and pass a dict to the template.

In `app/blueprints/game_night.py`, in the `view_game_night` route, add:
```python
from app.models import TrackerSession
tracker_sessions = {
    ts.game_night_game_id: ts
    for ts in TrackerSession.query.filter(
        TrackerSession.game_night_game_id.in_([gng.game_night_game_id for gng in game_night_games]),
        TrackerSession.status.in_(["configuring", "active"])
    ).all()
}
```
Pass `tracker_sessions=tracker_sessions` to `render_template` and use `tracker_sessions.get(gng.game_night_game_id)` in the template.

- [ ] **Step 4: Run integration tests**

```
pytest tests/blueprints/test_tracker.py -k "track_button" -v
```

Expected: 2 PASSED

- [ ] **Step 5: Run full test suite**

```
pytest tests/ -q
```

Expected: all PASSED

- [ ] **Step 6: Commit**

```bash
git add app/templates/view_game_night.html app/blueprints/game_night.py tests/blueprints/test_tracker.py
git commit -m "feat: add Track / Resume Tracker buttons to game night page"
```

---

## Final: Full test suite + push

- [ ] **Step 1: Run full test suite**

```
pytest tests/ -q
```

Expected: all PASSED, no regressions

- [ ] **Step 2: Push feature branch**

```bash
git push origin feature/live-tracker
```

Let CI run. Fix any ruff/mypy/bandit failures before requesting review.
