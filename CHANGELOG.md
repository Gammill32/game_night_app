# Changelog

All notable changes to this project will be documented here.

## 2026-09-29 — Poker Night ports and full pass

Migrations `j7k8l9m0n1o2` through `s6t7u8v9w0x1`; the entrypoint applies them on deploy.

### Added
- Polls need a login, can be linked to a night and show on its page; availability answers show as RSVP badges
- "Find a date" polls (date range with weekdays, or hand-picked dates); picking a date creates the night with RSVPs carried over
- Home page: upcoming nights and open polls above the calendar
- Night photos (`MEDIA_DIR`, `MAX_UPLOAD_MB`), food (provided with extras / sign-up list / split cost), payment links on profiles
- Badge explanations linked to the night earned; head-to-head opponent picker on stats
- Library "Owned by" and wishlist "Wanted by" filters; one search for adding games and wishlist entries
- Score tracker teams mode; Share button on the public recap
- Emailed one-hour password reset links; reminders the day before and morning of (`APP_BASE_URL`)
- Night hosts: members with Can host start and run their own nights and polls; owner-only admin promotion
- Private night address, never emailed, deleted when the night is finalized or past

### Changed
- Removing a person with history deactivates them instead of deleting results
- Votes for games no longer nominated are removed
- Container runs as uid 1000; `ProxyFix` for Traefik headers
- Flask 3.1.3, Werkzeug 3.1.9, Flask-SQLAlchemy 3.1.1, SQLAlchemy 2.0.51 (pinned)
- gunicorn 26.2.0, requests 2.34.2, cachetools 7.2.0, APScheduler 3.11.3, Flask-Migrate 4.1.0, Flask-WTF 1.3.0, psycopg2-binary 2.9.13 and current pytz / python-dotenv; SQLAlchemy held at 2.0 (2.1 switches the default Postgres driver) and flask-session at 0.6 (0.8 would sign everyone out)

## [Unreleased] — Phase 1: UI Infrastructure (2026-03-26)

### Added
- Tailwind CSS CDN replacing custom CSS
- HTMX CDN (used in Phase 2 BGG integration)
- Icon-only sidebar navigation (desktop) + mobile bottom tab bar
- Flask-Migrate (Alembic) for database schema management
- pytest infrastructure with PostgreSQL-backed integration tests
- GitHub Actions CI pipeline (lint → typecheck → security → build → test → publish)
- `.env.example` for new developer onboarding with comprehensive variable documentation
- `.gitignore` for Python/Flask artifacts
- `.dockerignore` for cleaner Docker builds
- `requirements-dev.txt` for development dependencies
- `APP_TIMEZONE` configurable timezone setting (defaults to America/Chicago)
- Python 3.11 base image in Dockerfile

### Changed
- Dockerfile upgraded from Python 3.10 to 3.11 with optimized layer caching
- `entrypoint.sh` now runs `flask db upgrade` before starting gunicorn
- Removed unconditional `test_bp` blueprint registration
- Removed `db.create_all()` call (replaced by Flask-Migrate)
- Gunicorn reduced to `-w 1` (APScheduler is per-process)

### Removed
- `app/static/css/styles.css` bulk custom CSS (kept only minimal overrides)

## Upgrade Guide (for existing installations)

If you have an existing gamenight database created before Phase 1 (tables were
created by `db.create_all()`), run this once after deploying Phase 1:

```bash
# Mark your existing schema as current (do NOT run db upgrade on an existing DB)
flask db stamp head
```

Fresh installations: the Docker entrypoint runs `flask db upgrade` automatically.
No manual steps needed.
