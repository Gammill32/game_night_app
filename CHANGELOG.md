# Changelog

All notable changes to this project will be documented here.

## 2026-10-10 — Badge rules, locked nights, invites, and a UI pass

Migrations `t7u8v9w0x1y2` through `v9w0x1y2z3a4`; the entrypoint applies them on deploy. `u8c2u3n4i5q6` merges any duplicate players, results, votes, wishlist rows and nominations before adding unique constraints (its docstring lists exactly what it keeps); `v9w0x1y2z3a4` deletes result rows with neither a score nor a place.

**Before deploying:** run the read-only checks in the developer guide ("Before the first deploy of the October 2026 changes"). **After deploying:** run `flask badges recheck --dry-run` in the app container to see which existing awards the corrected rules would add or remove, then `flask badges recheck` to apply. It leaves Collector and Social Butterfly alone (they're judged on today's data, not a night's history).

### Deploy
- New `game_night_scheduler` container (same image, `command: ["scheduler"]`) runs the reminder job; the web container sets `ENABLE_SCHEDULER=false` and serves with 4 gthread threads instead of one sync worker. No new env vars; `docker compose up -d --build` starts both.
- Tailwind is built with the pinned standalone CLI (v3.4.17, no Node) instead of the Play CDN: the Dockerfile builds it, and the built `app/static/css/tailwind.css` is committed for `scripts/dev.sh`. After using a new class run `scripts/build_css.sh` and commit; CI fails on a stale file.

### Fixed
- Badges now match their descriptions: Gracious Host is judged after the year ends; Nemesis needs 5 losses in the same game; The Diplomat needs a shared first place in every game; Social Butterfly counts active people who have played; Founding Member goes by first night played; ties for most wins all count for Kingslayer/Most Wins; Dark Horse and The Rematch edge cases. Career badges only count finalized nights up to the one being judged, and one failing check no longer rolls back the rest.
- Night rankings count every place (5th and 6th no longer tie).
- A finalized night can't change: results, games, players, tracker and votes are refused server-side. Closed voting is enforced server-side too. Finalize and reopen are explicit actions, not a toggle.
- Only the night's host (or an admin) saves or discards tracker results, and saved scores come from the tracker.
- Log results only accepts this night's players and whole numbers in range; blank entries no longer save empty rows.
- Removing someone who's in a tracker, double-submits, bad ids/numbers and `?month=13` get a message instead of a 500.
- Deleting a night deletes its RSVP poll instead of leaving it visible to everyone; picking a date twice can't create two nights.
- Today's date follows `APP_TIMEZONE` everywhere (date polls, games, stats), not the container's UTC.
- Reminder job: one bad night no longer stops the rest; a late start still runs. Poll share sends over one SMTP connection and names anyone who wasn't emailed.
- Uploads are size-checked before decoding; files and rows stay in step when a save fails.
- Security: login `next` can't leave the site; one password rule (8+ characters); reset links no longer carry part of the password hash; changing your password signs out other devices; sign-in and reset requests are rate-limited (per email from an address, so guessing can't lock the owner out); old temporary passwords can't sign in.

### Changed
- Sign-up stays invite-only, but by signed invite link: admins (and hosts, for guests who've only played at their nights) copy a link on the Admin page or `/invites`. A link stops working if its maker could no longer make it. Knowing someone's name is no longer enough to claim their account.
- Closing voting leaves the RSVP poll open until the night is finalized.
- The public recap no longer shows the night's notes.
- Finalize lives at the bottom of "Games played" and only works once the night has happened and a game has results (the server refuses it otherwise). Reopening a night reopens its RSVP poll.
- Night, tracker, voting, food, photo and RSVP-poll services raise `ServiceError` (flashed or returned as JSON by one handler) instead of returning `(ok, message)`; the rest still return tuples and are listed in the developer guide's conventions, to convert when touched. Multi-step operations commit once; database queries moved out of the blueprints.
- Removed: four unused SQL views, the never-used temporary-password login path, and other dead code.

### Added
- UI: tracker as player cards with 44px buttons and instant taps; players can open a running tracker from the night page; nav shows where you are; dismissible flash messages; shared podium and badge chips on the night page and recap; badges page with a progress ring; better contrast and tap sizes; working home-screen icon.
- Small celebrations (all off with reduced motion): podium reveal on finalize, a "New badge!" dialog, ranking medals, poll answer stamp, "Tonight" card, wishlist heart, winner-row sweep.
- `flask badges recheck [--dry-run]`.

Prepared with AI assistance (Claude); every change was reviewed and tested.

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
