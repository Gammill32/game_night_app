# blueprints/tracker.py

from flask import (
    Blueprint,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.models import GameNightGame, TrackerSession
from app.services import night_policy, tracker_services
from app.services.errors import ServiceError
from app.utils.errors import service_error_response

tracker_bp = Blueprint("tracker", __name__)


def _get_session_or_404(session_id):
    session = db.session.get(TrackerSession, session_id)
    if session is None:
        abort(404)
    return session


def _assert_manager(session):
    """Abort 403 unless current user hosts this session's night (or is an admin)."""
    if not night_policy.can_manage(session.game_night_game.game_night, current_user):
        abort(403)


def _int_or_none(raw):
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _assert_gng_participant_or_admin(gng):
    """Abort 403 if current user is not a participant of this game night or admin."""
    if not tracker_services.can_track(gng.game_night, current_user):
        abort(403)


@tracker_bp.route("/game_night/<int:gng_id>/tracker/new")
@login_required
def setup_tracker(gng_id):
    gng = db.get_or_404(GameNightGame, gng_id)
    gn = gng.game_night
    _assert_gng_participant_or_admin(gng)
    if gn.final:
        flash("This game night is finalized, so it can't be tracked.", "error")
        return redirect(url_for("game_night.view_game_night", game_night_id=gn.id))
    # Redirect away from completed sessions — can't re-track a finished game
    if tracker_services.find_session(gng_id, "completed"):
        return redirect(url_for("game_night.view_game_night", game_night_id=gn.id))
    # Resume active session if one exists
    active = tracker_services.find_session(gng_id, "active")
    if active:
        return redirect(url_for("tracker.live_tracker", session_id=active.id))
    session = tracker_services.get_or_create_configuring_session(gng_id)
    return render_template(
        "tracker_setup.html",
        session=session,
        gng=gng,
        gn=gn,
        can_manage=night_policy.can_manage(gn, current_user),
        **tracker_services.setup_context(session, gn),
    )


@tracker_bp.route("/game_night/<int:gng_id>/tracker", methods=["POST"])
@login_required
def launch_tracker(gng_id):
    gng = db.get_or_404(GameNightGame, gng_id)
    _assert_gng_participant_or_admin(gng)

    session_id = _int_or_none(request.form.get("session_id"))
    if session_id is None:
        abort(400, "Invalid session for this game.")
    # Verify session belongs to this gng — prevents IDOR
    if tracker_services.find_session(gng_id, session_id=session_id) is None:
        abort(400, "Invalid session for this game.")

    mode = request.form.get("mode", "individual")
    try:
        player_ids = [int(pid) for pid in request.form.getlist("player_ids")]
        field_order_str = request.form.get("field_order", "").strip()
        field_order = (
            [int(fid) for fid in field_order_str.split(",") if fid.strip()]
            if field_order_str
            else None
        )
    except ValueError:
        abort(400, "Invalid player or field.")

    teams_data = []
    if mode == "teams":
        team_names = request.form.getlist("team_names")
        teams_data = [{"name": name, "player_ids": []} for name in team_names]
        # Each player picks one team: team_of_<player_id> = team index ('' = sitting out).
        # (team_<i>_player_ids is the older form, still accepted.)
        for key, value in request.form.items():
            if key.startswith("team_of_") and value.isdigit() and int(value) < len(teams_data):
                teams_data[int(value)]["player_ids"].append(int(key[len("team_of_") :]))
        for i, team in enumerate(teams_data):
            team["player_ids"] += [
                int(pid) for pid in request.form.getlist(f"team_{i}_player_ids") if pid.isdigit()
            ]
        teams_data = [t for t in teams_data if t["player_ids"]]
        if len(teams_data) < 2:
            flash("Put players on at least two teams.", "error")
            return redirect(url_for("tracker.setup_tracker", gng_id=gng_id))

    try:
        tracker_services.launch_session(
            session_id,
            mode=mode,
            teams_data=teams_data,
            player_ids=player_ids,
            field_order=field_order,
        )
    except ServiceError as e:
        return service_error_response(
            e, redirect_to=url_for("tracker.setup_tracker", gng_id=gng_id)
        )

    return redirect(url_for("tracker.live_tracker", session_id=session_id))


@tracker_bp.route("/tracker/<int:session_id>")
@login_required
def live_tracker(session_id):
    session = _get_session_or_404(session_id)
    _assert_gng_participant_or_admin(session.game_night_game)
    gn = session.game_night_game.game_night
    if gn.final:
        return redirect(url_for("game_night.view_game_night", game_night_id=gn.id))
    return render_template(
        "tracker_live.html",
        session=session,
        gn=gn,
        can_manage=night_policy.can_manage(gn, current_user),
        **tracker_services.live_context(session),
    )


@tracker_bp.route("/tracker/<int:session_id>/field", methods=["POST"])
@login_required
def add_field(session_id):
    session = _get_session_or_404(session_id)
    _assert_gng_participant_or_admin(session.game_night_game)
    field_type = request.form.get("type", "")
    label = request.form.get("label", "")
    starting_value = _int_or_none(request.form.get("starting_value") or 0)
    if starting_value is None:
        return "Starting value must be a whole number.", 400
    is_score_field = request.form.get("is_score_field", "false").lower() == "true"
    field = tracker_services.add_field(
        session_id,
        type=field_type,
        label=label,
        starting_value=starting_value,
        is_score_field=is_score_field,
    )
    response = make_response(
        render_template("_tracker_field_row.html", field=field, session=session)
    )
    if getattr(field, "replaced_score_field", False):
        response.headers["HX-Refresh"] = "true"  # the old score field changed; redraw
    return response


@tracker_bp.route("/tracker/<int:session_id>/value", methods=["POST"])
@login_required
def update_value(session_id):
    session = _get_session_or_404(session_id)
    _assert_gng_participant_or_admin(session.game_night_game)
    field_id = _int_or_none(request.form.get("field_id"))
    entity_type = request.form.get("entity_type", "")
    entity_id = _int_or_none(request.form.get("entity_id"))
    delta = _int_or_none(request.form.get("delta"))
    if (
        field_id is None
        or (request.form.get("entity_id") and entity_id is None)
        or (request.form.get("delta") and delta is None)
    ):
        return "Field, player and change must be whole numbers.", 400
    value = request.form.get("value")
    if request.form.get("kind") == "checkbox":
        value = "true" if value == "true" else "false"
    tv = tracker_services.update_value(
        session_id,
        field_id,
        entity_type=entity_type,
        entity_id=entity_id,
        delta=delta,
        value=value,
    )
    return render_template(
        "_tracker_cell.html",
        tv=tv,
        field=tv.field,
        session=session,
        entity_type=entity_type,
        entity_id=entity_id,
    )


@tracker_bp.route("/tracker/<int:session_id>/end")
@login_required
def end_game(session_id):
    session = _get_session_or_404(session_id)
    _assert_manager(session)
    if session.status == "completed":
        return redirect(
            url_for(
                "game_night.view_game_night",
                game_night_id=session.game_night_game.game_night_id,
            )
        )
    try:
        low_wins = request.args.get("low") == "1"
        rankings = tracker_services.compute_rankings(session_id, low_wins=low_wins)
    except ServiceError as e:
        return service_error_response(
            e, redirect_to=url_for("tracker.live_tracker", session_id=session_id)
        )
    gng = session.game_night_game
    has_existing_results = bool(gng.results)
    return render_template(
        "tracker_confirm.html",
        session=session,
        rankings=rankings,
        low_wins=low_wins,
        has_existing_results=has_existing_results,
    )


@tracker_bp.route("/tracker/<int:session_id>/save", methods=["POST"])
@login_required
def save_results(session_id):
    """Results are official, so only the night's host or an admin saves them.
    Scores are taken from the tracker; the form can only change places."""
    session = _get_session_or_404(session_id)
    _assert_manager(session)
    positions = {}
    for key, pos in request.form.items():
        for prefix, kind in (("position_p_", "player"), ("position_t_", "team")):
            if key.startswith(prefix):
                entity_id = _int_or_none(key[len(prefix) :])
                if entity_id is None:
                    abort(400)
                positions[(kind, entity_id)] = _int_or_none(pos)
    try:
        tracker_services.save_results(session_id, positions)
    except ServiceError as e:
        return service_error_response(
            e, redirect_to=url_for("tracker.end_game", session_id=session_id)
        )
    gn_id = session.game_night_game.game_night_id
    return redirect(
        url_for(
            "game_night.view_game_night",
            game_night_id=gn_id,
            saved=session.game_night_game_id,  # which game the winner sweep plays on
            _anchor="played",
        )
    )


@tracker_bp.route("/tracker/<int:session_id>/discard", methods=["POST"])
@login_required
def discard_tracker(session_id):
    session = _get_session_or_404(session_id)
    _assert_manager(session)
    gn_id = session.game_night_game.game_night_id
    tracker_services.discard_session(session_id)
    return redirect(url_for("game_night.view_game_night", game_night_id=gn_id))
