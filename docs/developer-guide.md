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
- **Tailwind CSS** replaces custom CSS (built with the pinned standalone CLI, `scripts/build_css.sh`; started on the CDN); **HTMX** (CDN) added for async page fragments
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
| `APP_BASE_URL` | No | `https://gamenight.sgammill.com` | Public URL used for links in emails sent by the scheduler (no request to take it from) |
| `MEDIA_DIR` | No | `/app/media` | Where night photos are stored; bind-mount a persistent volume here, writable by uid 1000 |
| `MAX_UPLOAD_MB` | No | `20` | Largest photo upload accepted |
| `ENABLE_SCHEDULER` | No | `true` | Set `false` to skip the reminder scheduler in this process. `docker-compose.yml` sets it `false` on the web container (the `game_night_scheduler` container runs the job); dev tooling and tests set it too |

---

## Testing

CI runs the tests on every push.

Tests live in `tests/` and are split by layer:
- `tests/blueprints/` — route-level integration tests
- `tests/services/` — service-layer unit/integration tests

Migrations run once per session. Each test then runs inside one transaction that's rolled back when it ends (the `_rollback_after_test` fixture in `tests/conftest.py`): `db.session.commit()` and `rollback()` become savepoint operations, so code under test behaves as usual but nothing a test writes reaches the next test, even if it fails before cleaning up. Server-side `now()` stays fixed for the whole test, and ids aren't reused (sequences don't roll back). A test that needs another connection or process to see its rows is marked `@pytest.mark.real_commits`; it commits for real and must clean up after itself (`tests/services/test_unique_races.py` does).

CI runs them with:

```bash
pytest --cov=app --cov-report=term-missing --cov-fail-under=60 -v
```

To run them locally (boxer has no `python3-venv`), start a throwaway Postgres and use `scripts/dev.sh`, which runs any command in a tooling container built from `scripts/Dockerfile.dev`:

```bash
docker run -d --name game_night_testdb --rm -e POSTGRES_USER=gamenight \
  -e POSTGRES_PASSWORD=gamenight -e POSTGRES_DB=gamenight_dev -p 127.0.0.1:55433:5432 postgres:16
docker exec game_night_testdb psql -U gamenight -d gamenight_dev -c "CREATE DATABASE gamenight_test"

scripts/dev.sh pytest
scripts/dev.sh sh -c "ruff check . && ruff format --check . && mypy app/ tests/"
scripts/dev.sh flask db migrate -m "describe change"
```

Delete the `game_night_dev` image after changing `requirements*.txt` so it rebuilds.

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

> **Version note:** The project pins `ruff==0.4.4` in `requirements-dev.txt`. Your system ruff may be a different (newer) version and will report "All checks passed" locally while CI still fails. **Always use the pinned version before pushing:**
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install -r requirements.txt -r requirements-dev.txt
> ruff check --fix . && ruff format .
> ```
> Or with a one-off temp venv:
> ```bash
> python3 -m venv /tmp/ruff-venv && /tmp/ruff-venv/bin/pip install ruff==0.4.4 -q
> /tmp/ruff-venv/bin/ruff check --fix . && /tmp/ruff-venv/bin/ruff format .
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
                                                    └─ j7k8l9m0n1o2  add_poll_private_invitees
                                                         └─ k8l9m0n1o2p3  poll_availability_flag
                                                              └─ l9m0n1o2p3q4  payment_handles
                                                                   └─ m0n1o2p3q4r5  game_night_photos
                                                                        └─ n1o2p3q4r5s6  food
                                                                             └─ o2p3q4r5s6t7  people_active
                                                                                  └─ p3q4r5s6t7u8  date_polls
                                                                                       └─ q4r5s6t7u8v9  remove_votes_for_unnominated_games
                                                                                            └─ r5s6t7u8v9w0  night_hosts
                                                                                                 └─ s6t7u8v9w0x1  night_address
                                                                                                      └─ t7u8v9w0x1y2  badge_rules_match_checks
                                                                                                           └─ u8c1a2s3c4d5  tracker_player_fk_cascade
                                                                                                                └─ u8c2u3n4i5q6  one_row_per_thing
                                                                                                                     └─ u8c3v4i5e6w7  drop_unused_night_list_views
                                                                                                                          └─ u8c4r5a6n7k8  rankings_count_every_place
                                                                                                                               └─ u8v9w0auth01  session_tokens_and_auth_throttle
                                                                                                                                    └─ v9w0x1y2z3a4  drop_blank_results
```

### Existing Production Database (Brownfield Setup)

If you have an existing database created before Flask-Migrate was introduced, run this **once** to mark the current state as up-to-date without re-running migrations:

```bash
flask db stamp head
```

Then future migrations will apply normally with `flask db upgrade`.

### Database Views

The app uses 5 PostgreSQL views for performance (e.g., `GameNightRankings`, `GamesIndex`). These are tracked in migration `a1b2c3d4e5f6_create_views.py`. If you're starting from sgammill's original database, run `flask db upgrade` from the beginning to create them, or manually verify the views exist.

---

## User Management

People are added by name first (so they can be put on nights before they have an account), then claim that person with a personal **invite link**. Sign-up is invite-only: `/signup` without a link only explains how to get one, and typing a name never attaches to someone already on the site.

### Adding a New User

1. Log in as an admin
2. Go to **Admin → Add Person** and enter their first and last name
3. On the Admin page, their row says *Not signed up yet* with **Copy invite link**
4. Send them the link; it opens sign-up prefilled as that person and they add an email and password

Invite links are signed with `SECRET_KEY` (`itsdangerous`, salt `person-invite`), last 14 days, and stop working once the person has signed up or has been deactivated (the link includes a digest of `people.session_token`, which deactivation changes). A link also names who made it and stops working if they could no longer make it: they lost admin or hosting, or an admin has since given the person rights. Whatever rights an admin gave the person (admin, Can host) carry over when they claim it.

Hosts can also add someone by name from the start/edit night form (**Not on the site? Add them**, `POST /people/quick_add`). Hosts get invite links from **Profile → Invite people** (`/invites`) for their own guests: unclaimed people who have only ever played on nights that host ran, and whom no admin has given rights to.

### Sign-in security

- One password rule everywhere (`auth_services.password_problem`): 8+ characters, at most 72 bytes (bcrypt's limit).
- `Person.get_id()` returns `"<id>:<session_token>"` (Flask-Login's alternative token). Changing or resetting a password, or deactivating someone, sets a new token, which logs out their other sessions; the session that changed the password is logged back in.
- Failed sign-ins (per email *from* an address, and per address) and reset requests are counted in `auth_throttle`, so the limits hold across workers and threads. Keying the email limit by address too means guessing at an account from one place can't lock its owner out elsewhere. Tests turn this off with `AUTH_THROTTLE = False`.
- The client address comes from `ProxyFix` (one trusted proxy: Traefik). If the domain is ever put behind Cloudflare or another proxy, every visitor would share that proxy's address and the per-address limit; trust its client-IP header only from its published ranges.
- Accounts still flagged `temp_pass` (from the original app's mailed temporary passwords) can't sign in with that password; they use Forgot password.

**Removing** someone who has played deactivates them (`people.active = false`) so their results and stats stay; people with no history are deleted.

### Roles

| Role | Can do | Set by |
|------|--------|--------|
| Owner | Everything, including promote/demote admins | Database |
| Admin | Manage every night, poll and person; switch **Can host** on or off | Owner, from the Admin page |
| Host (`people.can_host`) | Start nights and polls; run the nights they host (edit, results, finalize, photos, food, polls) | An admin, from the Admin page |
| Member | Play, nominate, vote, RSVP, answer polls | — |

Each night has a `host_id`. `GameNight.managed_by(user)` is true for admins, the owner and that night's host. Decorators live in `app/utils/decorators.py`: `@admin_required`, `@owner_required`, `@host_required` (can start nights), `@night_manager_required` (manages this night) and `@game_night_access_required` (a player on the night, or someone who manages it). Admins can hand a night to any member from its edit page. Reminder emails for a night are signed by its host.

### Night address

A night can have an optional `address`. Only people who can open the night see it; it's never included in emails or the public recap. It's set to `NULL` when the night is finalized, and the daily reminder job clears any left on nights more than a day past (`clear_past_addresses`).

---

## Feature Details

### Wishlist

**Personal wishlist** (`/wishlist/mine`) — games a user wants to play. Managed via add/remove actions.

**Group wishlist** (`/wishlist`) — aggregated view showing all wishlisted games with a "want count." Users can vote on games they don't personally own but would like to play. Voting is blocked if the game is already on the user's personal wishlist (it counts as a vote automatically).

### Achievement Badges

26 badges are automatically evaluated when a game night is **finalized** (marked as complete). The evaluation runs in `app/services/badge_services.py`.

After changing a badge rule, run `flask badges recheck --dry-run` to see which awards would be added or removed when every finalized night is re-judged in date order, then `flask badges recheck` to save those changes in one transaction. Awards that still qualify are left as they are. Collector and Social Butterfly are skipped: they're judged on today's data (games owned now, who's active now), not on the night's history, so re-judging old nights would date or remove them wrongly; finalizing a night still awards them.

| Badge | Rule |
|-------|------|
| First Blood | First time winning any game at a game night |
| Hat Trick | Win 3 games in a single game night session |
| Veteran | Attend 25 game nights total |
| Kingslayer | Beat the person with the most all-time wins in a head-to-head game |
| Collector | Own 10+ games in the group library |
| Variety Pack | Play 10 different unique games across any number of nights |
| Nemesis | One specific person has beaten you 5+ times in the same game |
| Redemption Arc | Win a game you have previously lost 3+ times |
| Night Owl | Attend 5 game nights in a single calendar month |
| Gracious Host | Attend every game night in a calendar year (awarded once the year is over) |
| Jack of All Trades | Finish in the top half in every game played at a single game night |
| Upset Special | Beat a player whose win rate against you was 80% or more (min 5 games) |
| Bench Warmer | Attend a game night but finish last in every game you played |
| Grudge Match | Play the same game against the same opponent 10+ times |
| The Closer | Win the last game at 5 consecutive game nights you attended |
| Opening Night | Play in the very first game night ever recorded |
| Winning Streak | Win at least one game at 3 consecutive game nights you attended |
| The Diplomat | Play a game night where every game ends in a tie or shared first place |
| Host with the Most | Host 10 game nights |
| The Rematch | Play the same game at back-to-back consecutive game nights you attended |
| Century Club | Play in 100 total game night games across all nights |
| Dark Horse | Within one game night: finish last in your first 3 games then win the last |
| Social Butterfly | Play at least one game with everyone else who has played |
| The Oracle | Nominate a game, have it played, and win it — 5 times |
| Founding Member | Be one of the first 5 people to ever play a game night |
| Most Wins | Once hold the record for most all-time wins across the group |

Badges are displayed on the **user stats page** (`/user_stats`) and on each game night's **recap page** (`/game_night/<id>/recap`).

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

### Before the first deploy of the October 2026 changes

Run these against production first (read-only):

```sql
-- the main things migration u8c2 merges or deletes (its docstring lists every step and which row it keeps):
-- people on a night twice
SELECT game_night_id, people_id, count(*) FROM players GROUP BY 1, 2 HAVING count(*) > 1;
-- more than one result for a player in one game
SELECT game_night_game_id, player_id, count(*) FROM results GROUP BY 1, 2 HAVING count(*) > 1;
-- the same vote twice
SELECT player_id, game_id, count(*) FROM game_votes GROUP BY 1, 2 HAVING count(*) > 1;
-- a game nominated twice on a night (the later nominations are dropped, which can change The Oracle)
SELECT game_night_id, game_id, count(*) FROM game_nominations GROUP BY 1, 2 HAVING count(*) > 1;
-- votes for a game that isn't nominated that night (deleted outright)
SELECT gv.id FROM game_votes gv
 WHERE NOT EXISTS (SELECT 1 FROM game_nominations n
                    WHERE n.game_night_id = gv.game_night_id AND n.game_id = gv.game_id);
-- the same wishlist entry twice
SELECT person_id, game_id, count(*) FROM wishlist GROUP BY 1, 2 HAVING count(*) > 1;

-- result rows with neither score nor place: migration v9w0 deletes them
SELECT count(*) FROM results WHERE score IS NULL AND position IS NULL;

-- anything built on the four views migration u8c3 drops (it fails rather than cascade)
SELECT DISTINCT dependent.relname FROM pg_depend d
  JOIN pg_rewrite r ON r.oid = d.objid
  JOIN pg_class dependent ON dependent.oid = r.ev_class
  JOIN pg_class source ON source.oid = d.refobjid
 WHERE source.relname IN ('user_recent_future_game_nights', 'admin_recent_future_game_nights',
                          'user_game_nights_list', 'admin_game_nights_list')
   AND dependent.relname NOT IN ('user_recent_future_game_nights', 'admin_recent_future_game_nights',
                                 'user_game_nights_list', 'admin_game_nights_list');

-- old temporary passwords still set (they can no longer sign in; those people use Forgot password?)
SELECT count(*) FROM people WHERE temp_pass;
```

Take a backup first (`pg_dump`): the duplicate and blank-row deletions can't be undone by a downgrade.

and `\d players`, `\d wishlist`, `\d ownedby`, `\d game_nominations` in psql: if the brownfield database has its own unique indexes on those tables under other names, drop them in a migration so double-submits are recognised by the constraint names in `app/services/db_utils.py`. After deploying all four parts (not before: the blank-row cleanup only arrives in the last one, and a recheck before it would count blank rows as games played), run `flask badges recheck --dry-run`, read the list, then `flask badges recheck`.

### Containers: web and scheduler

`docker-compose.yml` runs two containers from the same image:

| Container | Command | Does |
|-----------|---------|------|
| `game_night_app` | (default) | Waits for the database, runs `flask db upgrade`, then gunicorn: **1 worker process, 4 threads** (`-k gthread --threads 4`). `ENABLE_SCHEDULER=false`. |
| `game_night_scheduler` | `scheduler` | Waits for the database, then `python -m app.scheduler` (`app/scheduler.py`): the daily reminder job at 8:45 `APP_TIMEZONE`, nothing else. No migrations, no port, no media volume. |

`sudo docker compose up -d --build` builds and starts both; there's nothing else to do. The scheduler needs the same `DATABASE_URL`, `SECRET_KEY`, `MAIL_*`, `APP_BASE_URL` (and `APP_TIMEZONE` if you set it) as the app, from the same place. It sits on `web_network` as well as `game_night_internal` only because `game_night_internal` has no route out to the SMTP server; its `traefik.enable=false` label keeps Traefik from routing to it. Its logs: `sudo docker logs game_night_scheduler` (one "Scheduler running: daily_game_night_reminder, next run ..." line at start).

Why: the web used to be one *sync* gunicorn worker, so one slow request (a photo upload, a batch of emails) held up every other visitor, and it couldn't have more because the scheduler ran inside it and would have been duplicated. Now the web has threads and the scheduler has its own process.

Things to know before changing this:

- **Keep `ENABLE_SCHEDULER=false` on the web if you raise `-w` above 1**, or every worker sends its own copy of each reminder. (With `-w 1`, even `true` only runs it once, so an older compose file without the scheduler service still works.)
- In-process state is fine with threads: the BGG search cache is a `TTLCache` behind a lock, Flask-SQLAlchemy sessions are per request, and there are no other module-level caches. With more than one *worker process*, the BGG cache would be per process (harmless) and filesystem sessions still work because they're files in the container. With more than one *container* behind Traefik, sessions would need a shared store (`SESSION_TYPE=redis`).
- Reminder jobs live in memory: if the scheduler container is down (or restarting during a deploy) at 8:45, that day's reminders don't go out. A wake-up up to an hour late still runs them (`misfire_grace_time`).

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
- Blueprints handle HTTP only (request parsing, auth decorators, flash/render/redirect); queries and writes go in services
- **Service errors:** a service that refuses an operation raises `ServiceError(message, status=400)` (`app/services/errors.py`); `FoodError`, `MediaError` and `NightRuleError` subclass it. On success it returns the message to show (or the object it made). Routes don't catch it: the handler in `app/utils/errors.py` rolls back, then flashes the message and redirects back (form posts) or returns `{"error": message}` (JSON) / the bare message (HTMX fragment) with the status. A blueprint whose pages should land somewhere specific registers its own `@bp.errorhandler(ServiceError)` that calls `service_error_response(e, redirect_to=...)` (food → `#food`, photos → `#photos`, voting and night routes → the night page). Routes that re-render a form on error (start/edit night) catch `ServiceError` themselves; so do routes that should land somewhere other than their blueprint's default (tracker launch → setup, end game → live tracker, save results → confirm page, delete night → home, RSVP poll → `#polls`), and they hand it to `service_error_response(e, redirect_to=...)` so the rollback and the JSON/HTMX answers stay in one place.
  - Converted: `food_services`, `photo_services`, `tracker_services`, `voting_services`, `game_night_services`, `poll_services.create_availability_poll`.
  - Still `(ok, message[, obj])` tuples: `admin_services`, `auth_services` (login/signup/reset carry status like "too many attempts"), `games_services`, `payment_services`, `poll_services.submit_response` and `date_poll_services.submit_answers` (they re-render the poll widget with the message either way), `date_poll_services.pick_date`, and `game_night_services.finalize`/`unfinalize` (an "already finalized" outcome, flashed as info, not an error). Convert these the same way when touching them.
- **One commit per operation:** an operation that writes several things commits once at the end; helpers it calls only `flush()` (e.g. `poll_services.add_poll` / `add_availability_poll` vs `create_poll` / `create_availability_poll`). Deliberate exceptions: `finalize` commits before awarding badges (a badge failure mustn't undo finalizing), `get_or_create_game` commits the library row before ownership/wishlist is added (the game belongs in the library either way), and the sign-in throttle (`auth_services._record`) commits its attempt rows itself (a refused sign-in must still count).
- **Unique constraints and double-submits:** don't look a row up and then insert it. Use `app/services/db_utils.py`: `upsert()` (`INSERT ... ON CONFLICT DO UPDATE`, results and votes) or `add_unless_duplicate()` (savepoint; a duplicate means "already done": players, wishlist, ownership, nominations).
- Templates use Tailwind CSS (built: run `scripts/build_css.sh` after using a new class and commit `app/static/css/tailwind.css`; CI fails on a stale file) and HTMX for async fragments
- No docstrings required; add comments only where logic is non-obvious
- Commits: no AI co-author lines
