# Live Game Night Tracker — Design Spec

## Goal

An optional, per-game tracker that lets the host track scores and game state live during play. When the game ends, results flow directly into the existing game night finalization system. Manual result entry remains available if the tracker isn't used.

## Architecture

Server-side state stored in PostgreSQL. Every host action (increment counter, toggle checkbox, type a note) fires a small HTMX POST; the server updates the value and returns the refreshed HTML fragment. No client-side state — page refreshes are safe. One-screen experience: a single device (typically a shared laptop or TV) runs the tracker. Other players are not expected to interact from their own devices.

**Tech stack additions:** 4 new DB tables, 1 new blueprint, 1 new service module, 3 new templates.

---

## Data Model

### `TrackerSession`
One per game being tracked.

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| game_night_game_id | Integer FK → GameNightGame | unique — one session per game |
| mode | String | `"individual"` or `"teams"` |
| status | String | `"active"` or `"completed"` |
| created_at | DateTime | server default |

### `TrackerField`
The configured tracking columns for a session. Ordered by `sort_order`.

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| tracker_session_id | Integer FK → TrackerSession | |
| type | String | `counter`, `checkbox`, `player_notes`, `global_counter`, `global_notes` |
| label | String | Host-defined name (e.g. "Victory Points", "Life", "Has Crown") |
| starting_value | Integer | For counter types only; default 0 |
| is_score_field | Boolean | Exactly one counter per session is the score field; used for auto-ranking |
| sort_order | Integer | Display order |

### `TrackerTeam`
Only exists when `mode = "teams"`.

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| tracker_session_id | Integer FK → TrackerSession | |
| name | String | e.g. "Team A", "Red Team" |

Association between `TrackerTeam` and `Player` is a many-to-many join table `tracker_team_players (team_id, player_id)`.

### `TrackerValue`
Live state. One row per (field, entity) pair. Entities are players (individual/team-member fields) or teams (team-level fields). Global fields have `player_id = NULL` and `team_id = NULL`.

| Column | Type | Notes |
|---|---|---|
| id | Integer PK | |
| tracker_field_id | Integer FK → TrackerField | |
| player_id | Integer FK → Player, nullable | null for global and team-level fields |
| team_id | Integer FK → TrackerTeam, nullable | null for individual and global fields |
| value | Text | Stores integer (as string) for counters, `"true"`/`"false"` for checkboxes, free text for notes |

Unique constraint: `(tracker_field_id, player_id, team_id)` with `NULLS NOT DISTINCT` (PostgreSQL 15+) so that global fields (both NULLs) are also deduplicated.

---

## Field Types

| Type | Per-entity | UI | Notes |
|---|---|---|---|
| `counter` | Per player (or per team) | Number + / − buttons | Can be the score field |
| `checkbox` | Per player (or per team) | Toggle checkbox | |
| `player_notes` | Per player (or per team) | Text input | |
| `global_counter` | Single shared value | Number + / − buttons | Cannot be the score field |
| `global_notes` | Single shared value | Text input | |

---

## Routes

All tracker routes require `@login_required`. Write routes (`POST`) additionally require the user to be a game night participant or admin.

| Method | Path | Description |
|---|---|---|
| GET | `/game_night/<gn_id>/tracker/new` | Setup page — configure fields and teams |
| POST | `/game_night/<gn_id>/tracker` | Create tracker session, redirect to live tracker |
| GET | `/tracker/<session_id>` | Live tracker page |
| POST | `/tracker/<session_id>/value` | Update a single TrackerValue (HTMX) |
| GET | `/tracker/<session_id>/end` | End-game confirmation — auto-ranked results |
| POST | `/tracker/<session_id>/save` | Save results → creates/replaces Result records, marks session completed |
| POST | `/tracker/<session_id>/discard` | Delete session and its values, redirect back to game night |

---

## Setup Flow

1. Host clicks **"Track"** next to a game on the game night page (only visible when night is not finalized).
2. If a `TrackerSession` already exists for this game with `status = "active"`, button reads **"Resume Tracker"** and links directly to the live tracker — no setup page.
3. Setup page collects:
   - **Mode:** Individual or Teams. If Teams, host names each team and assigns players.
   - **Fields:** Host adds fields one at a time — picks type, enters label, sets starting value for counters. At least one counter must be designated as the score field before the form can be submitted. Fields can be reordered.
4. Submitting setup creates the `TrackerSession`, `TrackerField` rows, `TrackerTeam`/join rows (if teams), and seeds `TrackerValue` rows for every (field, entity) pair at the field's starting value.
5. Redirect to the live tracker.

---

## Live Tracker Page

**Layout:**
- **Global bar** (top): Global counter(s) and global notes field displayed horizontally across the full width.
- **Player/team grid** (main): Rows are players (individual mode) or teams (teams mode). Columns are per-entity fields in `sort_order`. Score field column is visually highlighted (★).
- **Footer**: Session metadata (player count, mode, score field name) + **"End Game →"** button.

**HTMX updates:**
- Counter `+` / `−` buttons POST to `/tracker/<session_id>/value` with `field_id`, `entity_id`, `entity_type` (`player`/`team`/`global`), and `delta` (+1 or -1).
- Checkbox toggle POSTs the new boolean value.
- Notes fields POST on `hx-trigger="change"` (on blur).
- Each POST returns only the updated cell fragment (`hx-swap="outerHTML"`), keeping the rest of the page stable.

---

## End-Game Confirmation

1. Host clicks "End Game →".
2. Server reads all `TrackerValue` rows for the score field, sorts entities descending by value, assigns positions 1, 2, 3…
3. Ties share a position (e.g., two players at 47 VP both get position 2; next player gets position 4).
4. Confirmation page shows a table: position (editable dropdown), player/team name, score field value, other counter values for reference.
5. In team mode, all members of a team inherit the team's position.
6. Host adjusts positions if needed, hits **"Save Results →"**.
7. `POST /tracker/<session_id>/save` creates or replaces `Result` rows (`player_id`, `game_night_game_id`, `position`, `score`) using the score field value as the score. Session `status` set to `"completed"`.
8. If `Result` rows already exist for this `GameNightGame`, a warning is shown on step 4 before save.
9. Redirect back to the game night page.

Only **position** and **score** carry over to the `Result` record. Other tracked fields (non-score counters, checkboxes, notes) are stored in `TrackerValue` for reference but do not affect the game night record, badge evaluation, or statistics.

---

## Integration with Existing System

- **Game night page:** Adds a "Track" / "Resume Tracker" button per game. Existing manual result entry is unchanged.
- **Finalization:** Tracker writes standard `Result` records — badge evaluation and recap are unaffected.
- **No migration of existing data:** Tracker is opt-in per game. Games without tracker sessions continue to use manual entry.

---

## Not In Scope

- Multi-device simultaneous editing (multiple people updating the tracker from their own phones)
- Reusable tracker templates saved per game
- Tracker history, replays, or undo
- Tracker access for non-authenticated users

---

## New Files

| File | Purpose |
|---|---|
| `app/models.py` | Add `TrackerSession`, `TrackerField`, `TrackerTeam`, `TrackerValue` models + join table |
| `migrations/versions/<rev>_add_tracker_tables.py` | Alembic migration |
| `app/blueprints/tracker.py` | All tracker routes |
| `app/services/tracker_services.py` | Business logic: create session, update value, compute rankings, save results |
| `app/templates/tracker_setup.html` | Setup page |
| `app/templates/tracker_live.html` | Live tracker page |
| `app/templates/tracker_confirm.html` | End-game confirmation |
| `app/templates/view_game_night.html` | Add Track/Resume Tracker buttons per game |
| `tests/blueprints/test_tracker.py` | Blueprint integration tests |
| `tests/services/test_tracker_services.py` | Service unit tests |

---

## Testing

**Service tests** (`test_tracker_services.py`):
- Creating a session seeds correct `TrackerValue` rows at starting values
- Updating a counter value increments/decrements correctly (counters have no floor — they can go negative, e.g. life points in Magic)
- Auto-ranking sorts descending by score field value
- Ties assign shared position with correct gap (two 2nds → next is 4th)
- `save_results` creates `Result` rows with correct `position` and `score`
- `save_results` replaces existing `Result` rows for the same `GameNightGame`
- Team mode: all team members get the team's position

**Blueprint tests** (`test_tracker.py`):
- Setup POST creates session and redirects to live tracker
- Value POST updates the correct `TrackerValue` row
- End-game GET returns auto-ranked results
- Save POST creates `Result` records and marks session completed
- Unauthenticated requests are redirected to login
