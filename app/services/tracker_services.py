from app.extensions import db
from app.models import (
    Player,
    TrackerField,
    TrackerSession,
    TrackerTeam,
    TrackerValue,
    tracker_team_players,
)
from app.services import night_policy
from app.services.db_utils import add_unless_duplicate
from app.services.errors import ServiceError
from app.services.game_night_services import upsert_result

GLOBAL_FIELD_TYPES = {"global_counter", "global_notes"}
PER_PLAYER_FIELD_TYPES = {"counter", "checkbox", "player_notes"}
VALID_FIELD_TYPES = GLOBAL_FIELD_TYPES | PER_PLAYER_FIELD_TYPES

_DELTA_MAX = 100
_NOTES_MAX_LEN = 500


DEFAULT_SCORE_LABEL = "Score"


def can_track(game_night, user):
    """The night's players and whoever manages it can set up and score trackers."""
    return game_night.managed_by(user) or (
        Player.query.filter_by(game_night_id=game_night.id, people_id=user.id).first() is not None
    )


def find_session(game_night_game_id, status=None, *, session_id=None):
    """The game's tracker session with this status (or this id), or None."""
    query = TrackerSession.query.filter_by(game_night_game_id=game_night_game_id)
    if status is not None:
        query = query.filter_by(status=status)
    if session_id is not None:
        query = query.filter_by(id=session_id)
    return query.first()


def setup_context(session, game_night):
    """Players (by first name), who's playing (everyone but RSVP "Can't Make
    It") and the session's fields in order, for the setup page."""
    from app.services.poll_services import rsvps_for_night

    players = sorted(
        Player.query.filter_by(game_night_id=game_night.id).all(),
        key=lambda p: p.person.first_name.lower(),
    )
    rsvps = rsvps_for_night(game_night)
    fields = (
        TrackerField.query.filter_by(tracker_session_id=session.id)
        .order_by(TrackerField.sort_order)
        .all()
    )
    return {
        "players": players,
        "playing": {p.id for p in players if rsvps.get(p.people_id) != "Can't Make It"},
        "fields": fields,
    }


def live_context(session):
    """Everything the live tracker page shows, with the values in one query."""
    all_values = TrackerValue.query.filter_by(tracker_session_id=session.id).all()
    # Only the players this game was started with (not everyone at the night).
    seeded = {v.player_id for v in all_values if v.player_id is not None}
    players = (
        sorted(
            Player.query.filter(Player.id.in_(seeded)).all(),
            key=lambda p: p.person.first_name.lower(),
        )
        if session.mode == "individual"
        else []
    )
    return {
        # {(field_id, player_id, team_id): TrackerValue}
        "value_map": {(v.tracker_field_id, v.player_id, v.team_id): v for v in all_values},
        "players": players,
        "teams": session.teams if session.mode == "teams" else [],
        "global_fields": [f for f in session.fields if f.type in GLOBAL_FIELD_TYPES],
        "player_fields": [f for f in session.fields if f.type not in GLOBAL_FIELD_TYPES],
    }


def open_sessions_by_game(game_night_game_ids):
    """{game_night_game_id: session} for trackers being set up or played."""
    if not game_night_game_ids:
        return {}
    return {
        ts.game_night_game_id: ts
        for ts in TrackerSession.query.filter(
            TrackerSession.game_night_game_id.in_(game_night_game_ids),
            TrackerSession.status.in_(["configuring", "active"]),
        )
    }


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
    if not add_unless_duplicate(session, "tracker_sessions_game_night_game_id_key"):
        # another tab started this game's tracker first: use that one
        existing = TrackerSession.query.filter_by(game_night_game_id=game_night_game_id).first()
        if existing is None:  # ...and it was discarded again in between
            raise ServiceError("Someone else just changed this tracker. Try again.")
        return existing
    # Most games just need a score, so start with one; people can add more.
    db.session.add(
        TrackerField(
            tracker_session_id=session.id,
            type="counter",
            label=DEFAULT_SCORE_LABEL,
            starting_value=0,
            is_score_field=True,
            sort_order=0,
        )
    )
    db.session.commit()
    return session


def discard_session(session_id):
    """Delete a tracker session and all its children (cascade handles FK children)."""
    session = db.session.get(TrackerSession, session_id)
    if session:
        night_policy.require_editable(session.game_night_game.game_night)
        db.session.delete(session)
        db.session.commit()


def add_field(session_id, *, type, label, starting_value=0, is_score_field=False):
    """Add a TrackerField to a configuring session. Does not seed values yet."""
    session = db.session.get(TrackerSession, session_id)
    if session is None or session.status != "configuring":
        raise ServiceError("This tracker has already started, so fields can't be added.")
    night_policy.require_editable(session.game_night_game.game_night)
    if type not in VALID_FIELD_TYPES:
        raise ServiceError("Pick a field type from the list.")
    label = label.strip() if label else ""
    if not label:
        raise ServiceError("Give the field a name.")
    if is_score_field and type != "counter":
        raise ServiceError("Only a per-player counter can be the score.")
    replaced = False
    if is_score_field:
        # One score field per session: the new one replaces the starting
        # "Score" field if it's untouched, or else takes over the score role.
        current = TrackerField.query.filter_by(
            tracker_session_id=session_id, is_score_field=True
        ).first()
        if current is not None:
            if current.label == DEFAULT_SCORE_LABEL and current.starting_value == 0:
                db.session.delete(current)
            else:
                current.is_score_field = False
            db.session.flush()
            replaced = True
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
    field.replaced_score_field = replaced  # tells the page to redraw the list
    return field


def launch_session(session_id, *, mode, teams_data, player_ids, field_order=None):
    """
    Activate a configuring session. Seeds all TrackerValue rows.

    teams_data: list of {"name": str, "player_ids": [int]} — only used when mode="teams"
    player_ids: list of Player.id — all players for the game night (individual mode)
    field_order: list of TrackerField.id in desired sort order (optional)
    """
    session = db.get_or_404(TrackerSession, session_id)
    if session.status != "configuring":
        raise ServiceError("This tracker has already started.")
    night_policy.require_editable(session.game_night_game.game_night)

    # Require at least one score field before launch
    score_field = TrackerField.query.filter_by(
        tracker_session_id=session_id, is_score_field=True
    ).first()
    if score_field is None:
        raise ServiceError("Mark one field as the score before starting.")

    # Apply drag-to-reorder sort_order if provided
    if field_order:
        for i, fid in enumerate(field_order):
            TrackerField.query.filter_by(id=fid, tracker_session_id=session_id).update(
                {"sort_order": i}
            )

    # Validate player IDs belong to this game night
    gn_id = session.game_night_game.game_night_id
    valid_player_ids = {p.id for p in Player.query.filter_by(game_night_id=gn_id).all()}

    session.mode = mode
    session.status = "active"

    # Build teams if needed
    entity_map = []  # list of ("player"|"team", id) pairs
    if mode == "teams":
        for td in teams_data:
            if not td.get("name", "").strip():
                continue
            team = TrackerTeam(tracker_session_id=session_id, name=td["name"])
            db.session.add(team)
            db.session.flush()
            for pid in td["player_ids"]:
                if pid in valid_player_ids:
                    db.session.execute(
                        tracker_team_players.insert().values(team_id=team.id, player_id=pid)
                    )
            entity_map.append(("team", team.id))
    else:
        entity_map = [("player", pid) for pid in player_ids if pid in valid_player_ids]

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


def update_value(session_id, field_id, *, entity_type, entity_id=None, delta=None, value=None):
    """
    Update a single TrackerValue.

    entity_type: "player", "team", or "global"
    entity_id: Player.id or TrackerTeam.id (ignored for global)
    delta: integer increment/decrement for counter fields (clamped to ±100)
    value: new string value for checkbox/notes fields
    """
    session = db.session.get(TrackerSession, session_id)
    if session is None or session.status != "active":
        raise ServiceError("This tracker isn't running anymore.")
    night_policy.require_editable(session.game_night_game.game_night)

    # Validate field belongs to this session
    field = TrackerField.query.filter_by(id=field_id, tracker_session_id=session_id).first()
    if field is None:
        raise ServiceError("That field isn't in this tracker.")

    player_id = entity_id if entity_type == "player" else None
    team_id = entity_id if entity_type == "team" else None

    tv = (
        TrackerValue.query.filter_by(
            tracker_session_id=session_id,
            tracker_field_id=field_id,
            player_id=player_id,
            team_id=team_id,
        )
        .with_for_update()
        .first()
    )
    if tv is None:
        raise ServiceError("That player or team isn't in this tracker.")

    if delta is not None:
        # Clamp delta to prevent abuse
        delta = max(-_DELTA_MAX, min(_DELTA_MAX, delta))
        current = int(tv.value)
        tv.value = str(current + delta)
    elif value is not None:
        # Validate type
        if field.type in ("counter", "global_counter"):
            try:
                int(value)
            except ValueError:
                raise ServiceError(f"{field.label} needs a whole number.")
        elif field.type == "checkbox":
            if value not in ("true", "false"):
                raise ServiceError(f"{field.label} is a checkbox: on or off.")
        elif field.type in ("player_notes", "global_notes"):
            if len(value) > _NOTES_MAX_LEN:
                raise ServiceError(f"Notes can be at most {_NOTES_MAX_LEN} characters.")
        tv.value = value

    db.session.commit()
    return tv


def compute_rankings(session_id, low_wins=False):
    """
    Return a list of dicts sorted by score field value, highest first (or
    lowest first when low_wins).
    Each dict: {"player_id", "team_id", "player", "team", "position", "score"}
    Ties share a position with a gap (two 1sts → next is 3rd).
    """
    score_field = TrackerField.query.filter_by(
        tracker_session_id=session_id, is_score_field=True
    ).first()
    if score_field is None:
        raise ServiceError("No score field yet. Add one before ending the game.")

    values = TrackerValue.query.filter_by(tracker_field_id=score_field.id).all()
    sorted_vals = sorted(values, key=lambda v: int(v.value), reverse=not low_wins)

    rankings = []
    pos = 1
    for i, v in enumerate(sorted_vals):
        if i > 0 and int(v.value) != int(sorted_vals[i - 1].value):
            pos = i + 1
        rankings.append(
            {
                "player_id": v.player_id,
                "team_id": v.team_id,
                "player": v.player,
                "team": v.team,
                "position": pos,
                "score": int(v.value),
            }
        )
    return rankings


def save_results(session_id, positions=None):
    """
    Write the session's results (an INSERT ... ON CONFLICT upsert, like log_results).

    Scores come from the tracked values, never from the caller. Places start
    from compute_rankings; positions ({("player"|"team", id): place}) lets
    the host change any place on the confirm page, each 1..number of entries.
    In team mode, all team members get the team's position and score.
    Marks session status = "completed".
    """
    session = db.session.get(TrackerSession, session_id)
    if session is None:
        raise ServiceError("That tracker no longer exists.")
    if session.status != "active":
        raise ServiceError("This tracker isn't running, so there's nothing to save.")
    night_policy.require_editable(session.game_night_game.game_night)

    gng_id = session.game_night_game_id
    rankings = compute_rankings(session_id)
    by_key = {
        ("player", r["player_id"]) if r["player_id"] is not None else ("team", r["team_id"]): r
        for r in rankings
    }
    for key, place in (positions or {}).items():
        if key not in by_key:
            raise ServiceError("That player or team isn't in this tracker.")
        if not isinstance(place, int) or not 1 <= place <= len(rankings):
            raise ServiceError(f"Places go from 1 to {len(rankings)}.")
        by_key[key]["position"] = place

    for entry in rankings:
        if entry["player_id"] is not None:
            upsert_result(gng_id, entry["player_id"], entry["position"], entry["score"])
        else:
            for player in entry["team"].players:
                upsert_result(gng_id, player.id, entry["position"], entry["score"])

    session.status = "completed"
    db.session.commit()


def _seed_value(session_id, field, *, player_id, team_id):
    initial = (
        str(field.starting_value)
        if field.type in ("counter", "global_counter")
        else ("false" if field.type == "checkbox" else "")
    )
    v = TrackerValue(
        tracker_session_id=session_id,
        tracker_field_id=field.id,
        player_id=player_id,
        team_id=team_id,
        value=initial,
    )
    db.session.add(v)
