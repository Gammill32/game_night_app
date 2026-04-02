# Achievement Badges Review Fixes — Part 2

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Fix the remaining outstanding issues from the 4-reviewer code review of `feature/achievement-badges`.

**Context:** Part 1 (plan `2026-04-01-achievement-badges-review-fixes.md`) is fully complete — 12 commits on `feature/achievement-badges`. This plan covers the remaining actionable items.

**Branch:** `feature/achievement-badges`

**Tech Stack:** Python 3, Flask, SQLAlchemy, pytest, Alembic

---

## Task 1: Fix `test_gracious_host_does_not_earn_when_missed_a_night`

**Files:**
- Modify: `tests/services/test_badge_services.py`

**Problem:** The test claims to test "missed a night" but actually tests a `stranger` with zero attendance. The real negative case — a person who attended all-but-one nights — is never tested.

- [ ] Read the current test body to understand the fixture (`multi_night_person`) it uses
- [ ] Replace the test with two focused tests:
  1. `test_gracious_host_does_not_earn_when_missed_a_night` — create N finalized nights, person attends N-1, assert False
  2. Keep the existing positive test (`test_gracious_host_earns_with_perfect_attendance`) unchanged
- [ ] Run: `pytest tests/services/test_badge_services.py -x -q -k "gracious" 2>&1 | tail -10`
- [ ] Commit: `git commit -m "test: fix gracious_host negative test — actually test missing one night, not zero attendance"`

---

## Task 2: Add `jack_of_all_trades` 3-player test

**Files:**
- Modify: `tests/services/test_badge_services.py`

**Problem:** Only 2-player scenarios are tested. With 3 players, positions 1 and 2 both earn the badge (top half of 3 = positions 1–2); position 3 does not. This path is untested.

- [ ] Add test `test_jack_of_all_trades_earns_for_middle_player_in_3_player_game` — create a 3-player game night with one game, check that position 1 earns True, position 2 earns True, position 3 earns False
- [ ] Run: `pytest tests/services/test_badge_services.py -x -q -k "jack" 2>&1 | tail -10`
- [ ] Commit: `git commit -m "test: add 3-player scenario for jack_of_all_trades (middle player earns badge)"`

---

## Task 3: Verify CSRF protection is enabled

**Files:**
- Read: `app/__init__.py` or wherever the Flask app is configured
- Read: `app/extensions.py`

**Problem:** Flask-WTF CSRF protection should be globally enabled. The security review flagged it needs verification.

- [ ] Check if `CSRFProtect` is initialized on the app (grep for `CSRFProtect`, `WTF_CSRF`, `csrf`)
- [ ] If enabled: just confirm in a code comment or note — no change needed
- [ ] If NOT enabled: initialize it (`csrf = CSRFProtect(app)` in extensions or app factory)
- [ ] Commit only if a change was needed: `git commit -m "fix: enable Flask-WTF CSRF protection globally"`

---

## Task 4: Verify Alembic migration chain

**Files:**
- Read: `migrations/versions/` directory

**Problem:** The migration `8b9f3a3784a3` has `down_revision = '83f9da8656a8'`. There is also an untracked migration `c5d6e7f8a9b0_add_wishlist_votes.py` on the main branch. If that migration was merged before this branch was created and has a different revision ID as head, `alembic upgrade head` will fail with a branching error.

- [ ] Run: `alembic history --verbose 2>&1 | head -30` to see the chain
- [ ] Run: `alembic heads` to see if there are multiple heads
- [ ] If there is a branching conflict, update `down_revision` in `8b9f3a3784a3_add_achievement_badges.py` to point to the correct parent
- [ ] Commit if changed: `git commit -m "fix: correct migration down_revision to resolve alembic chain conflict"`

---

## Task 5: Fix mixed ORM style in `badge_services.py`

**Files:**
- Modify: `app/services/badge_services.py`

**Problem:** The file mixes `db.session.query(...)` (legacy SQLAlchemy 1.x) with `Model.query.filter_by(...)` (Flask-SQLAlchemy) and `db.session.get(Model, pk)` (SQLAlchemy 2.x). Standardize on `db.session.query(...)` / `db.session.get()` throughout (the forward-compatible style already used in most of the service-layer files).

Specifically: replace all instances of `Model.query.filter_by(...)`, `Model.query.filter(...)`, `Model.query.order_by(...)`, and `Model.query.count()` with `db.session.query(Model).filter_by(...)` etc. in `badge_services.py`.

Note: `Player.query.filter_by(game_night_id=..., people_id=...).first()` can become `db.session.query(Player).filter_by(game_night_id=..., people_id=...).first()`.

- [ ] Make the replacements throughout `badge_services.py`
- [ ] Run: `pytest tests/services/test_badge_services.py -x -q 2>&1 | tail -15`
- [ ] Commit: `git commit -m "refactor: standardize ORM style in badge_services — use db.session.query throughout"`

---

## Task 6: Fix deferred import in `badge_services.py`

**Files:**
- Modify: `app/services/badge_services.py`

**Problem:** `from sqlalchemy.orm import joinedload` is imported inside `get_person_badges` function body (deferred import). It should be at module level. Check if it's already imported at the top; if not, add it.

- [ ] Move `from sqlalchemy.orm import joinedload` to the top of `badge_services.py` (it's already imported in `game_night_services.py` this way)
- [ ] Remove the inline `from sqlalchemy.orm import joinedload` inside `get_person_badges`
- [ ] Run tests to confirm no breakage
- [ ] Commit: `git commit -m "fix: move joinedload import to module level in badge_services"`

---

## Task 7: Fix test fixtures — manual teardown → use `db` fixture rollback

**Files:**
- Modify: `tests/services/test_badge_services.py`

**Problem:** All badge test fixtures use manual `session.delete()` chains for teardown instead of the transaction-rollback pattern established in the project's `conftest.py`. This is fragile: if a fixture teardown crashes mid-sequence, data leaks into subsequent tests.

- [ ] Read `tests/conftest.py` to understand the existing `db` fixture scoping and rollback strategy
- [ ] Update badge test fixtures to use the same rollback approach (wrap fixture body in a transaction that's rolled back on teardown, rather than explicit deletes)
- [ ] Run the full test suite: `pytest tests/ -x -q 2>&1 | tail -20`
- [ ] Commit: `git commit -m "refactor: replace manual fixture teardown with transaction rollback in badge tests"`

---

## Final Verification

- [ ] Run full test suite: `pytest tests/ -q 2>&1 | tail -20`
- [ ] Confirm no failures
- [ ] Run: `git log --oneline main..HEAD` to review all commits on the feature branch
