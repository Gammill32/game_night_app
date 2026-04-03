# Changelog

All notable changes to this project will be documented here.

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
