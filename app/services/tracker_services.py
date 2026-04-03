from app.extensions import db
from app.models import (  # noqa: F401 — partial imports used by later functions in this module
    Player,
    Result,
    TrackerField,
    TrackerSession,
    TrackerTeam,
    TrackerValue,
    tracker_team_players,
)

GLOBAL_FIELD_TYPES = {"global_counter", "global_notes"}
PER_PLAYER_FIELD_TYPES = {"counter", "checkbox", "player_notes"}
VALID_FIELD_TYPES = GLOBAL_FIELD_TYPES | PER_PLAYER_FIELD_TYPES

_DELTA_MAX = 100
_NOTES_MAX_LEN = 500


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
    db.session.add(session)
    db.session.commit()
    return session


def discard_session(session_id):
    """Delete a tracker session and all its children (cascade handles FK children)."""
    session = TrackerSession.query.get(session_id)
    if session:
        db.session.delete(session)
        db.session.commit()


def add_field(session_id, *, type, label, starting_value=0, is_score_field=False):
    """Add a TrackerField to a configuring session. Does not seed values yet."""
    session = TrackerSession.query.get(session_id)
    if session is None or session.status != "configuring":
        raise ValueError("Fields can only be added to a session in 'configuring' status")
    if type not in VALID_FIELD_TYPES:
        raise ValueError(
            f"Unknown field type: {type!r}. Must be one of: {sorted(VALID_FIELD_TYPES)}"
        )
    label = label.strip() if label else ""
    if not label:
        raise ValueError("Field label cannot be empty")
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
    return field


def launch_session(session_id, *, mode, teams_data, player_ids, field_order=None):
    """
    Activate a configuring session. Seeds all TrackerValue rows.

    teams_data: list of {"name": str, "player_ids": [int]} — only used when mode="teams"
    player_ids: list of Player.id — all players for the game night (individual mode)
    field_order: list of TrackerField.id in desired sort order (optional)
    """
    session = TrackerSession.query.get_or_404(session_id)
    if session.status != "configuring":
        raise ValueError("Only sessions in 'configuring' status can be launched")

    # Require at least one score field before launch
    score_field = TrackerField.query.filter_by(
        tracker_session_id=session_id, is_score_field=True
    ).first()
    if score_field is None:
        raise ValueError("At least one field must be marked as the score field before launching")

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
    session = TrackerSession.query.get(session_id)
    if session is None or session.status != "active":
        raise ValueError("Values can only be updated for sessions in 'active' status")

    # Validate field belongs to this session
    field = TrackerField.query.filter_by(id=field_id, tracker_session_id=session_id).first()
    if field is None:
        raise ValueError(f"TrackerField {field_id} not found in session {session_id}")

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
        raise ValueError(
            f"TrackerValue not found for field {field_id}, entity_type={entity_type}, entity_id={entity_id}"
        )

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
                raise ValueError(
                    f"Counter field '{field.label}' requires an integer value, got: {value!r}"
                )
        elif field.type == "checkbox":
            if value not in ("true", "false"):
                raise ValueError(
                    f"Checkbox field '{field.label}' requires 'true' or 'false', got: {value!r}"
                )
        elif field.type in ("player_notes", "global_notes"):
            if len(value) > _NOTES_MAX_LEN:
                raise ValueError(
                    f"Note value exceeds maximum length of {_NOTES_MAX_LEN} characters"
                )
        tv.value = value

    db.session.commit()
    return tv


def compute_rankings(session_id):
    """
    Return a list of dicts sorted descending by score field value.
    Each dict: {"player_id", "team_id", "player", "team", "position", "score"}
    Ties share a position with a gap (two 1sts → next is 3rd).
    """
    score_field = TrackerField.query.filter_by(
        tracker_session_id=session_id, is_score_field=True
    ).first()
    if score_field is None:
        raise ValueError(f"No score field found for session {session_id}")

    values = TrackerValue.query.filter_by(tracker_field_id=score_field.id).all()
    sorted_vals = sorted(values, key=lambda v: int(v.value), reverse=True)

    rankings = []
    pos = 1
    for i, v in enumerate(sorted_vals):
        if i > 0 and int(v.value) < int(sorted_vals[i - 1].value):
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


def save_results(session_id, rankings):
    """
    Write Result rows using fetch-or-create upsert. Mirrors log_results pattern.
    In team mode, all team members get the team's position and score.
    Marks session status = "completed".
    """
    session = TrackerSession.query.get(session_id)
    if session is None:
        raise ValueError(f"TrackerSession {session_id} not found")
    if session.status != "active":
        raise ValueError("Results can only be saved for sessions in 'active' status")

    gng_id = session.game_night_game_id

    # Build valid participant sets from seeded TrackerValues
    seeded = TrackerValue.query.filter_by(tracker_session_id=session_id).all()
    valid_player_ids = {tv.player_id for tv in seeded if tv.player_id is not None}
    valid_team_ids = {tv.team_id for tv in seeded if tv.team_id is not None}

    for entry in rankings:
        if entry.get("player_id") is not None:
            if entry["player_id"] not in valid_player_ids:
                raise ValueError(
                    f"Player {entry['player_id']} is not a participant in this session"
                )
            _upsert_result(gng_id, entry["player_id"], entry["position"], entry["score"])
        elif entry.get("team_id") is not None:
            if entry["team_id"] not in valid_team_ids:
                raise ValueError(f"Team {entry['team_id']} is not in this session")
            team = TrackerTeam.query.get(entry["team_id"])
            for player in team.players:
                _upsert_result(gng_id, player.id, entry["position"], entry["score"])

    session.status = "completed"
    db.session.commit()


def _upsert_result(game_night_game_id, player_id, position, score):
    result = Result.query.filter_by(
        game_night_game_id=game_night_game_id, player_id=player_id
    ).first()
    if not result:
        result = Result(game_night_game_id=game_night_game_id, player_id=player_id)
        db.session.add(result)
    result.position = position
    result.score = score


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
