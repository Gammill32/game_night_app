# Achievement Badges Review Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all Critical, Important, and Minor issues found across four code reviews (backend architecture, QA, security, test quality) of the `feature/achievement-badges` branch.

**Architecture:** All changes are on `feature/achievement-badges`. Fixes are grouped by concern: migration compatibility, evaluation correctness (race condition, re-finalization), checker logic bugs, query performance (N+1), display correctness (recap missing 15/26 badges), security (field allowlist), and comprehensive test suite repair.

**Tech Stack:** Python 3, Flask, SQLAlchemy, pytest, SQLite (tests), PostgreSQL (production), Jinja2

---

## Preflight

- [ ] **Check out the feature branch**
```bash
git checkout feature/achievement-badges
```

- [ ] **Verify tests pass before starting**
```bash
pytest tests/services/test_badge_services.py tests/blueprints/test_game_night.py -x -q 2>&1 | tail -20
```

---

## Task 1: Fix migration SQLite incompatibility

**Files:**
- Modify: `migrations/versions/8b9f3a3784a3_add_achievement_badges.py:35`

The `server_default=sa.text("now()")` is PostgreSQL-only and breaks the SQLite test database. Fix to use `CURRENT_TIMESTAMP` which both engines understand.

- [ ] **Make the fix**

In `migrations/versions/8b9f3a3784a3_add_achievement_badges.py`, find:
```python
sa.Column("earned_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
```
Replace with:
```python
sa.Column("earned_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
```

- [ ] **Commit**
```bash
git add migrations/versions/8b9f3a3784a3_add_achievement_badges.py
git commit -m "fix: use CURRENT_TIMESTAMP in migration — now() is PostgreSQL-only"
```

---

## Task 2: Fix race condition in `evaluate_badges_for_night` + add `final` guard

**Files:**
- Modify: `app/services/badge_services.py:690-749`

**Two bugs:**
1. The application-level `already` check before insert is non-atomic — two concurrent transactions can both read `None` and both insert, causing an `IntegrityError` that silently rolls back all badge awards.
2. No guard on `game_night.final` — calling with an unfinalized night awards badges on incomplete data.

Fix: remove the `already` pre-check entirely; rely solely on the DB unique constraint by catching `IntegrityError` per badge insert. Add a `game_night.final` guard at the top.

- [ ] **Write the failing test first**

Add to `tests/services/test_badge_services.py` (after `test_evaluate_badges_does_not_raise_on_bad_night`):

```python
def test_evaluate_badges_skips_unfinalized_night(app, db, badge_night):
    """evaluate_badges_for_night must do nothing on an unfinalized night."""
    from app.services.badge_services import evaluate_badges_for_night

    with app.app_context():
        gn_id = badge_night["game_night"].id
        winner_id = badge_night["winner"].id

        # Un-finalize the night
        from app.models import GameNight as GN
        gn = GN.query.get(gn_id)
        gn.final = False
        _db.session.commit()

        PersonBadge.query.filter_by(person_id=winner_id).delete()
        _db.session.commit()

        evaluate_badges_for_night(gn_id)

        count = PersonBadge.query.filter_by(person_id=winner_id).count()
        assert count == 0, "No badges should be awarded for an unfinalized night"

        # Restore for fixture teardown
        gn.final = True
        _db.session.commit()
```

- [ ] **Run to confirm failure**
```bash
pytest tests/services/test_badge_services.py::test_evaluate_badges_skips_unfinalized_night -xvs
```

- [ ] **Implement the fix**

Replace the body of `evaluate_badges_for_night` in `app/services/badge_services.py`:

```python
def evaluate_badges_for_night(game_night_id: int) -> None:
    """Evaluate all badges for all participants of the given finalized game night.

    Silently logs and returns on any error — must never raise to the caller.
    Relies on the uq_person_badge unique constraint to prevent duplicates;
    does NOT use an application-level pre-check (which would be a race condition).
    """
    from sqlalchemy.exc import IntegrityError

    try:
        game_night = db.session.get(GameNight, game_night_id)
        if game_night is None or not game_night.final:
            return

        participants = Player.query.filter_by(game_night_id=game_night_id).all()
        person_ids = [p.people_id for p in participants]

        badges = {b.key: b for b in Badge.query.all()}

        for badge_key, checker_fn in _BADGE_REGISTRY.items():
            badge = badges.get(badge_key)
            if badge is None:
                continue

            # Always store the triggering night so recap can show all awarded badges
            night_id_to_store = game_night_id

            for person_id in person_ids:
                try:
                    earned = checker_fn(person_id, game_night_id)
                except Exception:
                    logger.exception(
                        "Badge checker %s failed for person %s night %s",
                        badge_key, person_id, game_night_id,
                    )
                    continue

                if earned:
                    try:
                        db.session.add(PersonBadge(
                            person_id=person_id,
                            badge_id=badge.id,
                            game_night_id=night_id_to_store,
                        ))
                        db.session.flush()
                    except IntegrityError:
                        db.session.rollback()
                        # Already earned — unique constraint fired, skip silently
                        continue

        db.session.commit()

    except Exception:
        db.session.rollback()
        logger.exception("Badge evaluation failed for game night %s", game_night_id)
```

Also remove the `_NIGHT_LINKED` set entirely (it is no longer used). Delete these lines:

```python
# keys where game_night_id is recorded on PersonBadge (the night that triggered it)
_NIGHT_LINKED = {
    "first_blood", "hat_trick", "kingslayer", "redemption_arc",
    "jack_of_all_trades", "upset_special", "bench_warmer", "opening_night",
    "the_diplomat", "the_rematch", "dark_horse",
}
```

- [ ] **Run the new test + full badge test suite**
```bash
pytest tests/services/test_badge_services.py -x -q 2>&1 | tail -20
```
Expected: new test passes; existing tests still pass.

- [ ] **Commit**
```bash
git add app/services/badge_services.py tests/services/test_badge_services.py
git commit -m "fix: remove non-atomic badge pre-check; guard unfinalized nights; store night_id for all badges"
```

---

## Task 3: Fix re-finalization + field allowlist in `toggle_game_night_field`

**Files:**
- Modify: `app/services/game_night_services.py:169-192`

**Two bugs:**
1. Un-finalizing and re-finalizing a game night leaves wrong badge state permanently (night-linked badges from first finalization remain).
2. `hasattr`/`setattr` with no allowlist allows an admin to accidentally toggle non-boolean fields like `id` or relationships.

Fix: add explicit `TOGGLEABLE_FIELDS` allowlist; when toggling `final` to `False`, delete PersonBadges with `game_night_id = game_night_id`.

- [ ] **Write the failing test for allowlist**

Add to `tests/blueprints/test_game_night.py`:

```python
def test_toggle_invalid_field_is_rejected(admin_client, app, db):
    """toggle_game_night_field must reject fields not in the allowlist."""
    import datetime, uuid
    from app.extensions import db as _db
    from app.models import GameNight, Person, Player

    person = Person(first_name="T", last_name="T",
                    email=f"toggle_{uuid.uuid4().hex[:6]}@test.invalid")
    _db.session.add(person)
    _db.session.flush()
    gn = GameNight(date=datetime.date.today(), final=False)
    _db.session.add(gn)
    _db.session.flush()
    pl = Player(game_night_id=gn.id, people_id=person.id)
    _db.session.add(pl)
    _db.session.commit()
    gn_id, pl_id, person_id = gn.id, pl.id, person.id

    resp = admin_client.post(f"/game_night/{gn_id}/toggle/id")
    assert resp.status_code in (400, 404, 302)

    # Confirm id was not modified
    from app.models import GameNight as GN
    fresh = GN.query.get(gn_id)
    assert fresh.id == gn_id

    Player.query.filter_by(id=pl_id).delete()
    GameNight.query.filter_by(id=gn_id).delete()
    Person.query.filter_by(id=person_id).delete()
    _db.session.commit()
```

- [ ] **Run to confirm failure**
```bash
pytest tests/blueprints/test_game_night.py::test_toggle_invalid_field_is_rejected -xvs
```

- [ ] **Implement the fix**

Replace the `toggle_game_night_field` function in `app/services/game_night_services.py`:

```python
_TOGGLEABLE_FIELDS = {"final", "closed"}


def toggle_game_night_field(game_night_id, field):
    """Toggle boolean fields in a game night (e.g., final results, voting)."""
    if field not in _TOGGLEABLE_FIELDS:
        return False, "Invalid field."

    game_night = GameNight.query.get_or_404(game_night_id)
    setattr(game_night, field, not getattr(game_night, field))

    if field == "final" and getattr(game_night, field) is False:
        # Clear night-triggered badges so re-finalization starts clean
        from app.models import PersonBadge
        PersonBadge.query.filter_by(game_night_id=game_night_id).delete()

    db.session.commit()

    if field == "final" and getattr(game_night, field) is True:
        try:
            from app.services.badge_services import evaluate_badges_for_night
            evaluate_badges_for_night(game_night_id)
        except Exception:
            logging.getLogger(__name__).exception(
                "Badge evaluation failed for game night %s", game_night_id
            )

    return (
        True,
        f"{field.replace('_', ' ').capitalize()} has been {'enabled' if getattr(game_night, field) else 'disabled'}.",
    )
```

Add `import logging` at the top of `game_night_services.py` at module level (remove the inline `import logging` inside the except block).

- [ ] **Run tests**
```bash
pytest tests/blueprints/test_game_night.py -x -q 2>&1 | tail -20
```

- [ ] **Commit**
```bash
git add app/services/game_night_services.py tests/blueprints/test_game_night.py
git commit -m "fix: add TOGGLEABLE_FIELDS allowlist; clear night badges on un-finalize for clean re-evaluation"
```

---

## Task 4: Add the missing recap route

**Files:**
- Modify: `app/blueprints/game_night.py`

The `recap_game_night.html` template and `get_recap_details()` service exist but no route is registered. Any test hitting `/game_night/<id>/recap` currently fails.

The `get_recap_details` service aborts 404 for unfinalized nights, so the route is safe to leave unauthenticated (the docstring marks it "public"). Note: player names are visible to unauthenticated users; this is the accepted design per the docstring. If this needs changing, add `@login_required`.

- [ ] **Add the route**

In `app/blueprints/game_night.py`, after the `delete_game_night` route (end of file), add:

```python
@game_night_bp.route("/game_night/<int:game_night_id>/recap")
def recap_game_night(game_night_id):
    """Public read-only recap of a completed game night."""
    details = game_night_services.get_recap_details(game_night_id)
    return render_template("recap_game_night.html", **details)
```

- [ ] **Run the integration test**
```bash
pytest tests/blueprints/test_game_night.py -x -q -k "recap" 2>&1 | tail -20
```

- [ ] **Commit**
```bash
git add app/blueprints/game_night.py
git commit -m "fix: register /game_night/<id>/recap route — template and service existed but route was missing"
```

---

## Task 5: Fix `get_recap_details` — add joinedload + include all badges

**Files:**
- Modify: `app/services/game_night_services.py` (the `get_recap_details` function)

Two bugs:
1. N+1: `raw_badges` accesses `pb.person` and `pb.badge` without eager loading.
2. Only night-linked badges are shown (15 of 26 badges have `game_night_id = None` and never appear). Since Task 2 now sets `game_night_id` for ALL badges, this query now works — but we also need `joinedload`.

- [ ] **Implement the fix**

In `get_recap_details`, replace the `raw_badges` / `badges_earned` block:

```python
from sqlalchemy.orm import joinedload as _joinedload

raw_badges = (
    PersonBadge.query
    .filter_by(game_night_id=game_night_id)
    .options(
        _joinedload(PersonBadge.person),
        _joinedload(PersonBadge.badge),
    )
    .all()
)
badges_earned = [
    {
        "person_name": f"{pb.person.first_name} {pb.person.last_name}",
        "badge_name": pb.badge.name,
        "badge_icon": pb.badge.icon,
    }
    for pb in raw_badges
]
```

Note: `joinedload` is already imported at the top of `game_night_services.py` as `from sqlalchemy.orm import joinedload`. Use it directly (remove the inline re-import).

- [ ] **Also fix `get_person_badges` N+1**

In `app/services/badge_services.py`, update `get_person_badges`:

```python
def get_person_badges(person_id: int) -> list:
    """Return all earned badges for a person, newest first."""
    from sqlalchemy.orm import joinedload
    return (
        PersonBadge.query
        .filter_by(person_id=person_id)
        .options(joinedload(PersonBadge.badge))
        .order_by(PersonBadge.earned_at.desc())
        .all()
    )
```

- [ ] **Run tests**
```bash
pytest tests/ -x -q 2>&1 | tail -20
```

- [ ] **Commit**
```bash
git add app/services/game_night_services.py app/services/badge_services.py
git commit -m "fix: add joinedload to get_recap_details and get_person_badges to eliminate N+1 queries"
```

---

## Task 6: Fix `_check_bench_warmer` — 1-player game bug

**Files:**
- Modify: `app/services/badge_services.py` (`_check_bench_warmer`)

When `max_pos == 1` there is only one player with a recorded result — that player cannot be "last place" in any meaningful sense. The badge must require at least 2 players.

- [ ] **Write the failing test**

In `tests/services/test_badge_services.py`, add after `test_bench_warmer_does_not_earn_for_winner`:

```python
def test_bench_warmer_does_not_earn_in_solo_game(app, db):
    """bench_warmer must not fire when only one player has a recorded result."""
    from app.services.badge_services import _check_bench_warmer

    with app.app_context():
        game = Game(name=f"Solo {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(first_name="Solo", last_name="Player",
                        email=f"solo_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all([game, person])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=2), final=True)
        _db.session.add(gn)
        _db.session.flush()

        player = Player(game_night_id=gn.id, people_id=person.id)
        _db.session.add(player)
        _db.session.flush()

        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.flush()

        _db.session.add(Result(game_night_game_id=gng.id, player_id=player.id, position=1))
        _db.session.commit()

        assert _check_bench_warmer(person.id, gn.id) is False

        Result.query.filter_by(game_night_game_id=gng.id).delete()
        _db.session.delete(gng)
        _db.session.delete(player)
        PersonBadge.query.filter_by(game_night_id=gn.id).delete()
        _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(game)
        _db.session.commit()
```

- [ ] **Run to confirm failure**
```bash
pytest tests/services/test_badge_services.py::test_bench_warmer_does_not_earn_in_solo_game -xvs
```

- [ ] **Fix the checker**

In `_check_bench_warmer`, change the inner loop:

```python
def _check_bench_warmer(person_id: int, game_night_id: int) -> bool:
    person_results = (
        db.session.query(GameNightGame.id.label("gng_id"), Result.position)
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .filter(
            Player.people_id == person_id,
            GameNightGame.game_night_id == game_night_id,
            Result.position.isnot(None),
        )
        .all()
    )
    if not person_results:
        return False
    for row in person_results:
        max_pos = (
            db.session.query(func.max(Result.position))
            .filter(Result.game_night_game_id == row.gng_id, Result.position.isnot(None))
            .scalar()
        )
        # max_pos == 1 means only one player had a result — no true "last place"
        if max_pos is None or max_pos <= 1 or row.position != max_pos:
            return False
    return True
```

- [ ] **Run tests**
```bash
pytest tests/services/test_badge_services.py -x -q -k "bench" 2>&1 | tail -10
```

- [ ] **Commit**
```bash
git add app/services/badge_services.py tests/services/test_badge_services.py
git commit -m "fix: bench_warmer must not award badge when only one player has a result (solo game)"
```

---

## Task 7: Fix `_check_the_diplomat` — zero-results bug

**Files:**
- Modify: `app/services/badge_services.py` (`_check_the_diplomat`)

A game with no recorded results (all positions NULL) passes the check and awards the badge incorrectly. Each game in the night must have at least one recorded result to qualify.

- [ ] **Write the failing test**

In `tests/services/test_badge_services.py`, add after `test_the_diplomat_does_not_earn_when_not_all_tied`:

```python
def test_the_diplomat_does_not_earn_with_no_results_recorded(app, db):
    """the_diplomat must not award badge when games have no results at all."""
    from app.services.badge_services import _check_the_diplomat

    with app.app_context():
        game = Game(name=f"EmptyGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(first_name="Dip", last_name="Empty",
                        email=f"dipempty_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all([game, person])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=3), final=True)
        _db.session.add(gn)
        _db.session.flush()

        player = Player(game_night_id=gn.id, people_id=person.id)
        _db.session.add(player)
        _db.session.flush()

        # Game with NO results
        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.commit()

        assert _check_the_diplomat(person.id, gn.id) is False

        _db.session.delete(gng)
        _db.session.delete(player)
        PersonBadge.query.filter_by(game_night_id=gn.id).delete()
        _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(game)
        _db.session.commit()
```

- [ ] **Run to confirm failure**
```bash
pytest tests/services/test_badge_services.py::test_the_diplomat_does_not_earn_with_no_results_recorded -xvs
```

- [ ] **Fix the checker**

```python
def _check_the_diplomat(person_id: int, game_night_id: int) -> bool:
    if not Player.query.filter_by(game_night_id=game_night_id, people_id=person_id).first():
        return False
    games = GameNightGame.query.filter_by(game_night_id=game_night_id).all()
    if not games:
        return False
    for gng in games:
        # Must have at least one result recorded — a game with no results doesn't qualify
        has_results = (
            db.session.query(Result)
            .filter(Result.game_night_game_id == gng.id, Result.position.isnot(None))
            .first()
        )
        if not has_results:
            return False
        non_first = (
            db.session.query(Result)
            .filter(
                Result.game_night_game_id == gng.id,
                Result.position != 1,
                Result.position.isnot(None),
            )
            .first()
        )
        if non_first:
            return False
    return True
```

- [ ] **Run tests**
```bash
pytest tests/services/test_badge_services.py -x -q -k "diplomat" 2>&1 | tail -10
```

- [ ] **Commit**
```bash
git add app/services/badge_services.py tests/services/test_badge_services.py
git commit -m "fix: the_diplomat must not award badge when games have no recorded results"
```

---

## Task 8: Fix `_check_opening_night` — decouple from current game_night_id

**Files:**
- Modify: `app/services/badge_services.py` (`_check_opening_night`)

Current code: `if first_night.id != game_night_id: return False` — only awards badge when the CURRENT night being evaluated is the first ever. If historical data was entered retroactively, this will never fire.

Fix: check if the person attended the first recorded night (by date), regardless of which night is being evaluated now. The unique constraint prevents double-awarding.

- [ ] **Rewrite `test_opening_night_earns_on_first_night`** (replaces the tautological test)

In `tests/services/test_badge_services.py`, replace `test_opening_night_earns_on_first_night` with:

```python
def test_opening_night_earns_for_attendee_of_first_night(app, db):
    """opening_night earns for anyone who attended the earliest recorded game night."""
    from app.services.badge_services import _check_opening_night

    with app.app_context():
        # Use a date far in the past to guarantee this is the first night in the DB
        first_date = datetime.date(1900, 1, 1)
        later_date = datetime.date(1900, 1, 2)

        game = Game(name=f"OGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        founder = Person(first_name="Founder", last_name="One",
                         email=f"founder_{uuid.uuid4().hex[:6]}@test.invalid")
        latecomer = Person(first_name="Late", last_name="Comer",
                           email=f"late_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all([game, founder, latecomer])
        _db.session.flush()

        first_gn = GameNight(date=first_date, final=True)
        later_gn = GameNight(date=later_date, final=True)
        _db.session.add_all([first_gn, later_gn])
        _db.session.flush()

        founder_player = Player(game_night_id=first_gn.id, people_id=founder.id)
        latecomer_player = Player(game_night_id=later_gn.id, people_id=latecomer.id)
        _db.session.add_all([founder_player, latecomer_player])
        _db.session.commit()

        # Founder attended the first night — earns badge regardless of which night we evaluate
        assert _check_opening_night(founder.id, later_gn.id) is True
        # Latecomer only attended a later night — does not earn
        assert _check_opening_night(latecomer.id, later_gn.id) is False

        _db.session.delete(founder_player)
        _db.session.delete(latecomer_player)
        PersonBadge.query.filter_by(game_night_id=first_gn.id).delete()
        PersonBadge.query.filter_by(game_night_id=later_gn.id).delete()
        _db.session.delete(first_gn)
        _db.session.delete(later_gn)
        _db.session.delete(founder)
        _db.session.delete(latecomer)
        _db.session.delete(game)
        _db.session.commit()
```

- [ ] **Run to confirm failure**
```bash
pytest tests/services/test_badge_services.py::test_opening_night_earns_for_attendee_of_first_night -xvs
```

- [ ] **Fix the checker**

```python
def _check_opening_night(person_id: int, game_night_id: int) -> bool:
    first_night = GameNight.query.order_by(GameNight.date, GameNight.id).first()
    if first_night is None:
        return False
    return (
        Player.query.filter_by(game_night_id=first_night.id, people_id=person_id).first()
        is not None
    )
```

- [ ] **Run tests**
```bash
pytest tests/services/test_badge_services.py -x -q -k "opening" 2>&1 | tail -10
```

- [ ] **Commit**
```bash
git add app/services/badge_services.py tests/services/test_badge_services.py
git commit -m "fix: opening_night checks attendance at first night by date, not current game_night_id"
```

---

## Task 9: Fix `_check_founding_member` — correct semantics

**Files:**
- Modify: `app/services/badge_services.py` (`_check_founding_member`)

Current: finds 5 people with the earliest personal `min(GameNight.date)`. Problem: a Night 2 attendee with the same date as Night 1 could qualify while a Night 1-only attendee gets excluded.

Fix: find the attendees of the first recorded game night (by date), take up to 5 by `Player.id` order.

- [ ] **Replace `test_founding_member_earns_for_early_players`** with isolated test

In `tests/services/test_badge_services.py`, replace `test_founding_member_earns_for_early_players` with:

```python
def test_founding_member_earns_for_attendees_of_first_night(app, db):
    """founding_member earns for the first 5 attendees of the earliest game night."""
    from app.services.badge_services import _check_founding_member

    with app.app_context():
        # Use a date far in the past to guarantee this is the DB's first night
        first_date = datetime.date(1901, 1, 1)
        later_date = datetime.date(1901, 1, 2)

        founders = [
            Person(first_name=f"F{i}", last_name="Founder",
                   email=f"founding_{i}_{uuid.uuid4().hex[:6]}@test.invalid")
            for i in range(3)
        ]
        outsider = Person(first_name="Out", last_name="Sider",
                          email=f"outsider_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all(founders + [outsider])
        _db.session.flush()

        first_gn = GameNight(date=first_date, final=True)
        later_gn = GameNight(date=later_date, final=True)
        _db.session.add_all([first_gn, later_gn])
        _db.session.flush()

        founder_players = [
            Player(game_night_id=first_gn.id, people_id=f.id) for f in founders
        ]
        outsider_player = Player(game_night_id=later_gn.id, people_id=outsider.id)
        _db.session.add_all(founder_players + [outsider_player])
        _db.session.commit()

        for f in founders:
            assert _check_founding_member(f.id, later_gn.id) is True
        assert _check_founding_member(outsider.id, later_gn.id) is False

        for p in founder_players:
            _db.session.delete(p)
        _db.session.delete(outsider_player)
        for f in founders:
            PersonBadge.query.filter_by(person_id=f.id).delete()
        PersonBadge.query.filter_by(person_id=outsider.id).delete()
        _db.session.delete(first_gn)
        _db.session.delete(later_gn)
        for f in founders:
            _db.session.delete(f)
        _db.session.delete(outsider)
        _db.session.commit()
```

- [ ] **Run to confirm failure**
```bash
pytest tests/services/test_badge_services.py::test_founding_member_earns_for_attendees_of_first_night -xvs
```

- [ ] **Fix the checker**

```python
def _check_founding_member(person_id: int, game_night_id: int) -> bool:
    first_night = GameNight.query.order_by(GameNight.date, GameNight.id).first()
    if first_night is None:
        return False
    first_five = (
        db.session.query(Player.people_id)
        .filter_by(game_night_id=first_night.id)
        .order_by(Player.id)
        .limit(5)
        .all()
    )
    return any(pid == person_id for (pid,) in first_five)
```

- [ ] **Run tests**
```bash
pytest tests/services/test_badge_services.py -x -q -k "founding" 2>&1 | tail -10
```

- [ ] **Commit**
```bash
git add app/services/badge_services.py tests/services/test_badge_services.py
git commit -m "fix: founding_member awards badge to first 5 attendees of Night 1, not earliest-per-person date"
```

---

## Task 10: Fix N+1 queries — `_check_nemesis`, `_check_upset_special`, `_check_winning_streak`, `_check_the_closer`, `_check_the_oracle`, `_check_early_bird`

**Files:**
- Modify: `app/services/badge_services.py` (six checker functions)

### 10a — `_check_nemesis` (O(n) queries → 1 query)

Replace with a single aggregated query:

```python
def _check_nemesis(person_id: int, game_night_id: int) -> bool:
    person_alias = db.aliased(Player)
    opp_alias = db.aliased(Player)
    person_result = db.aliased(Result)
    opp_result = db.aliased(Result)

    row = (
        db.session.query(func.count().label("beat_count"))
        .select_from(person_result)
        .join(person_alias, person_result.player_id == person_alias.id)
        .join(opp_result, person_result.game_night_game_id == opp_result.game_night_game_id)
        .join(opp_alias, opp_result.player_id == opp_alias.id)
        .filter(
            person_alias.people_id == person_id,
            opp_alias.people_id != person_id,
            opp_result.position < person_result.position,
            person_result.position.isnot(None),
            opp_result.position.isnot(None),
        )
        .group_by(opp_alias.people_id)
        .having(func.count() >= 5)
        .first()
    )
    return row is not None
```

### 10b — `_check_early_bird` (O(n nights) queries → 2 queries)

Replace with a subquery approach; filter to finalized nights only:

```python
def _check_early_bird(person_id: int, game_night_id: int) -> bool:
    # First registered player per finalized night (use Player.id as proxy for insertion order)
    first_player_per_night = (
        db.session.query(
            Player.game_night_id,
            func.min(Player.id).label("first_player_id"),
        )
        .join(GameNight, Player.game_night_id == GameNight.id)
        .filter(GameNight.final.is_(True))
        .group_by(Player.game_night_id)
        .subquery()
    )
    first_count = (
        db.session.query(func.count())
        .select_from(Player)
        .join(first_player_per_night, Player.id == first_player_per_night.c.first_player_id)
        .filter(Player.people_id == person_id)
        .scalar()
    )
    return (first_count or 0) >= 10
```

### 10c — `_check_winning_streak` (O(n nights) queries → 2 queries)

```python
def _check_winning_streak(person_id: int, game_night_id: int) -> bool:
    attended = (
        db.session.query(GameNight.id)
        .join(Player, GameNight.id == Player.game_night_id)
        .filter(Player.people_id == person_id, GameNight.final.is_(True))
        .order_by(GameNight.date)
        .all()
    )
    if len(attended) < 3:
        return False

    win_night_ids = {
        nid
        for (nid,) in (
            db.session.query(GameNight.id)
            .join(GameNightGame, GameNight.id == GameNightGame.game_night_id)
            .join(Result, GameNightGame.id == Result.game_night_game_id)
            .join(Player, Result.player_id == Player.id)
            .filter(
                Player.people_id == person_id,
                Result.position == 1,
                GameNight.final.is_(True),
            )
            .distinct()
            .all()
        )
    }

    streak = 0
    for (nid,) in attended:
        if nid in win_night_ids:
            streak += 1
            if streak >= 3:
                return True
        else:
            streak = 0
    return False
```

### 10d — `_check_the_closer` (O(n nights) queries → 3 queries)

```python
def _check_the_closer(person_id: int, game_night_id: int) -> bool:
    attended = (
        db.session.query(GameNight.id)
        .join(Player, GameNight.id == Player.game_night_id)
        .filter(Player.people_id == person_id, GameNight.final.is_(True))
        .order_by(GameNight.date)
        .all()
    )
    if len(attended) < 5:
        return False

    night_ids = [nid for (nid,) in attended]

    # Last round per night
    last_round_sq = (
        db.session.query(
            GameNightGame.game_night_id,
            func.max(GameNightGame.round).label("max_round"),
        )
        .filter(GameNightGame.game_night_id.in_(night_ids))
        .group_by(GameNightGame.game_night_id)
        .subquery()
    )

    # Nights where person won the last game
    closed_nights = {
        nid
        for (nid,) in (
            db.session.query(GameNightGame.game_night_id)
            .join(
                last_round_sq,
                (GameNightGame.game_night_id == last_round_sq.c.game_night_id)
                & (GameNightGame.round == last_round_sq.c.max_round),
            )
            .join(Result, GameNightGame.id == Result.game_night_game_id)
            .join(Player, Result.player_id == Player.id)
            .filter(Player.people_id == person_id, Result.position == 1)
            .distinct()
            .all()
        )
    }

    streak = 0
    for (nid,) in attended:
        if nid in closed_nights:
            streak += 1
            if streak >= 5:
                return True
        else:
            streak = 0
    return False
```

### 10e — `_check_the_oracle` (O(nights × nominations) queries → 1 query)

```python
def _check_the_oracle(person_id: int, game_night_id: int) -> bool:
    nom_player = db.aliased(Player)
    win_player = db.aliased(Player)

    oracle_nights = (
        db.session.query(func.count(func.distinct(GameNominations.game_night_id)))
        .join(nom_player, GameNominations.player_id == nom_player.id)
        .join(
            GameNightGame,
            (GameNightGame.game_night_id == GameNominations.game_night_id)
            & (GameNightGame.game_id == GameNominations.game_id),
        )
        .join(Result, Result.game_night_game_id == GameNightGame.id)
        .join(win_player, Result.player_id == win_player.id)
        .join(GameNight, GameNight.id == GameNominations.game_night_id)
        .filter(
            nom_player.people_id == person_id,
            win_player.people_id == person_id,
            Result.position == 1,
            GameNight.final.is_(True),
        )
        .scalar()
    )
    return (oracle_nights or 0) >= 5
```

### 10f — `_check_upset_special` (O(n³) → O(beaten opponents) queries)

```python
def _check_upset_special(person_id: int, game_night_id: int) -> bool:
    tonight_gng_ids = [
        r.id for r in GameNightGame.query.filter_by(game_night_id=game_night_id).all()
    ]
    if not tonight_gng_ids:
        return False

    person_tonight = {
        r.game_night_game_id: r.position
        for r in (
            db.session.query(Result.game_night_game_id, Result.position)
            .join(Player, Result.player_id == Player.id)
            .filter(
                Player.people_id == person_id,
                Result.game_night_game_id.in_(tonight_gng_ids),
                Result.position.isnot(None),
            )
            .all()
        )
    }

    beaten_opp_ids: set = set()
    for gng_id, person_pos in person_tonight.items():
        for (opp_id,) in (
            db.session.query(Player.people_id)
            .join(Result, Player.id == Result.player_id)
            .filter(
                Result.game_night_game_id == gng_id,
                Player.people_id != person_id,
                Result.position > person_pos,
                Result.position.isnot(None),
            )
            .all()
        ):
            beaten_opp_ids.add(opp_id)

    if not beaten_opp_ids:
        return False

    person_alias = db.aliased(Player)
    opp_alias = db.aliased(Player)
    p_result = db.aliased(Result)
    o_result = db.aliased(Result)

    for opp_id in beaten_opp_ids:
        rows = (
            db.session.query(
                p_result.position.label("p_pos"),
                o_result.position.label("o_pos"),
            )
            .join(person_alias, p_result.player_id == person_alias.id)
            .join(o_result, p_result.game_night_game_id == o_result.game_night_game_id)
            .join(opp_alias, o_result.player_id == opp_alias.id)
            .filter(
                person_alias.people_id == person_id,
                opp_alias.people_id == opp_id,
                p_result.game_night_game_id.notin_(tonight_gng_ids),
                p_result.position.isnot(None),
                o_result.position.isnot(None),
            )
            .all()
        )
        if len(rows) < 5:
            continue
        opp_wins = sum(1 for r in rows if r.o_pos < r.p_pos)
        if opp_wins / len(rows) >= 0.8:
            return True
    return False
```

- [ ] **Apply all six optimizations** as described above

- [ ] **Run full badge test suite**
```bash
pytest tests/services/test_badge_services.py -x -q 2>&1 | tail -20
```

- [ ] **Commit**
```bash
git add app/services/badge_services.py
git commit -m "perf: eliminate N+1 queries in nemesis, early_bird, winning_streak, the_closer, the_oracle, upset_special"
```

---

## Task 11: Fix `db.text("wins DESC")` → ORM ordering

**Files:**
- Modify: `app/services/badge_services.py` (`_check_kingslayer` line ~102, `_check_most_wins` line ~637)

- [ ] **In `_check_kingslayer`**, replace `.order_by(db.text("wins DESC"))` with:
```python
.order_by(func.count(Result.id).desc())
```
(remove the `.label("wins")` from the query since we no longer reference it by name)

- [ ] **In `_check_most_wins`**, replace `.order_by(db.text("wins DESC"))` with:
```python
.order_by(func.count(Result.id).desc())
```

- [ ] **Run tests**
```bash
pytest tests/services/test_badge_services.py -x -q -k "kingslayer or most_wins" 2>&1 | tail -10
```

- [ ] **Commit**
```bash
git add app/services/badge_services.py
git commit -m "fix: replace db.text('wins DESC') with ORM .order_by() in kingslayer and most_wins"
```

---

## Task 12: Remove `_stub` dead code

**Files:**
- Modify: `app/services/badge_services.py`

- [ ] **Delete `_stub`**

Remove these lines:

```python
def _stub(person_id: int, game_night_id: int) -> bool:
    """Placeholder — returns False until implemented."""
    return False
```

- [ ] **Run tests**
```bash
pytest tests/services/test_badge_services.py -x -q 2>&1 | tail -10
```

- [ ] **Commit**
```bash
git add app/services/badge_services.py
git commit -m "chore: remove _stub dead code"
```

---

## Task 13: Fix tautological and wrong-assertion tests

**Files:**
- Modify: `tests/services/test_badge_services.py`

Fix five tests that either assert trivially true things or have names that contradict their assertions.

### 13a — `test_century_club_earns_at_100_games` → rename + add positive test

Replace the test with:

```python
def test_century_club_does_not_earn_with_25_games(app, db, multi_night_person):
    from app.services.badge_services import _check_century_club
    # multi_night_person has 25 nights × 1 game = 25 games, not enough
    with app.app_context():
        assert _check_century_club(multi_night_person["person"].id, multi_night_person["last_night"].id) is False


def test_century_club_earns_at_100_games(app, db):
    """century_club earns when a person has played 100+ games across finalized nights."""
    from app.services.badge_services import _check_century_club

    with app.app_context():
        game = Game(name=f"CGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(first_name="Century", last_name="Player",
                        email=f"century_{uuid.uuid4().hex[:6]}@test.invalid")
        other = Person(first_name="Oth", last_name="C",
                       email=f"othc_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all([game, person, other])
        _db.session.flush()

        nights, players, gngs = [], [], []
        for i in range(100):
            gn = GameNight(date=datetime.date(2000, 1, 1) + datetime.timedelta(days=i), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)
            pl = Player(game_night_id=gn.id, people_id=person.id)
            op = Player(game_night_id=gn.id, people_id=other.id)
            _db.session.add_all([pl, op])
            _db.session.flush()
            players.extend([pl, op])
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=pl.id, position=1))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=op.id, position=2))
        _db.session.commit()

        assert _check_century_club(person.id, nights[-1].id) is True
        assert _check_century_club(other.id, nights[-1].id) is True

        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in players:
            _db.session.delete(pl)
        for gn in nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()
```

### 13b — `test_variety_pack_earns_with_10_different_games` → rename + add positive test

Replace with:

```python
def test_variety_pack_does_not_earn_with_1_unique_game(app, db, multi_night_person):
    from app.services.badge_services import _check_variety_pack
    with app.app_context():
        assert _check_variety_pack(multi_night_person["person"].id, multi_night_person["last_night"].id) is False


def test_variety_pack_earns_with_10_different_games(app, db):
    """variety_pack earns when a person has played 10+ distinct games."""
    from app.services.badge_services import _check_variety_pack

    with app.app_context():
        games = [Game(name=f"VGame{i}_{uuid.uuid4().hex[:4]}", bgg_id=None) for i in range(10)]
        person = Person(first_name="Var", last_name="Pack",
                        email=f"varpack_{uuid.uuid4().hex[:6]}@test.invalid")
        other = Person(first_name="Oth", last_name="Var",
                       email=f"othvar_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all(games + [person, other])
        _db.session.flush()

        nights, players, gngs = [], [], []
        for i, game in enumerate(games):
            gn = GameNight(date=datetime.date(2001, 1, 1) + datetime.timedelta(days=i), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)
            pl = Player(game_night_id=gn.id, people_id=person.id)
            op = Player(game_night_id=gn.id, people_id=other.id)
            _db.session.add_all([pl, op])
            _db.session.flush()
            players.extend([pl, op])
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=pl.id, position=1))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=op.id, position=2))
        _db.session.commit()

        assert _check_variety_pack(person.id, nights[-1].id) is True

        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in players:
            _db.session.delete(pl)
        for gn in nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(other)
        for g in games:
            _db.session.delete(g)
        _db.session.commit()
```

### 13c — `test_social_butterfly_does_not_earn_without_universal_play` → real assertions

Replace:

```python
def test_social_butterfly_does_not_earn_without_universal_play(app, db):
    """social_butterfly does not earn when person has not played with everyone."""
    from app.services.badge_services import _check_social_butterfly

    with app.app_context():
        game = Game(name=f"SBGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        p1 = Person(first_name="SB1", last_name="T",
                    email=f"sb1_{uuid.uuid4().hex[:6]}@test.invalid")
        p2 = Person(first_name="SB2", last_name="T",
                    email=f"sb2_{uuid.uuid4().hex[:6]}@test.invalid")
        # stranger has never played with p1
        stranger = Person(first_name="SBStr", last_name="T",
                          email=f"sbstr_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all([game, p1, p2, stranger])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=5), final=True)
        _db.session.add(gn)
        _db.session.flush()

        pl1 = Player(game_night_id=gn.id, people_id=p1.id)
        pl2 = Player(game_night_id=gn.id, people_id=p2.id)
        _db.session.add_all([pl1, pl2])
        _db.session.flush()

        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.flush()

        _db.session.add(Result(game_night_game_id=gng.id, player_id=pl1.id, position=1))
        _db.session.add(Result(game_night_game_id=gng.id, player_id=pl2.id, position=2))
        _db.session.commit()

        # p1 played with p2 but not stranger — should not earn
        assert _check_social_butterfly(p1.id, gn.id) is False

        Result.query.filter_by(game_night_game_id=gng.id).delete()
        _db.session.delete(gng)
        _db.session.delete(pl1)
        _db.session.delete(pl2)
        PersonBadge.query.filter_by(game_night_id=gn.id).delete()
        _db.session.delete(gn)
        _db.session.delete(p1)
        _db.session.delete(p2)
        _db.session.delete(stranger)
        _db.session.delete(game)
        _db.session.commit()
```

### 13d — `test_evaluate_badges_does_not_raise_on_bad_night` → add DB state assertion

Replace:

```python
def test_evaluate_badges_does_not_raise_on_bad_night(app, db):
    from app.services.badge_services import evaluate_badges_for_night

    with app.app_context():
        evaluate_badges_for_night(999999)
        # Must not write any PersonBadge rows for the nonexistent night
        count = PersonBadge.query.filter_by(game_night_id=999999).count()
        assert count == 0
```

- [ ] **Apply all four fixes above**

- [ ] **Run tests**
```bash
pytest tests/services/test_badge_services.py -x -q 2>&1 | tail -20
```

- [ ] **Commit**
```bash
git add tests/services/test_badge_services.py
git commit -m "test: fix tautological tests — rename century_club/variety_pack negatives, add real social_butterfly assertion, add DB state check"
```

---

## Task 14: Add missing positive-path tests — `kingslayer` and `grudge_match`

**Files:**
- Modify: `tests/services/test_badge_services.py`

Both badges have zero tests where the checker returns `True`. A stub returning `False` is indistinguishable.

### 14a — `kingslayer` positive test

Add after `test_kingslayer_earns_when_beating_top_winner`:

```python
def test_kingslayer_earns_when_underdog_beats_all_time_leader(app, db):
    """kingslayer earns when you beat the person with the most all-time wins tonight."""
    from app.services.badge_services import _check_kingslayer

    with app.app_context():
        game = Game(name=f"KSGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        champion = Person(first_name="Champ", last_name="KS",
                          email=f"champ_{uuid.uuid4().hex[:6]}@test.invalid")
        underdog = Person(first_name="Under", last_name="Dog",
                          email=f"underdog_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all([game, champion, underdog])
        _db.session.flush()

        # Champion wins 5 prior nights
        prior_nights, prior_players, prior_gngs = [], [], []
        for i in range(5):
            gn = GameNight(date=datetime.date(2002, 1, i + 1), final=True)
            _db.session.add(gn)
            _db.session.flush()
            prior_nights.append(gn)
            champ_pl = Player(game_night_id=gn.id, people_id=champion.id)
            und_pl = Player(game_night_id=gn.id, people_id=underdog.id)
            _db.session.add_all([champ_pl, und_pl])
            _db.session.flush()
            prior_players.extend([champ_pl, und_pl])
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            prior_gngs.append(gng)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=champ_pl.id, position=1))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=und_pl.id, position=2))

        # Tonight: underdog wins, champion loses
        tonight = GameNight(date=datetime.date(2002, 1, 10), final=True)
        _db.session.add(tonight)
        _db.session.flush()
        t_champ = Player(game_night_id=tonight.id, people_id=champion.id)
        t_under = Player(game_night_id=tonight.id, people_id=underdog.id)
        _db.session.add_all([t_champ, t_under])
        _db.session.flush()
        t_gng = GameNightGame(game_night_id=tonight.id, game_id=game.id, round=1)
        _db.session.add(t_gng)
        _db.session.flush()
        _db.session.add(Result(game_night_game_id=t_gng.id, player_id=t_under.id, position=1))
        _db.session.add(Result(game_night_game_id=t_gng.id, player_id=t_champ.id, position=2))
        _db.session.commit()

        assert _check_kingslayer(underdog.id, tonight.id) is True
        assert _check_kingslayer(champion.id, tonight.id) is False

        Result.query.filter_by(game_night_game_id=t_gng.id).delete()
        _db.session.delete(t_gng)
        _db.session.delete(t_champ)
        _db.session.delete(t_under)
        PersonBadge.query.filter_by(game_night_id=tonight.id).delete()
        _db.session.delete(tonight)
        for gng in prior_gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in prior_players:
            _db.session.delete(pl)
        for gn in prior_nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        _db.session.delete(champion)
        _db.session.delete(underdog)
        _db.session.delete(game)
        _db.session.commit()
```

### 14b — `grudge_match` positive test

Add after `test_grudge_match_does_not_earn_before_10_shared_games`:

```python
def test_grudge_match_earns_after_10_shared_games_of_same_type(app, db):
    """grudge_match earns when person has played the same game vs same opponent 10+ times."""
    from app.services.badge_services import _check_grudge_match

    with app.app_context():
        game = Game(name=f"GrudgeGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(first_name="Grudge", last_name="One",
                        email=f"grudge1_{uuid.uuid4().hex[:6]}@test.invalid")
        rival = Person(first_name="Grudge", last_name="Two",
                       email=f"grudge2_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all([game, person, rival])
        _db.session.flush()

        nights, players, gngs = [], [], []
        for i in range(10):
            gn = GameNight(date=datetime.date(2003, 1, i + 1), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)
            pl = Player(game_night_id=gn.id, people_id=person.id)
            rv = Player(game_night_id=gn.id, people_id=rival.id)
            _db.session.add_all([pl, rv])
            _db.session.flush()
            players.extend([pl, rv])
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=pl.id, position=1))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=rv.id, position=2))
        _db.session.commit()

        assert _check_grudge_match(person.id, nights[-1].id) is True
        assert _check_grudge_match(rival.id, nights[-1].id) is True

        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in players:
            _db.session.delete(pl)
        for gn in nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(rival)
        _db.session.delete(game)
        _db.session.commit()
```

- [ ] **Run both new tests**
```bash
pytest tests/services/test_badge_services.py -x -q -k "kingslayer or grudge" 2>&1 | tail -10
```

- [ ] **Commit**
```bash
git add tests/services/test_badge_services.py
git commit -m "test: add positive-path tests for kingslayer and grudge_match (both had zero earn-case coverage)"
```

---

## Task 15: Add missing positive-path tests — `upset_special` and `early_bird`

**Files:**
- Modify: `tests/services/test_badge_services.py`

Both badges had zero tests exercising the earn condition; a stub returning `False` was undetectable.

### 15a — `upset_special` positive test

Add after the existing upset_special test (currently only `test_social_butterfly_does_not_earn_without_universal_play` — add before it):

```python
def test_upset_special_earns_when_beating_dominant_opponent(app, db):
    """upset_special earns when you beat an opponent who had 80%+ win rate against you (min 5 shared games)."""
    from app.services.badge_services import _check_upset_special

    with app.app_context():
        game = Game(name=f"UpsetGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        underdog = Person(first_name="Upset", last_name="Hero",
                          email=f"upset_hero_{uuid.uuid4().hex[:6]}@test.invalid")
        dominant = Person(first_name="Upset", last_name="Dominant",
                          email=f"upset_dom_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all([game, underdog, dominant])
        _db.session.flush()

        # 5 prior games: dominant wins all 5
        prior_nights, prior_players, prior_gngs = [], [], []
        for i in range(5):
            gn = GameNight(date=datetime.date(2004, 1, i + 1), final=True)
            _db.session.add(gn)
            _db.session.flush()
            prior_nights.append(gn)
            und_pl = Player(game_night_id=gn.id, people_id=underdog.id)
            dom_pl = Player(game_night_id=gn.id, people_id=dominant.id)
            _db.session.add_all([und_pl, dom_pl])
            _db.session.flush()
            prior_players.extend([und_pl, dom_pl])
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            prior_gngs.append(gng)
            # Dominant wins (lower position = better)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=dom_pl.id, position=1))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=und_pl.id, position=2))

        # Tonight: underdog wins
        tonight = GameNight(date=datetime.date(2004, 1, 10), final=True)
        _db.session.add(tonight)
        _db.session.flush()
        t_und = Player(game_night_id=tonight.id, people_id=underdog.id)
        t_dom = Player(game_night_id=tonight.id, people_id=dominant.id)
        _db.session.add_all([t_und, t_dom])
        _db.session.flush()
        t_gng = GameNightGame(game_night_id=tonight.id, game_id=game.id, round=1)
        _db.session.add(t_gng)
        _db.session.flush()
        _db.session.add(Result(game_night_game_id=t_gng.id, player_id=t_und.id, position=1))
        _db.session.add(Result(game_night_game_id=t_gng.id, player_id=t_dom.id, position=2))
        _db.session.commit()

        assert _check_upset_special(underdog.id, tonight.id) is True
        assert _check_upset_special(dominant.id, tonight.id) is False

        Result.query.filter_by(game_night_game_id=t_gng.id).delete()
        _db.session.delete(t_gng)
        _db.session.delete(t_und)
        _db.session.delete(t_dom)
        PersonBadge.query.filter_by(game_night_id=tonight.id).delete()
        _db.session.delete(tonight)
        for gng in prior_gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in prior_players:
            _db.session.delete(pl)
        for gn in prior_nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        _db.session.delete(underdog)
        _db.session.delete(dominant)
        _db.session.delete(game)
        _db.session.commit()
```

### 15b — `early_bird` positive test

Add after the existing early_bird negative test (or near the multi_night tests):

```python
def test_early_bird_earns_after_being_first_10_times(app, db):
    """early_bird earns when person was first to register at 10+ finalized game nights."""
    from app.services.badge_services import _check_early_bird

    with app.app_context():
        game = Game(name=f"EBGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        early = Person(first_name="Early", last_name="Bird",
                       email=f"early_{uuid.uuid4().hex[:6]}@test.invalid")
        late = Person(first_name="Late", last_name="Bird",
                      email=f"late_{uuid.uuid4().hex[:6]}@test.invalid")
        _db.session.add_all([game, early, late])
        _db.session.flush()

        nights, players, gngs = [], [], []
        for i in range(10):
            gn = GameNight(date=datetime.date(2005, 1, i + 1), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)
            # early registers first (lower Player.id)
            early_pl = Player(game_night_id=gn.id, people_id=early.id)
            _db.session.add(early_pl)
            _db.session.flush()
            late_pl = Player(game_night_id=gn.id, people_id=late.id)
            _db.session.add(late_pl)
            _db.session.flush()
            players.extend([early_pl, late_pl])
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=early_pl.id, position=1))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=late_pl.id, position=2))
        _db.session.commit()

        assert _check_early_bird(early.id, nights[-1].id) is True
        assert _check_early_bird(late.id, nights[-1].id) is False

        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in players:
            _db.session.delete(pl)
        for gn in nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        _db.session.delete(early)
        _db.session.delete(late)
        _db.session.delete(game)
        _db.session.commit()
```

- [ ] **Run both new tests**
```bash
pytest tests/services/test_badge_services.py -x -q -k "upset_special or early_bird" 2>&1 | tail -10
```

- [ ] **Commit**
```bash
git add tests/services/test_badge_services.py
git commit -m "test: add positive-path tests for upset_special and early_bird"
```

---

## Task 16: Fix night_owl date-dependent test

**Files:**
- Modify: `tests/services/test_badge_services.py` (`multi_night_person` fixture)

The `multi_night_person` fixture starts from `datetime.date.today().replace(day=1) - timedelta(days=60)` and steps forward one day at a time. On some calendar dates, 5 consecutive days span two months, making `test_night_owl_earns_with_5_in_same_month` intermittently fail.

- [ ] **Find the `multi_night_person` fixture** (line ~517 in the test file) and change the base date to a fixed date:

Find:
```python
base = datetime.date.today().replace(day=1) - datetime.timedelta(days=60)
```
Replace with:
```python
base = datetime.date(2010, 6, 1)  # Fixed: June 2010 — same month guaranteed for first 25 days
```

- [ ] **Run night_owl test**
```bash
pytest tests/services/test_badge_services.py -x -q -k "night_owl" 2>&1 | tail -10
```

- [ ] **Commit**
```bash
git add tests/services/test_badge_services.py
git commit -m "test: pin multi_night_person fixture to fixed date — night_owl test was intermittently failing depending on calendar date"
```

---

## Task 17: Fix integration test assertions

**Files:**
- Modify: `tests/blueprints/test_game_night.py`

Three integration tests need stronger assertions.

### 17a — `test_finalize_route_triggers_badge_evaluation` — verify specific person + badge

Find `assert badge_count >= 1` and strengthen it:

```python
# Verify at minimum: winner earned first_blood
from app.models import Badge
first_blood = Badge.query.filter_by(key="first_blood").first()
assert first_blood is not None, "first_blood badge must exist in the catalog"
winner_earned = PersonBadge.query.filter_by(
    person_id=person_id, badge_id=first_blood.id
).first()
assert winner_earned is not None, "winner should have earned first_blood"
assert winner_earned.game_night_id == gn_id, "badge should be linked to the finalized night"
```

### 17b — `test_finalize_succeeds_even_if_badge_evaluation_raises` — verify `final` was persisted

After `assert resp.status_code in (200, 302)`, add:

```python
from app.models import GameNight as GN
updated = GN.query.get(gn_id)
assert updated.final is True, "Game night must be marked final even when badge evaluation raises"
```

- [ ] **Apply both fixes**

- [ ] **Run integration tests**
```bash
pytest tests/blueprints/test_game_night.py -x -q 2>&1 | tail -20
```

- [ ] **Commit**
```bash
git add tests/blueprints/test_game_night.py
git commit -m "test: strengthen finalize integration tests — verify specific badge awarded and final state persisted"
```

---

## Task 18: Fix user stats page test

**Files:**
- Modify: `tests/blueprints/test_stats.py`

`test_user_stats_page_includes_badges_context` only checks `b"Badges" in resp.data`. This passes even when no badge data is rendered.

- [ ] **Read the current test**
```bash
git show HEAD:tests/blueprints/test_stats.py
```

- [ ] **Replace the weak assertion** with one that verifies badge data when earned

```python
def test_user_stats_page_renders_earned_badges(auth_client, app, db):
    """user_stats page must render actual badge data for the current user."""
    import uuid
    from app.extensions import db as _db
    from app.models import Badge, PersonBadge
    from flask_login import current_user

    with app.app_context():
        # Create a test badge and award it to auth_client's user
        badge = Badge(
            key=f"test_stats_{uuid.uuid4().hex[:6]}",
            name="Stats Test Badge",
            description="test",
            icon="🧪",
        )
        _db.session.add(badge)
        _db.session.flush()

        # Get auth_client's user id
        resp = auth_client.get("/user_stats")
        # Find current user id via a known endpoint or by querying
        from app.models import Person
        user = Person.query.filter_by(email="test@test.com").first()
        if user is None:
            _db.session.delete(badge)
            _db.session.commit()
            pytest.skip("No test user found for stats test")

        pb = PersonBadge(person_id=user.id, badge_id=badge.id)
        _db.session.add(pb)
        _db.session.commit()

        resp = auth_client.get("/user_stats")
        assert resp.status_code == 200
        assert b"Stats Test Badge" in resp.data
        assert "🧪".encode() in resp.data

        PersonBadge.query.filter_by(badge_id=badge.id).delete()
        _db.session.delete(badge)
        _db.session.commit()
```

Note: if the test fixture email is different from `test@test.com`, adjust accordingly. Check `tests/conftest.py` for the test user email.

- [ ] **Check the test user email first**
```bash
grep -n "email\|Person\|auth" tests/conftest.py | head -20
```

- [ ] **Adjust the email in the test** to match what `auth_client` uses

- [ ] **Run the test**
```bash
pytest tests/blueprints/test_stats.py -x -q 2>&1 | tail -10
```

- [ ] **Commit**
```bash
git add tests/blueprints/test_stats.py
git commit -m "test: replace weak 'Badges' string check with real badge rendering assertion on user stats page"
```

---

## Final Verification

- [ ] **Run the complete test suite**
```bash
pytest tests/ -q 2>&1 | tail -30
```
Expected: all tests pass with no failures.

- [ ] **Run only badge-related tests for a quick summary**
```bash
pytest tests/services/test_badge_services.py tests/blueprints/test_game_night.py tests/blueprints/test_stats.py -v 2>&1 | tail -50
```

- [ ] **Review what changed**
```bash
git log --oneline main..HEAD
```

---

## Self-Review

**Spec coverage check:**
- ✅ Migration `now()` → `CURRENT_TIMESTAMP` (Backend C2)
- ✅ Race condition / non-atomic insert (Backend C1)
- ✅ Unfinalized night guard (Backend I9, QA M5)
- ✅ Re-finalization badge state (QA C2) — via un-finalize clears night badges
- ✅ Field allowlist (Security I2)
- ✅ Recap route (QA C1)
- ✅ Recap shows all 26 badges (QA I8) — via always storing game_night_id
- ✅ joinedload on `get_person_badges` and `get_recap_details` (Backend I4)
- ✅ `_check_bench_warmer` 1-player bug (QA C3)
- ✅ `_check_the_diplomat` zero-results bug (QA I4)
- ✅ `_check_opening_night` decoupled from current game_night_id (Backend I8, QA M1)
- ✅ `_check_founding_member` Night 1 semantics (QA I1)
- ✅ `_check_early_bird` finalized-only + N+1 fix (Backend I5, QA I7)
- ✅ `_check_nemesis` N+1 fix (Backend I3, QA I6)
- ✅ `_check_upset_special` O(n³) → O(beaten opponents) (Backend I3, QA I5)
- ✅ `_check_winning_streak` N+1 fix (Backend I3)
- ✅ `_check_the_closer` N+1 fix (Backend I3)
- ✅ `_check_the_oracle` N+1 fix (Backend I3)
- ✅ `db.text("wins DESC")` → ORM (Security I3, Backend M11)
- ✅ `_stub` dead code removed (QA M9)
- ✅ Tautological tests fixed (Test I1, I2, I3, I4, I6)
- ✅ Missing positive tests: kingslayer, grudge_match, upset_special, early_bird, century_club, variety_pack, social_butterfly
- ✅ Date-dependent night_owl fixture pinned (Test I14)
- ✅ Founding member test isolation (Test I9)
- ✅ Integration test `test_finalize_*` strengthened (Test I11, I12)
- ✅ Stats page test strengthened (Test I13)

**Items not addressed (intentional):**
- `_check_gracious_host` stale badge mid-year (Backend I7) — this is a design decision about point-in-time vs end-of-year semantics; left as-is with the existing behavior
- `_check_the_diplomat` scoping to entire night vs person's games (QA M2) — spec says "game night where every game ends in a tie", entire night is the correct scope
- Badge evaluation moving off request thread (Backend I6) — no background task infrastructure is in scope; synchronous is acceptable for the current scale
- Unbounded `String` columns on Badge model (Backend M12) — Postgres-only project, no MySQL migration planned
- Unauthenticated recap route (Security I1) — docstring explicitly marks it public; accepted design
- `down_revision` migration check (QA M3) — verify manually with `alembic history` before merging
- `earned_at` UTC timezone display (QA M6) — cosmetic, out of scope
