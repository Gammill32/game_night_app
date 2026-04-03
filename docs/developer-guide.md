# Developer Guide

This guide is written for sgammill — the upstream repo owner — and covers everything needed to understand, run, and maintain this codebase independently.

## Background

This is a fork of [game_night_app](https://github.com/Gammill32/game_night_app). It was redesigned and extended before being PR'd back upstream. This fork is the **source of truth** for all changes; the homelab deployment at [gamenight.sgammill.com](https://gamenight.sgammill.com) runs the production version.

---

## What Changed From the Original

### Infrastructure
- **Flask-Migrate (Alembic)** added for database schema management — all schema changes now go through versioned migrations in `migrations/versions/`
- **GitHub Actions CI** runs on every push/PR: lint → type check → security scan → pytest → Docker build → image publish to GHCR
- **Dockerfile** upgraded from Python 3.10 → 3.11; entrypoint runs `flask db upgrade` automatically before starting gunicorn
- **Tailwind CSS** (CDN) replaces custom CSS; **HTMX** (CDN) added for async page fragments
- **pytest** infrastructure with PostgreSQL-backed integration tests (see [Testing](#testing))

### Features Added
1. **Game Night Recap Page** — `GET /game_night/<id>/recap`, public (no login required), only visible for finalized nights
2. **Play Count & Fatigue Tracking** — tracks how recently each game has been played; amber "Recently Played" badge on game cards
3. **Always Bridesmaid** — tracks games that are frequently nominated but rarely played
4. **Group Wishlist Voting** — any user can vote on games wishlisted by others; group view aggregates all want-counts
5. **Achievement Badges** — 26 badges awarded automatically when a game night is finalized (see [Achievement Badges](#achievement-badges))
6. **Live Score Tracker** — in-session score tracking during game nights

---

## Architecture

```
app/
  __init__.py       # create_app() application factory
  config.py         # Config class (reads env vars)
  models.py         # All SQLAlchemy models + view models
  extensions.py     # Shared Flask extension instances (db, login_manager, etc.)
  blueprints/       # HTTP route handlers, one file per feature area
  services/         # Business logic, called by blueprints
  templates/        # Jinja2 HTML templates
  static/           # Images, minimal CSS
  utils/            # Shared decorators and helpers
migrations/         # Alembic migration chain (never edit manually)
tests/              # pytest integration tests
docs/               # Internal documentation
app.py              # Entry point: calls create_app()
```

### Request Flow

```
HTTP request → Blueprint route → Service function → SQLAlchemy → PostgreSQL
                     ↓
              Jinja2 template (or JSON response for HTMX fragments)
```

Blueprints handle HTTP concerns (request parsing, auth checks, redirects, flash messages). Services contain all business logic and database writes. Blueprints should not query the database directly.

### Key Models (`app/models.py`)

| Model | Description |
|-------|-------------|
| `Person` | A user account |
| `GameNight` | A scheduled game night session |
| `Game` | A board game (linked to BGG) |
| `OwnedBy` | Person → Game ownership |
| `Wishlist` | Personal game wishlist entries |
| `WishlistVote` | Votes on others' wishlisted games |
| `Player` | Attendance record (person at a game night) |
| `GameNightGame` | A game played during a game night |
| `Result` | Win/loss result for a person on a game |
| `Poll` | Availability poll |
| `Badge` | A seeded achievement definition |
| `PersonBadge` | Awarded badge (person + badge + game night) |
| `TrackerSession` / `TrackerField` / `TrackerTeam` / `TrackerValue` | Live score tracker |

Several PostgreSQL **views** are also modeled as read-only SQLAlchemy classes (e.g., `GameNightRankings`, `GamesIndex`). These views exist in the production database but are managed separately — see [Database Views](#database-views).

---

## Local Development

### Prerequisites

- Docker and Docker Compose (`sudo` required on this machine)
- No local Python installation needed — everything runs in containers

### Start the App

```bash
sudo docker compose -f docker-compose.dev.yml up --build -d
```

The app runs at **http://localhost:5000**. The database runs on port 5432.

```bash
# View logs
sudo docker compose -f docker-compose.dev.yml logs -f app

# Stop everything
sudo docker compose -f docker-compose.dev.yml down
```

### Run Database Migrations

After pulling new code that includes migrations:

```bash
sudo docker compose -f docker-compose.dev.yml exec app flask db upgrade
```

The Docker entrypoint runs this automatically on startup, so usually you don't need to do this manually.

### Environment Variables

The dev compose file sets sensible defaults automatically. For a custom setup, copy `.env.example` to `.env` and edit it:

```bash
cp .env.example .env
```

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | — | PostgreSQL connection string |
| `SECRET_KEY` | Yes in prod | `dev-local-preview-key` | Session/token signing key — generate with `python -c "import secrets; print(secrets.token_hex(32))"` |
| `FLASK_DEBUG` | No | `0` | Set to `1` for auto-reload and detailed errors |
| `SESSION_TYPE` | No | `filesystem` | `filesystem` for local dev; `null` in tests |
| `APP_TIMEZONE` | No | `America/Chicago` | Timezone for game night scheduling (pytz name) |
| `MAIL_SERVER` | No | — | SMTP server for email reminders and password resets |
| `MAIL_PORT` | No | `587` | SMTP port |
| `MAIL_USERNAME` | No | — | SMTP login |
| `MAIL_PASSWORD` | No | — | SMTP password (use an App Password for Gmail) |
| `MAIL_DEFAULT_SENDER` | No | — | "From" address on outbound emails |
| `BGG_API_TOKEN` | No | — | BoardGameGeek API bearer token (optional, used by search) |

---

## Testing

**Tests run in CI only.** The dev docker-compose does not expose the database port to the host, so `pytest` cannot connect locally without extra setup.

Tests live in `tests/` and are split by layer:
- `tests/blueprints/` — route-level integration tests
- `tests/services/` — service-layer unit/integration tests

CI runs them with:

```bash
pytest --cov=app --cov-report=term-missing --cov-fail-under=60 -v
```

If you need to run tests locally, you'll need a locally accessible PostgreSQL database:

```bash
createdb gamenight_test
export TEST_DATABASE_URL=postgresql://user:password@localhost:5432/gamenight_test
pytest
```

**CI configuration:** `.github/workflows/ci.yml`

---

## Linting

These checks run in CI and **must pass** before a merge. Run them locally before pushing:

```bash
ruff check .          # lint
ruff format --check . # format check (use ruff format . to auto-fix)
mypy app/ tests/      # type checking
bandit -r app/ -ll -ii  # security scan
```

To auto-fix lint and format issues:

```bash
ruff check --fix . && ruff format .
```

> **Version note:** The project pins `ruff==0.4.4` in `requirements-dev.txt`. If your system has a different version of ruff installed, you may see different warnings. The CI version (0.4.4) is authoritative — install it in a virtualenv to be sure:
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install -r requirements.txt -r requirements-dev.txt
> ruff check . && ruff format --check .
> ```

---

## Database Migrations

All schema changes go through Alembic migrations. Never use `db.create_all()` or edit the schema directly.

### Applying Migrations

```bash
# Inside the running container
sudo docker compose -f docker-compose.dev.yml exec app flask db upgrade

# Or from a virtualenv with the app installed
flask db upgrade
```

### Creating a New Migration

```bash
# After editing app/models.py
sudo docker compose -f docker-compose.dev.yml exec app flask db migrate -m "describe your change"
# Review the generated file in migrations/versions/
sudo docker compose -f docker-compose.dev.yml exec app flask db upgrade
```

Always review the auto-generated migration before applying it — Alembic sometimes misses changes to views or custom types.

### Migration Chain

```
82a37a1f8996  initial_schema
  └─ a1b2c3d4e5f6  create_views
       └─ 83f9da8656a8  add_poll_tables
            └─ c5d6e7f8a9b0  add_wishlist_votes
                 └─ 8b9f3a3784a3  add_achievement_badges
                      └─ d1e2f3a4b5c6  add_tracker_tables
                           └─ e2f3a4b5c6d7  link_polls_to_game_nights
                                └─ f3a4b5c6d7e8  rename_game_ratings_table
                                     └─ g4h5i6j7k8l9  add_fk_indexes
                                          └─ h5i6j7k8l9m0  fix_view_date_timezone
                                               └─ i6j7k8l9m0n1  temp_pass_expiry_and_games_index
```

### Existing Production Database (Brownfield Setup)

If you have an existing database created before Flask-Migrate was introduced, run this **once** to mark the current state as up-to-date without re-running migrations:

```bash
flask db stamp head
```

Then future migrations will apply normally with `flask db upgrade`.

### Database Views

The app uses 9 PostgreSQL views for performance (e.g., `GameNightRankings`, `GamesIndex`). These are tracked in migration `a1b2c3d4e5f6_create_views.py`. If you're starting from sgammill's original database, run `flask db upgrade` from the beginning to create them, or manually verify the views exist.

---

## User Management

The app uses **invite-only signup**. A new user cannot register themselves — an admin must create their account first.

### Adding a New User

1. Log in as an admin
2. Go to **Admin → Add Person**
3. Enter the person's first and last name
4. The system creates a `Person` record with a temporary password
5. Send the person the app URL — they sign up using their name to claim the account

### Admin Access

The first user in the database is automatically an admin. Additional admins can be toggled from the Admin page. Admin-only routes are protected by `@admin_required` in `app/utils/decorators.py`.

---

## Feature Details

### Wishlist

**Personal wishlist** (`/wishlist/mine`) — games a user wants to play. Managed via add/remove actions.

**Group wishlist** (`/wishlist`) — aggregated view showing all wishlisted games with a "want count." Users can vote on games they don't personally own but would like to play. Voting is blocked if the game is already on the user's personal wishlist (it counts as a vote automatically).

### Achievement Badges

26 badges are automatically evaluated when a game night is **finalized** (marked as complete). The evaluation runs in `app/services/badge_services.py`.

| Badge | Trigger |
|-------|---------|
| First Blood | Win your first game |
| Hat Trick | Win 3 games in one night |
| Bench Warmer | Attend 3+ nights without a win |
| Jack of All Trades | Play 5+ different games |
| The Diplomat | Play in every game of a night |
| Opening Night | Host the first game night |
| Redemption Arc | Win after 2+ losses to the same person |
| The Rematch | Play the same game again after losing |
| Dark Horse | Win with the longest losing streak |
| Veteran | Attend 10 game nights |
| Century Club | Attend 100 game nights |
| Variety Pack | Play 25 unique games total |
| Night Owl | Attend 5+ game nights that go past midnight |
| Gracious Host | Host 5+ game nights |
| Collector | Own 10+ games |
| Early Bird | Be the first to RSVP to 3 game nights |
| Founding Member | Attend one of the first 3 game nights |
| Winning Streak | Win 3 games in a row (across nights) |
| The Closer | Win the last game of a night |
| Nemesis | Lose to the same person 3+ times |
| Kingslayer | Beat the person with the most wins |
| Upset Special | Win despite lowest win rate |
| Grudge Match | Beat your nemesis |
| Most Wins | Most wins in a single game night |
| Social Butterfly | Play with 5+ different people in one night |
| The Oracle | Correctly predict the game night winner |

Badges are displayed on the **user stats page** (`/user_stats`) and on each game night's **recap page** (`/game_night/<id>/recap`).

To retroactively evaluate badges on an existing database (e.g., after first deployment):

```bash
sudo docker compose -f docker-compose.dev.yml exec app flask shell
```

```python
from app.models import GameNight
from app.services.badge_services import evaluate_badges_for_night
from app import db

nights = GameNight.query.filter_by(final=True).all()
for night in nights:
    evaluate_badges_for_night(night.id)
db.session.commit()
print(f"Evaluated {len(nights)} nights")
```

### Game Night Recap

`GET /game_night/<id>/recap` — public, no login required. Only available for game nights with `final=True`. Shows results, attendance, games played, and badges earned that night.

### Live Score Tracker

Available during an active game night. Supports multiple teams, custom fields (score, wins, etc.), and real-time HTMX updates. Accessible from the game night view.

### BGG Integration

Game search uses the BoardGameGeek XML API v2. Set `BGG_API_TOKEN` in your environment if you have one; the search works without it but may be rate-limited.

---

## Production Deployment

The production deployment uses `docker-compose.yml` with Traefik for SSL termination. The image is published to GHCR on every push to `main`:

```
ghcr.io/gammill32/game_night_app:latest
ghcr.io/gammill32/game_night_app:<git-sha>
```

To deploy the latest image on your homelab:

```bash
sudo docker compose pull
sudo docker compose up -d
```

The entrypoint automatically runs `flask db upgrade` before starting gunicorn, so migrations apply on deploy without manual intervention.

### Generating a Production SECRET_KEY

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Set this as a real environment variable on the host — never put it in a committed file.

---

## CI/CD Pipeline

Every push to `main` and every PR runs:

1. **Lint** (`ruff check . && ruff format --check .`)
2. **Type check** (`mypy app/ tests/`)
3. **Security scan** (`bandit -r app/ -ll -ii`)
4. **Tests** (`pytest --cov=app --cov-fail-under=60`)
5. **Docker build** check
6. **Publish to GHCR** (main branch pushes only)

A failed lint or test blocks the merge. The 60% coverage gate is a minimum floor, not a target.

---

## Code Conventions

- Python 3.11, line length 100, ruff rules E/F/I/UP
- Snake_case for functions and variables; PascalCase for classes and models
- Blueprints handle HTTP only; all logic goes in services
- Templates use Tailwind CSS (CDN) and HTMX for async fragments
- No docstrings required; add comments only where logic is non-obvious
- Commits: no AI co-author lines
