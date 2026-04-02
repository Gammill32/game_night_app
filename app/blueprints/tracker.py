# blueprints/tracker.py

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import (  # noqa: F401
    GameNightGame,
    Player,
    TrackerField,
    TrackerSession,
    TrackerValue,
)
from app.services import tracker_services

tracker_bp = Blueprint("tracker", __name__)


def _get_session_or_404(session_id):
    session = TrackerSession.query.get(session_id)
    if session is None:
        abort(404)
    return session


def _assert_participant_or_admin(session):
    """Abort 403 if current user is not a participant of the session's game night or admin."""
    if current_user.admin:
        return
    gng = session.game_night_game
    is_participant = Player.query.filter_by(
        game_night_id=gng.game_night_id, people_id=current_user.id
    ).first()
    if not is_participant:
        abort(403)


def _assert_gng_participant_or_admin(gng):
    """Abort 403 if current user is not a participant of this game night or admin."""
    if current_user.admin:
        return
    is_participant = Player.query.filter_by(
        game_night_id=gng.game_night_id, people_id=current_user.id
    ).first()
    if not is_participant:
        abort(403)


@tracker_bp.route("/game_night/<int:gng_id>/tracker/new")
@login_required
def setup_tracker(gng_id):
    gng = GameNightGame.query.get_or_404(gng_id)
    gn = gng.game_night
    _assert_gng_participant_or_admin(gng)
    if gn.final:
        abort(400, "Cannot start a tracker for a finalized game night.")
    # Redirect away from completed sessions — can't re-track a finished game
    completed = TrackerSession.query.filter_by(
        game_night_game_id=gng_id, status="completed"
    ).first()
    if completed:
        return redirect(url_for("game_night.view_game_night", game_night_id=gn.id))
    # Resume active session if one exists
    active = TrackerSession.query.filter_by(
        game_night_game_id=gng_id, status="active"
    ).first()
    if active:
        return redirect(url_for("tracker.live_tracker", session_id=active.id))
    session = tracker_services.get_or_create_configuring_session(gng_id)
    players = Player.query.filter_by(game_night_id=gn.id).all()
    fields = TrackerField.query.filter_by(
        tracker_session_id=session.id
    ).order_by(TrackerField.sort_order).all()
    return render_template(
        "tracker_setup.html", session=session, gng=gng, gn=gn, players=players, fields=fields
    )


@tracker_bp.route("/game_night/<int:gng_id>/tracker", methods=["POST"])
@login_required
def launch_tracker(gng_id):
    gng = GameNightGame.query.get_or_404(gng_id)
    _assert_gng_participant_or_admin(gng)

    session_id = int(request.form["session_id"])
    # Verify session belongs to this gng — prevents IDOR
    session = TrackerSession.query.filter_by(
        id=session_id, game_night_game_id=gng_id
    ).first()
    if session is None:
        abort(400, "Invalid session for this game.")

    mode = request.form.get("mode", "individual")
    player_ids = [int(pid) for pid in request.form.getlist("player_ids")]
    field_order_str = request.form.get("field_order", "").strip()
    field_order = (
        [int(fid) for fid in field_order_str.split(",") if fid.strip()]
        if field_order_str else None
    )

    teams_data = []
    if mode == "teams":
        team_names = request.form.getlist("team_names")
        for i, name in enumerate(team_names):
            t_player_ids = [int(pid) for pid in request.form.getlist(f"team_{i}_player_ids")]
            teams_data.append({"name": name, "player_ids": t_player_ids})

    try:
        tracker_services.launch_session(
            session_id, mode=mode, teams_data=teams_data,
            player_ids=player_ids, field_order=field_order,
        )
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("tracker.setup_tracker", gng_id=gng_id))

    return redirect(url_for("tracker.live_tracker", session_id=session_id))


@tracker_bp.route("/tracker/<int:session_id>")
@login_required
def live_tracker(session_id):
    session = _get_session_or_404(session_id)
    _assert_participant_or_admin(session)
    gn = session.game_night_game.game_night
    if gn.final:
        return redirect(url_for("game_night.view_game_night", game_night_id=gn.id))
    # Batch-load all values for this session in one query
    all_values = TrackerValue.query.filter_by(tracker_session_id=session_id).all()
    # Build value lookup: {(field_id, player_id, team_id): TrackerValue}
    value_map = {(v.tracker_field_id, v.player_id, v.team_id): v for v in all_values}
    players = Player.query.filter_by(game_night_id=gn.id).all() if session.mode == "individual" else []
    teams = session.teams if session.mode == "teams" else []
    global_fields = [f for f in session.fields if f.type in ("global_counter", "global_notes")]
    player_fields = [f for f in session.fields if f.type not in ("global_counter", "global_notes")]
    return render_template(
        "tracker_live.html",
        session=session, gn=gn, players=players, teams=teams,
        global_fields=global_fields, player_fields=player_fields, value_map=value_map,
    )


@tracker_bp.route("/tracker/<int:session_id>/field", methods=["POST"])
@login_required
def add_field(session_id):
    session = _get_session_or_404(session_id)
    _assert_participant_or_admin(session)
    field_type = request.form.get("type", "")
    label = request.form.get("label", "")
    starting_value = int(request.form.get("starting_value", 0))
    is_score_field = request.form.get("is_score_field", "false").lower() == "true"
    try:
        field = tracker_services.add_field(
            session_id, type=field_type, label=label,
            starting_value=starting_value, is_score_field=is_score_field,
        )
    except ValueError as e:
        return str(e), 400
    return render_template("_tracker_field_row.html", field=field, session=session)


@tracker_bp.route("/tracker/<int:session_id>/value", methods=["POST"])
@login_required
def update_value(session_id):
    session = _get_session_or_404(session_id)
    _assert_participant_or_admin(session)
    field_id = int(request.form["field_id"])
    entity_type = request.form["entity_type"]
    entity_id = int(request.form["entity_id"]) if request.form.get("entity_id") else None
    delta = int(request.form["delta"]) if request.form.get("delta") else None
    value = request.form.get("value")
    try:
        tv = tracker_services.update_value(
            session_id, field_id, entity_type=entity_type, entity_id=entity_id,
            delta=delta, value=value,
        )
    except ValueError as e:
        return str(e), 400
    field = TrackerField.query.get(field_id)
    return render_template(
        "_tracker_cell.html", tv=tv, field=field, session=session,
        entity_type=entity_type, entity_id=entity_id,
    )


@tracker_bp.route("/tracker/<int:session_id>/end")
@login_required
def end_game(session_id):
    session = _get_session_or_404(session_id)
    _assert_participant_or_admin(session)
    if session.status == "completed":
        return redirect(url_for(
            "game_night.view_game_night",
            game_night_id=session.game_night_game.game_night_id,
        ))
    try:
        rankings = tracker_services.compute_rankings(session_id)
    except ValueError:
        flash("No score field configured. Add a score field before ending the game.", "error")
        return redirect(url_for("tracker.live_tracker", session_id=session_id))
    gng = session.game_night_game
    has_existing_results = bool(gng.results)
    return render_template(
        "tracker_confirm.html",
        session=session, rankings=rankings,
        has_existing_results=has_existing_results,
    )


@tracker_bp.route("/tracker/<int:session_id>/save", methods=["POST"])
@login_required
def save_results(session_id):
    session = _get_session_or_404(session_id)
    _assert_participant_or_admin(session)
    rankings = []
    for key, pos in request.form.items():
        if key.startswith("position_p_"):
            player_id = int(key[len("position_p_"):])
            score = int(request.form.get(f"score_p_{player_id}", 0))
            rankings.append({"player_id": player_id, "team_id": None,
                              "position": int(pos), "score": score})
        elif key.startswith("position_t_"):
            team_id = int(key[len("position_t_"):])
            score = int(request.form.get(f"score_t_{team_id}", 0))
            rankings.append({"player_id": None, "team_id": team_id,
                              "position": int(pos), "score": score})
    try:
        tracker_services.save_results(session_id, rankings)
    except ValueError as e:
        flash(str(e), "error")
        return redirect(url_for("tracker.end_game", session_id=session_id))
    gn_id = session.game_night_game.game_night_id
    return redirect(url_for("game_night.view_game_night", game_night_id=gn_id))


@tracker_bp.route("/tracker/<int:session_id>/discard", methods=["POST"])
@login_required
def discard_tracker(session_id):
    session = _get_session_or_404(session_id)
    _assert_participant_or_admin(session)
    gn_id = session.game_night_game.game_night_id
    tracker_services.discard_session(session_id)
    return redirect(url_for("game_night.view_game_night", game_night_id=gn_id))
