# blueprints/tracker.py

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import GameNightGame, Player, TrackerField, TrackerSession, TrackerValue  # noqa: F401
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


@tracker_bp.route("/game_night/<int:gng_id>/tracker/new")
@login_required
def setup_tracker(gng_id):
    gng = GameNightGame.query.get_or_404(gng_id)
    gn = gng.game_night
    if gn.final:
        abort(400, "Cannot start a tracker for a finalized game night.")
    # Resume active session if one exists
    active = TrackerSession.query.filter_by(game_night_game_id=gng_id, status="active").first()
    if active:
        return redirect(url_for("tracker.live_tracker", session_id=active.id))
    session = tracker_services.get_or_create_configuring_session(gng_id)
    players = Player.query.filter_by(game_night_id=gn.id).all()
    fields = TrackerField.query.filter_by(tracker_session_id=session.id).order_by(TrackerField.sort_order).all()
    return render_template("tracker_setup.html", session=session, gng=gng, gn=gn, players=players, fields=fields)


@tracker_bp.route("/game_night/<int:gng_id>/tracker", methods=["POST"])
@login_required
def launch_tracker(gng_id):
    gng = GameNightGame.query.get_or_404(gng_id)
    session_id = int(request.form["session_id"])
    mode = request.form.get("mode", "individual")
    player_ids = [int(pid) for pid in request.form.getlist("player_ids")]

    teams_data = []
    if mode == "teams":
        team_names = request.form.getlist("team_names")
        for i, name in enumerate(team_names):
            t_player_ids = [int(pid) for pid in request.form.getlist(f"team_{i}_player_ids")]
            teams_data.append({"name": name, "player_ids": t_player_ids})

    tracker_services.launch_session(session_id, mode=mode, teams_data=teams_data, player_ids=player_ids)
    return redirect(url_for("tracker.live_tracker", session_id=session_id))
