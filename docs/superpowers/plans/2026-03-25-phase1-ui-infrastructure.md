# Phase 1: UI Overhaul & Infrastructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace custom CSS with Tailwind CDN, introduce an icon sidebar + mobile bottom nav, set up the test infrastructure (pytest + Flask-Migrate), fix Docker housekeeping, and add a GitHub Actions CI pipeline — with zero behavior changes to the app.

**Architecture:** All templates inherit from `base.html`; replacing the nav structure and Tailwind CDN link there propagates to every page. Tailwind utility classes replace custom CSS classes throughout. Flask-Migrate is initialized in this phase so all future schema changes go through Alembic rather than `db.create_all()`.

**Tech Stack:** Tailwind CSS (CDN), HTMX (CDN — loaded now, used in Phase 2+), Flask-Migrate/Alembic, pytest + pytest-flask, GitHub Actions, Docker, ruff, mypy, bandit

**Spec:** `docs/superpowers/specs/2026-03-25-gamenight-redesign-design.md`

---

## File Map

### New files
- `pyproject.toml` — ruff, mypy, bandit, pytest config
- `requirements-dev.txt` — dev/test dependencies
- `.pre-commit-config.yaml` — pre-commit hooks (opt-in)
- `.dockerignore` — exclude .git, tests/, docs/, .env from image
- `.github/workflows/ci.yml` — CI pipeline + GHCR publish job
- `scripts/entrypoint.sh` — runs `flask db upgrade` then starts gunicorn (migration-safe startup)
- `tests/__init__.py`
- `tests/conftest.py` — app factory, test client, db fixtures
- `tests/test_smoke.py` — parameterized route smoke tests

### Modified files
- `requirements.txt` — add `flask-migrate`, `cachetools`
- `Dockerfile` — Python 3.11, fix layer order (requirements before app code), switch CMD to ENTRYPOINT via entrypoint.sh
- `docker-compose.game_night.yml` — remove host-bind volume mounts, add healthcheck, set `-w 1`
- `app/__init__.py` — init Flask-Migrate, remove `test_bp`, gate `db.create_all()` behind DEBUG
- `app/extensions.py` — add `migrate` extension instance
- `app/templates/base.html` — Tailwind CDN, HTMX CDN, icon sidebar, mobile bottom nav
- `app/templates/auth_base.html` — Tailwind, centered auth layout
- `app/static/css/styles.css` — cleared (kept as empty file for static serving)
- All content templates (see Task 6–10)

### Deleted files
- None in Phase 1 (fetch_bgg_data.py is deleted in Phase 2)

---

## Task 1: Project tooling setup (pyproject.toml + requirements-dev.txt)

**Prerequisite:** A Python 3.11 virtualenv must be active before running any pip or flask commands. If one doesn't exist yet: `python3.11 -m venv .venv && source .venv/bin/activate`.

**Files:**
- Create: `pyproject.toml`
- Create: `requirements-dev.txt`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP"]
ignore = ["E501"]

[tool.mypy]
python_version = "3.11"
ignore_missing_imports = true
warn_unused_ignores = true

[tool.bandit]
exclude_dirs = ["tests"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_classes = ["Test*"]
python_functions = ["test_*"]
```

- [ ] **Step 2: Create `requirements-dev.txt`**

```
ruff==0.4.4
mypy==1.10.0
bandit==1.7.8
pytest==8.2.0
pytest-flask==1.3.0
pytest-cov==5.0.0
pytest-mock==3.14.0
pre-commit==3.7.1
```

- [ ] **Step 3: Add `flask-migrate` and `cachetools` to `requirements.txt`**

Add to end of `requirements.txt`:
```
Flask-Migrate==4.0.7
cachetools==5.3.3
```

- [ ] **Step 4: Verify tools install**

```bash
pip install -r requirements.txt -r requirements-dev.txt
```
Expected: No errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml requirements-dev.txt requirements.txt
git commit -m "chore: add dev tooling and flask-migrate dependency"
```

---

## Task 2: Flask-Migrate initialization

**Files:**
- Modify: `app/extensions.py`
- Modify: `app/__init__.py`

- [ ] **Step 1: Add `migrate` to extensions**

In `app/extensions.py`, add:
```python
from flask_migrate import Migrate
migrate = Migrate()
```

- [ ] **Step 2: Update `app/__init__.py`**

Import `migrate` from extensions and initialize it. Replace `setup_database` and update `init_extensions` and `register_blueprints`.

Also remove the `test_bp` import from `app/blueprints/__init__.py` — the registration is removed below but the import line remains and will cause a ruff `F401` error:

```python
import logging
from flask import Flask
from flask_session import Session

from app.config import Config
from app.extensions import db, bcrypt, mail, login_manager, migrate


def init_extensions(app):
    """Initialize Flask extensions."""
    Session(app)
    db.init_app(app)
    bcrypt.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)


def register_blueprints(app):
    """Register Flask blueprints."""
    from app import blueprints
    app.register_blueprint(blueprints.auth_bp)
    app.register_blueprint(blueprints.admin_bp)
    app.register_blueprint(blueprints.game_night_bp)
    app.register_blueprint(blueprints.games_bp)
    app.register_blueprint(blueprints.voting_bp)
    app.register_blueprint(blueprints.reminders_bp)
    app.register_blueprint(blueprints.main_bp)
    app.register_blueprint(blueprints.api_bp)
    # test_bp removed — was a debug artifact registered unconditionally


def setup_logging():
    """Configure logging."""
    logging.basicConfig(level=logging.DEBUG)


def setup_database(app):
    """Register the user_loader callback for Flask-Login."""
    from app.models import Person

    @login_manager.user_loader
    def load_user(user_id):
        return Person.query.get(int(user_id))


def start_schedulers(app):
    """Start the background scheduler for reminders."""
    from app.services.reminders_services import start_scheduler
    start_scheduler(app)


def create_app():
    """Factory function to create a Flask app instance."""
    app = Flask(__name__)
    app.config.from_object(Config)

    setup_logging()
    init_extensions(app)
    setup_database(app)
    register_blueprints(app)
    start_schedulers(app)

    return app
```

- [ ] **Step 3: Initialize migrations**

**Prerequisite:** `export FLASK_APP=app` (required for all `flask` CLI commands).

**Brownfield check:** If the database already has tables (existing production schema), run `flask db stamp head` immediately after `flask db init` and BEFORE `flask db migrate`. This marks the current schema as the baseline without touching the DB. Skip `flask db upgrade` in that case — the schema is already current.

```bash
export FLASK_APP=app
flask db init
# For brownfield only (DB already has tables):
#   flask db stamp head
flask db migrate -m "initial schema"
flask db upgrade
```

**SQL view warning:** After `flask db migrate`, open the generated migration file and inspect it. Models backed by SQL views (`GamesIndex`, `UserRecentFutureGameNight`, etc.) must NOT appear as `CREATE TABLE` statements. If they do, delete those statements from the migration before running `flask db upgrade` — Alembic cannot manage views. Consider adding an `include_object` hook to `migrations/env.py` to permanently exclude view-backed models from autogeneration.

Expected: `migrations/` directory created, initial migration applied (or stamped for brownfield).

- [ ] **Step 4: Commit**

```bash
git add app/extensions.py app/__init__.py migrations/
git commit -m "chore: initialize flask-migrate, remove test_bp"
```

---

## Task 3: Docker housekeeping

**Files:**
- Create: `.dockerignore`
- Modify: `Dockerfile`
- Modify: `docker-compose.game_night.yml`

- [ ] **Step 1: Create `.dockerignore`**

```
.git
.github
.superpowers
tests/
docs/
*.pyc
__pycache__
.env
.env.*
*.md
.pre-commit-config.yaml
pyproject.toml
requirements-dev.txt
```

- [ ] **Step 2: Create `scripts/entrypoint.sh`**

**First, read the existing file:** `scripts/entrypoint.sh` already exists. Read it before overwriting — it likely contains cron job setup and a `gunicorn -w 4` invocation. Determine whether the cron jobs are still needed (APScheduler in `start_schedulers` likely replaces them). If the existing cron entries are dead code, discard them. If not, preserve the logic.

This script runs database migrations automatically on every container start, then hands off to gunicorn. Alembic migrations are idempotent, so running this on restart is safe.

```bash
#!/bin/sh
set -e

echo "Running database migrations..."
flask db upgrade

echo "Starting gunicorn..."
exec gunicorn -w 1 -b 0.0.0.0:8000 "app:create_app()"
```

Make it executable: the Dockerfile will handle this with `RUN chmod +x scripts/entrypoint.sh`.

- [ ] **Step 3: Fix `Dockerfile`**

Read the current Dockerfile, then update it so requirements are installed before app code is copied (better layer caching), upgrade to Python 3.11, and use the entrypoint script:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

RUN chmod +x scripts/entrypoint.sh

# Required so entrypoint.sh can run `flask db upgrade` without FLASK_APP set at runtime
ENV FLASK_APP=app

EXPOSE 8000

ENTRYPOINT ["scripts/entrypoint.sh"]
```

- [ ] **Step 4: Update `docker-compose.game_night.yml`**

Read the current file, then make these changes:
1. Remove the host-bind volume mounts for `app/templates` and `app/static` (the image must serve what was built into it)
2. Add a healthcheck
3. Remove any explicit `command:` override — the entrypoint handles startup now (no separate `-w 1` gunicorn command needed in compose)

The service definition should look like:
```yaml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/')"]
  interval: 30s
  timeout: 5s
  retries: 3
  start_period: 15s
```

Note: `curl` is not present in `python:3.11-slim`. Use the Python urllib approach above to avoid a silently broken healthcheck.

- [ ] **Step 5: Verify Docker build succeeds**

```bash
docker build -t gamenight:test .
```
Expected: Build completes with no errors.

- [ ] **Step 6: Commit**

```bash
git add .dockerignore Dockerfile docker-compose.game_night.yml scripts/entrypoint.sh
git commit -m "chore: fix dockerfile layer order, upgrade to python 3.11, add migration entrypoint"
```

---

## Task 4: Test infrastructure

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Create `tests/__init__.py`**

Empty file.

- [ ] **Step 2: Create `tests/conftest.py`**

```python
import os
import unittest.mock
import pytest
from app import create_app
from app.extensions import db as _db


@pytest.fixture(scope="session")
def app():
    """Create a test Flask app using the test PostgreSQL database."""
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    os.environ["FLASK_DEBUG"] = "1"
    os.environ["SECRET_KEY"] = "test-secret-key"

    # Patch APScheduler before create_app() — background threads fire during teardown
    # and hit a closed DB connection, causing noisy errors in CI logs.
    with unittest.mock.patch("app.start_schedulers"):
        app = create_app()

    # Set SESSION_TYPE after create_app() so the app config is already initialised.
    # Setting it via os.environ before create_app() does not work with flask-session.
    app.config["SESSION_TYPE"] = "null"
    app.config["TESTING"] = True
    app.config["WTF_CSRF_ENABLED"] = False
    # Do NOT set SERVER_NAME — it breaks url_for() resolution in tests.
    return app


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
```

- [ ] **Step 3: Write smoke tests**

**Before writing:** Run `flask routes` to get the exact registered route paths. The routes below are derived from reading the blueprint files — verify each one matches `flask routes` output before running.

```python
# tests/test_smoke.py
import pytest


# Routes that redirect to login when unauthenticated
# Verify exact paths with: flask routes
REDIRECT_ROUTES = [
    "/",
    "/games/",
    "/wishlist",      # games.wishlist — no /games/ prefix
    "/user_stats",    # games.user_stats — no /games/ prefix
]

# Routes that require admin
ADMIN_ROUTES = [
    "/admin/",
]

# Auth routes — auth_bp has no url_prefix, so routes are at root, not /auth/
AUTH_ROUTES = [
    "/login",
    "/signup",
    "/forgot_password",
]


@pytest.mark.parametrize("route", REDIRECT_ROUTES)
def test_authenticated_route_redirects_when_logged_out(client, route):
    response = client.get(route)
    assert response.status_code in (302, 301), f"{route} should redirect unauthenticated users"


@pytest.mark.parametrize("route", REDIRECT_ROUTES)
def test_authenticated_route_loads_when_logged_in(auth_client, route):
    response = auth_client.get(route)
    assert response.status_code == 200, f"{route} returned {response.status_code}"


@pytest.mark.parametrize("route", AUTH_ROUTES)
def test_auth_routes_load(client, route):
    response = client.get(route)
    assert response.status_code == 200, f"{route} returned {response.status_code}"


@pytest.mark.parametrize("route", ADMIN_ROUTES)
def test_admin_routes_load_for_admin(admin_client, route):
    response = admin_client.get(route)
    assert response.status_code == 200, f"{route} returned {response.status_code}"
```

**Add seed fixture to `conftest.py`** (required for parameterized routes with IDs):

```python
@pytest.fixture(scope="session")
def seed_data(db, app):
    """Minimal seed: one Game, one GameNight for routes with path params.

    Read app/models.py first to confirm field names before writing this fixture.
    Adjust field names to match the actual model definitions.
    """
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
```

Then add parameterized tests for routes with IDs (after seed_data is confirmed working):

```python
def test_view_game_loads(auth_client, seed_data):
    response = auth_client.get(f"/games/{seed_data['game_id']}")
    assert response.status_code == 200

def test_view_game_night_loads(auth_client, seed_data):
    response = auth_client.get(f"/game_nights/{seed_data['game_night_id']}")
    assert response.status_code == 200
```

- [ ] **Step 4: Set TEST_DATABASE_URL and run tests**

```bash
export TEST_DATABASE_URL="postgresql://postgres:postgres@localhost:5432/gamenight_test"
flask routes  # Verify route paths match what's in the smoke test lists above
pytest tests/test_smoke.py -v
```
Expected: All smoke tests pass. If a route returns 404, check `flask routes` output and correct the path in the test.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: add pytest infrastructure and route smoke tests"
```

---

## Task 5: GitHub Actions CI pipeline

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.pre-commit-config.yaml`

- [ ] **Step 1: Create `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  ci:
    runs-on: ubuntu-latest

    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: gamenight_test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
        ports:
          - 5432:5432

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Cache pip dependencies
        uses: actions/cache@v4
        with:
          path: ~/.cache/pip
          key: ${{ runner.os }}-pip-${{ hashFiles('requirements.txt', 'requirements-dev.txt') }}
          restore-keys: |
            ${{ runner.os }}-pip-

      - name: Install dependencies
        run: pip install -r requirements.txt -r requirements-dev.txt

      - name: Lint (ruff)
        run: |
          ruff check .
          ruff format --check .

      - name: Type check (mypy)
        run: mypy app/ tests/

      - name: Security scan (bandit)
        run: bandit -r app/ -ll -ii

      - name: Docker build check
        run: docker build -t gamenight:ci .

      - name: Run tests
        env:
          TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/gamenight_test
          SECRET_KEY: ci-secret-key
          FLASK_DEBUG: "1"
        run: pytest --cov=app --cov-report=term-missing --cov-fail-under=60 -v

  publish:
    name: Publish image to GHCR
    runs-on: ubuntu-latest
    needs: ci
    if: github.ref == 'refs/heads/main' && github.event_name == 'push'
    permissions:
      contents: read
      packages: write

    steps:
      - uses: actions/checkout@v4

      - name: Log in to GitHub Container Registry
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build and push image
        uses: docker/build-push-action@v5
        with:
          context: .
          push: true
          tags: ghcr.io/${{ github.repository }}:latest
```

The `publish` job only runs after `ci` passes and only on direct pushes to `main` (not PRs). It uses `GITHUB_TOKEN` — no extra secrets required. The homelab webhook continues to work as-is: it restarts the container pulling from GHCR, which now only contains CI-passing builds.

**Homelab action required:** After the first successful publish, verify the homelab's Docker restart webhook pulls from `ghcr.io/cner-smith/game_night_app:latest` (not a local build). If it currently builds locally, update the webhook command to `docker pull ghcr.io/cner-smith/game_night_app:latest && docker compose ... up -d`.

**Note for the repository owner:** The GHCR package visibility defaults to private for new packages. After the first publish, go to the package settings on GitHub and set it to public (or configure the homelab's Docker daemon with a GHCR auth token). Public is simpler for homelab use and appropriate for a personal project.

- [ ] **Step 2: Create `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.4.4  # Must match requirements-dev.txt
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.10.0  # Must match requirements-dev.txt
    hooks:
      - id: mypy
        args: [--ignore-missing-imports]
        additional_dependencies: [types-cachetools]
```

- [ ] **Step 3: Commit**

```bash
git add .github/ .pre-commit-config.yaml
git commit -m "ci: add github actions pipeline with lint, typecheck, security scan, tests, and ghcr publish"
```

---

## Task 6: Base template — Tailwind + new navigation

**Files:**
- Modify: `app/templates/base.html`
- Modify: `app/static/css/styles.css`

This is the most important template change — everything else inherits from it.

- [ ] **Step 1: Clear `styles.css`**

Replace the content of `app/static/css/styles.css` with a minimal override file:

```css
/* Custom overrides — Tailwind handles the rest */

/* Sidebar width token used in layout */
:root {
  --sidebar-width: 4rem;
}

/* Flash message animation */
.flash-message {
  animation: slideIn 0.2s ease-out;
}

@keyframes slideIn {
  from { opacity: 0; transform: translateY(-8px); }
  to   { opacity: 1; transform: translateY(0); }
}
```

- [ ] **Step 2: Rewrite `base.html`**

```html
<!DOCTYPE html>
<html lang="en" class="h-full">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{% block title %}Game Night{% endblock %}</title>

  <!-- Favicons -->
  <link rel="icon" href="{{ url_for('static', filename='images/favicon.svg') }}" type="image/svg+xml" />
  <link rel="icon" href="{{ url_for('static', filename='images/favicon.ico') }}" sizes="any" />
  <link rel="apple-touch-icon" sizes="180x180" href="{{ url_for('static', filename='images/apple-touch-icon.png') }}" />
  <link rel="manifest" href="{{ url_for('static', filename='images/site.webmanifest') }}" />

  <!-- Tailwind CSS CDN -->
  <script src="https://cdn.tailwindcss.com"></script>
  <script>
    tailwind.config = {
      theme: {
        extend: {
          colors: {
            brand: { DEFAULT: '#dc2626', hover: '#b91c1c' }
          }
        }
      }
    }
  </script>

  <!-- HTMX CDN (used in Phase 2+) -->
  <script src="https://unpkg.com/htmx.org@1.9.12" defer></script>

  <!-- Custom overrides -->
  <link rel="stylesheet" href="{{ url_for('static', filename='css/styles.css') }}" />
</head>
<body class="h-full bg-stone-50 text-stone-800">

  <!-- ===== DESKTOP SIDEBAR ===== -->
  <aside class="hidden md:flex fixed inset-y-0 left-0 w-16 flex-col bg-white border-r border-stone-200 z-30">
    <!-- Logo -->
    <a href="{{ url_for('main.index') }}" class="flex items-center justify-center h-16 border-b border-stone-200">
      <img src="{{ url_for('static', filename='images/logo.png') }}" alt="Game Night" class="h-8 w-8 object-contain" />
    </a>

    <!-- Nav links -->
    <nav class="flex flex-col items-center gap-1 flex-1 py-4">
      {% set nav_items = [
        ('main.index',    'Home',    'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6'),
        ('games.games_index', 'Games', 'M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10'),
        ('games.wishlist', 'Wishlist', 'M4.318 6.318a4.5 4.5 0 000 6.364L12 20.364l7.682-7.682a4.5 4.5 0 00-6.364-6.364L12 7.636l-1.318-1.318a4.5 4.5 0 00-6.364 0z'),
        ('games.user_stats', 'Stats', 'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z'),
      ] %}

      {% for endpoint, label, icon_path in nav_items %}
      <a href="{{ url_for(endpoint) }}"
         title="{{ label }}"
         class="group relative flex items-center justify-center w-10 h-10 rounded-lg text-stone-500 hover:bg-stone-100 hover:text-red-600 transition-colors">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="{{ icon_path }}" />
        </svg>
        <span class="absolute left-14 px-2 py-1 bg-stone-800 text-white text-xs rounded opacity-0 group-hover:opacity-100 whitespace-nowrap pointer-events-none transition-opacity z-50">
          {{ label }}
        </span>
      </a>
      {% endfor %}

      {% if current_user.is_authenticated and (current_user.admin or current_user.owner) %}
      <a href="{{ url_for('admin.admin_page') }}"
         title="Admin"
         class="group relative flex items-center justify-center w-10 h-10 rounded-lg text-amber-500 hover:bg-amber-50 hover:text-amber-600 transition-colors">
        <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
        </svg>
        <span class="absolute left-14 px-2 py-1 bg-stone-800 text-white text-xs rounded opacity-0 group-hover:opacity-100 whitespace-nowrap pointer-events-none transition-opacity z-50">Admin</span>
      </a>
      {% endif %}
    </nav>

    <!-- User + sign out at bottom -->
    <!-- Guard with is_authenticated — Phase 3 introduces public routes that use base.html -->
    {% if current_user.is_authenticated %}
    <div class="flex flex-col items-center gap-1 pb-4 border-t border-stone-200 pt-4">
      <a href="{{ url_for('auth.manage_user') }}"
         title="{{ current_user.first_name }} {{ current_user.last_name }}"
         class="group relative flex items-center justify-center w-10 h-10 rounded-lg bg-red-600 text-white text-xs font-bold hover:bg-red-700 transition-colors">
        {{ current_user.first_name[0] }}{{ current_user.last_name[0] }}
        <span class="absolute left-14 px-2 py-1 bg-stone-800 text-white text-xs rounded opacity-0 group-hover:opacity-100 whitespace-nowrap pointer-events-none transition-opacity z-50">
          {{ current_user.first_name }} {{ current_user.last_name }}
        </span>
      </a>
      <form action="{{ url_for('auth.logout') }}" method="POST">
        <button type="submit"
                title="Sign Out"
                class="group relative flex items-center justify-center w-10 h-10 rounded-lg text-stone-400 hover:bg-red-50 hover:text-red-600 transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
          </svg>
          <span class="absolute left-14 px-2 py-1 bg-stone-800 text-white text-xs rounded opacity-0 group-hover:opacity-100 whitespace-nowrap pointer-events-none transition-opacity z-50">Sign Out</span>
        </button>
      </form>
    </div>
    {% endif %}
  </aside>

  <!-- ===== MOBILE TOP BAR ===== -->
  <header class="md:hidden fixed top-0 left-0 right-0 h-14 bg-white border-b border-stone-200 flex items-center px-4 z-30">
    <img src="{{ url_for('static', filename='images/logo.png') }}" alt="" class="h-7 w-7 object-contain mr-2" />
    <span class="font-semibold text-stone-800">Game Night</span>
  </header>

  <!-- ===== MAIN CONTENT ===== -->
  <main class="md:ml-16 pt-14 md:pt-0 pb-20 md:pb-0 min-h-full">

    <!-- Flash messages -->
    {% with messages = get_flashed_messages(with_categories=true) %}
    {% if messages %}
    <div class="px-4 pt-4 space-y-2">
      {% for category, message in messages %}
      <div class="flash-message rounded-lg px-4 py-3 text-sm font-medium
        {% if category == 'success' %}bg-green-50 text-green-800 border border-green-200
        {% elif category == 'danger' or category == 'error' %}bg-red-50 text-red-800 border border-red-200
        {% elif category == 'warning' %}bg-amber-50 text-amber-800 border border-amber-200
        {% else %}bg-blue-50 text-blue-800 border border-blue-200{% endif %}">
        {{ message }}
      </div>
      {% endfor %}
    </div>
    {% endif %}
    {% endwith %}

    <!-- Page content -->
    <div class="px-4 py-6 max-w-5xl mx-auto">
      {% block content %}{% endblock %}
    </div>
  </main>

  <!-- ===== MOBILE BOTTOM NAV ===== -->
  <nav class="md:hidden fixed bottom-0 left-0 right-0 bg-white border-t border-stone-200 flex z-30">
    {% set mobile_nav = [
      ('main.index',        'Home',    'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6'),
      ('games.games_index', 'Games',   'M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10'),
      ('games.user_stats',  'Stats',   'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z'),
      ('auth.manage_user',  'Me',      'M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z'),
    ] %}
    {% for endpoint, label, icon_path in mobile_nav %}
    <a href="{{ url_for(endpoint) }}" class="flex flex-col items-center justify-center flex-1 py-2 text-stone-500 hover:text-red-600 transition-colors">
      <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mb-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="{{ icon_path }}" />
      </svg>
      <span class="text-xs">{{ label }}</span>
    </a>
    {% endfor %}
    {% if current_user.admin or current_user.owner %}
    <a href="{{ url_for('admin.admin_page') }}" class="flex flex-col items-center justify-center flex-1 py-2 text-amber-500 hover:text-amber-600 transition-colors">
      <svg xmlns="http://www.w3.org/2000/svg" class="h-5 w-5 mb-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" /><path stroke-linecap="round" stroke-linejoin="round" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
      </svg>
      <span class="text-xs">Admin</span>
    </a>
    {% endif %}
  </nav>

</body>
</html>
```

- [ ] **Step 3: Create placeholder static image files**

The base template references `favicon.svg`, `favicon.ico`, `apple-touch-icon.png`, `site.webmanifest`, and `logo.png`. Without them every page load produces 404 errors and the sidebar logo is broken. Create minimal placeholders now; replace with real assets later.

```bash
mkdir -p app/static/images

# Minimal 1×1 transparent PNG for apple-touch-icon and logo
python3 -c "
import base64, pathlib
# 1x1 transparent PNG (68 bytes)
png = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
pathlib.Path('app/static/images/apple-touch-icon.png').write_bytes(png)
pathlib.Path('app/static/images/logo.png').write_bytes(png)
"

# Minimal SVG favicon
cat > app/static/images/favicon.svg << 'EOF'
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <text y=".9em" font-size="90">🎲</text>
</svg>
EOF

# Copy SVG as ICO placeholder (browsers handle this gracefully)
cp app/static/images/favicon.svg app/static/images/favicon.ico

# Minimal web manifest
cat > app/static/images/site.webmanifest << 'EOF'
{"name":"Game Night","short_name":"GameNight","icons":[],"start_url":"/","display":"standalone"}
EOF
```

- [ ] **Step 4: Run smoke tests to verify base template renders**

```bash
pytest tests/test_smoke.py -v
```
Expected: All pass. If a template error appears (e.g., `url_for` endpoint not found), check the blueprint URL map with `flask routes`.

- [ ] **Step 5: Commit**

```bash
git add app/templates/base.html app/static/css/styles.css app/static/images/
git commit -m "feat: replace custom CSS with Tailwind CDN, add icon sidebar and mobile bottom nav"
```

---

## Task 7: Auth templates

**Files:**
- Modify: `app/templates/auth_base.html`
- Modify: `app/templates/login.html`
- Modify: `app/templates/signup.html`
- Modify: `app/templates/forgot_password.html`
- Modify: `app/templates/update_password.html`

Auth pages use `auth_base.html` (not `base.html`) since they don't show the nav. Rewrite `auth_base.html` as a centered card layout, then update each auth form to use Tailwind classes.

- [ ] **Step 0: Read all files in this task before editing**

```bash
# Read each file to understand current structure, form field names, and any custom logic
# before overwriting. Template variables come from the route — check app/blueprints/auth.py
# to confirm what context variables are passed to each template.
```

- [ ] **Step 1: Rewrite `auth_base.html`**

```html
<!DOCTYPE html>
<html lang="en" class="h-full bg-stone-50">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>{% block title %}Game Night{% endblock %}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="icon" href="{{ url_for('static', filename='images/favicon.svg') }}" type="image/svg+xml" />
</head>
<body class="h-full flex items-center justify-center bg-stone-50">
  <div class="w-full max-w-sm px-6">
    <div class="text-center mb-8">
      <img src="{{ url_for('static', filename='images/logo.png') }}" alt="Game Night" class="h-12 w-12 mx-auto mb-3 object-contain" />
      <h1 class="text-2xl font-bold text-stone-800">Game Night</h1>
    </div>
    <div class="bg-white rounded-2xl shadow-sm border border-stone-200 p-8">
      {% with messages = get_flashed_messages(with_categories=true) %}
      {% if messages %}
        {% for category, message in messages %}
        <div class="mb-4 rounded-lg px-4 py-3 text-sm
          {% if category == 'success' %}bg-green-50 text-green-800 border border-green-200
          {% elif category == 'danger' or category == 'error' %}bg-red-50 text-red-800 border border-red-200
          {% else %}bg-blue-50 text-blue-800 border border-blue-200{% endif %}">
          {{ message }}
        </div>
        {% endfor %}
      {% endif %}
      {% endwith %}
      {% block content %}{% endblock %}
    </div>
  </div>
</body>
</html>
```

- [ ] **Step 2: Update auth form templates**

For each of `login.html`, `signup.html`, `forgot_password.html`, `update_password.html`:
- Replace all custom CSS class names with Tailwind equivalents
- Input fields: `class="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500 focus:border-transparent"`
- Labels: `class="block text-sm font-medium text-stone-700 mb-1"`
- Primary buttons: `class="w-full rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 transition-colors"`
- Links: `class="text-red-600 hover:text-red-700 underline"`

- [ ] **Step 3: Run smoke tests**

```bash
pytest tests/test_smoke.py -k "auth" -v
```
Expected: All auth routes return 200.

- [ ] **Step 4: Commit**

```bash
git add app/templates/auth_base.html app/templates/login.html app/templates/signup.html app/templates/forgot_password.html app/templates/update_password.html
git commit -m "feat: redesign auth templates with Tailwind"
```

---

## Task 8: Game library templates

**Files:**
- Modify: `app/templates/games_index.html`
- Modify: `app/templates/view_game.html`
- Modify: `app/templates/add_game.html`
- Modify: `app/templates/add_to_wishlist.html`
- Modify: `app/templates/wishlist.html`
- Modify: `app/templates/user_stats.html`

**Before editing any template in this task:** Read the current file and the corresponding route in `app/blueprints/games.py` to understand what context variables are available (e.g., `games`, `game`, `wishlist_items`). Do not assume variable names — read the route first.

Apply Tailwind to each template. The consistent patterns to use throughout:

- **Page headings:** `<h1 class="text-2xl font-bold text-stone-800 mb-6">`
- **Cards:** `<div class="bg-white rounded-xl border border-stone-200 shadow-sm p-5">`
- **Card grids:** `<div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">`
- **Tables:** `<table class="w-full text-sm">` with `<th class="text-left text-xs font-semibold text-stone-500 uppercase tracking-wide pb-2">` and `<td class="py-2 text-stone-700">`
- **Primary action button:** `<a class="inline-flex items-center rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 transition-colors">`
- **Secondary button:** `class="inline-flex items-center rounded-lg border border-stone-300 px-4 py-2 text-sm font-medium text-stone-700 hover:bg-stone-50 transition-colors"`
- **Form inputs:** same as auth templates above

Update each template, replacing all old class names with the patterns above.

- [ ] **Step 1: Update `games_index.html`** — game grid with search/filter form at top, game cards below
- [ ] **Step 2: Update `view_game.html`** — two-column layout (game info left, stats/leaderboard right)
- [ ] **Step 3: Update `add_game.html`** — simple form card (will be replaced with HTMX search in Phase 2, but needs Tailwind now)
- [ ] **Step 4: Update `add_to_wishlist.html`**, `wishlist.html` — card grid for wishlist items
- [ ] **Step 5: Update `user_stats.html`** — stats cards + sortable table

- [ ] **Step 6: Run smoke tests**

```bash
pytest tests/test_smoke.py -v
```
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add app/templates/games_index.html app/templates/view_game.html app/templates/add_game.html app/templates/add_to_wishlist.html app/templates/wishlist.html app/templates/user_stats.html
git commit -m "feat: redesign game library templates with Tailwind"
```

---

## Task 9: Game night flow templates

**Files:**
- Modify: `app/templates/index.html`
- Modify: `app/templates/start_game_night.html`
- Modify: `app/templates/view_game_night.html`
- Modify: `app/templates/all_game_nights.html`
- Modify: `app/templates/edit_game_night.html`
- Modify: `app/templates/add_game_to_night.html`
- Modify: `app/templates/nominate_game.html`
- Modify: `app/templates/log_results.html`

**Before editing any template in this task:** Read the current file and the corresponding route in `app/blueprints/game_night.py` (or `main.py` for `index.html`) to understand what context variables are passed. The dashboard (`index.html`) is particularly complex — read its route carefully before touching the template.

Apply the same Tailwind patterns from Task 8. `index.html` (the dashboard) gets special treatment:
- Hero section showing the next upcoming game night (date, player count, status)
- Quick action cards (Start Voting, View Games, etc.)
- Recent game nights list

- [ ] **Step 1: Update `index.html`** — dashboard with hero + quick actions
- [ ] **Step 2: Update `start_game_night.html`, `edit_game_night.html`** — form cards
- [ ] **Step 3: Update `view_game_night.html`** — game night detail with nominations/votes/results sections
- [ ] **Step 4: Update `all_game_nights.html`** — list/grid of past nights
- [ ] **Step 5: Update `add_game_to_night.html`, `nominate_game.html`, `log_results.html`** — action forms

- [ ] **Step 6: Run smoke tests**

```bash
pytest tests/test_smoke.py -v
```
Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add app/templates/index.html app/templates/start_game_night.html app/templates/view_game_night.html app/templates/all_game_nights.html app/templates/edit_game_night.html app/templates/add_game_to_night.html app/templates/nominate_game.html app/templates/log_results.html
git commit -m "feat: redesign game night flow templates with Tailwind"
```

---

## Task 10: Admin templates + email templates + README

**Files:**
- Modify: `app/templates/admin_page.html`
- Modify: `app/templates/add_person.html`
- Modify: `app/templates/manage_user.html`
- Modify: `app/templates/email_templates/reminder_body.html`
- Modify: `app/templates/email_templates/email_signature.html`
- Create/Modify: `README.md`
- Create: `CHANGELOG.md`

- [ ] **Step 1: Update admin templates** — `admin_page.html`, `add_person.html`, `manage_user.html`
  - Admin sections use amber accent (`amber-600`) to distinguish from standard red
  - Same card/table/button patterns as above

- [ ] **Step 2: Update email templates** — update inline styles in `reminder_body.html` and `email_signature.html` to use clean, modern inline CSS (email clients don't support Tailwind)

- [ ] **Step 3: Rewrite `README.md`**

```markdown
# Game Night

A board game night coordination app for a friend group. Track your game library, schedule nights, vote on what to play, and log results.

Hosted at: https://gamenight.sgammill.com

## Features
- Game library with BoardGameGeek integration
- Game night scheduling and ranked voting
- Player stats and leaderboards
- Wishlist
- Availability polls (shareable links, no login required)

## Local Development

### Prerequisites
- Python 3.11
- PostgreSQL 15+
- Docker (optional)

### Setup

```bash
git clone https://github.com/cner-smith/game_night_app
cd game_night_app
pip install -r requirements.txt -r requirements-dev.txt

# Copy and fill in your environment variables
cp .env.example .env

# Run database migrations
flask db upgrade

# Start the app
flask run
```

### Environment Variables

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `SECRET_KEY` | Flask session secret |
| `MAIL_SERVER` | SMTP server for email reminders |
| `MAIL_PORT` | SMTP port (default: 587) |
| `MAIL_USERNAME` | SMTP username |
| `MAIL_PASSWORD` | SMTP password |
| `MAIL_DEFAULT_SENDER` | From address for emails |

### Running Tests

Requires a PostgreSQL test database:

```bash
export TEST_DATABASE_URL="postgresql://user:password@localhost/gamenight_test"
pytest -v
```

### Docker

```bash
docker compose -f docker-compose.game_night.yml up --build -d
```

## Deployment

The app runs on a home lab via Docker Compose. See `docker-compose.game_night.yml`.

The container runs `flask db upgrade` automatically on startup via `scripts/entrypoint.sh` — no manual migration step is needed when deploying.

```bash
docker compose -f docker-compose.game_night.yml pull
docker compose -f docker-compose.game_night.yml up -d
```
```

- [ ] **Step 4: Create `.env.example`**

```bash
cat > .env.example << 'EOF'
# Database
DATABASE_URL=postgresql://user:password@localhost:5432/gamenight

# Flask
SECRET_KEY=change-me-in-production
FLASK_APP=app
FLASK_DEBUG=0

# Email (flask-mail)
MAIL_SERVER=smtp.example.com
MAIL_PORT=587
MAIL_USERNAME=
MAIL_PASSWORD=
MAIL_DEFAULT_SENDER=noreply@example.com

# Session
SESSION_TYPE=filesystem
EOF
```

- [ ] **Step 5: Create `CHANGELOG.md`**

```markdown
# Changelog

## [Unreleased]

### Changed
- Full UI redesign: Tailwind CSS replaces custom CSS, new icon sidebar + mobile bottom nav
- BGG API fully integrated: search-to-add flow, richer game detail pages
- Poll/availability system: shareable links, no login required to respond
- Test suite added: pytest + pytest-flask
- CI/CD: GitHub Actions pipeline (lint, type check, security scan, tests)
- Flask-Migrate (Alembic) added for database schema management
- Docker improvements: .dockerignore, fixed layer caching, healthcheck

### Removed
- Manual BGG data entry replaced by search flow
- Raw custom CSS (replaced by Tailwind utilities)
```

- [ ] **Step 6: Run full test suite**

```bash
pytest -v
```
Expected: All smoke tests pass.

- [ ] **Step 7: Run linter and type checker**

```bash
ruff check .
mypy app/ tests/
```
Fix any issues before committing.

- [ ] **Step 8: Final commit for Phase 1**

```bash
git add app/templates/admin_page.html app/templates/add_person.html app/templates/manage_user.html app/templates/email_templates/ README.md CHANGELOG.md .env.example
git commit -m "feat: complete phase 1 — tailwind UI overhaul, infrastructure, CI pipeline"
```

---

## Phase 1 Done ✓

The app is fully deployable at this point. All routes work, all templates use Tailwind, the sidebar/mobile nav is in place, CI runs on every push, Flask-Migrate is initialized, Docker is fixed.

**Before starting Phase 2:** verify all smoke tests pass in CI (push to GitHub and check the Actions tab).
