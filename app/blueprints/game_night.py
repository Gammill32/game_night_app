# blueprints/game_night.py

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import GameNightGame, TrackerSession
from app.services import admin_services, game_night_services
from app.utils import admin_required, flash_if_no_action, game_night_access_required

game_night_bp = Blueprint("game_night", __name__)


@game_night_bp.route("/game_night/start", methods=["GET", "POST"])
@login_required
@admin_required
@flash_if_no_action("Please provide the required data to start a game night.", "error")
def start_game_night():
    if request.method == "POST":
        date_str = request.form.get("date")
        notes = request.form.get("notes")
        attendees_ids = request.form.getlist("attendees")

        success, message = game_night_services.start_game_night(date_str, notes, attendees_ids)
        flash(message, "success" if success else "error")

        if success:
            return redirect(url_for("main.index"))

    people = admin_services.get_all_people()

    context = {"people": people}
    return render_template("start_game_night.html", **context)


@game_night_bp.route("/game_night/<int:game_night_id>")
@login_required
@game_night_access_required
def view_game_night(game_night_id):
    """View the details of a specific game night."""
    context = game_night_services.get_view_game_night_details(game_night_id, current_user.id)
    game_night_games = context.get("game_night_games", [])
    tracker_sessions = (
        {
            ts.game_night_game_id: ts
            for ts in TrackerSession.query.filter(
                TrackerSession.game_night_game_id.in_(
                    [gng.game_night_game_id for gng in game_night_games]
                ),
                TrackerSession.status.in_(["configuring", "active"]),
            ).all()
        }
        if game_night_games
        else {}
    )
    context["tracker_sessions"] = tracker_sessions
    return render_template("view_game_night.html", **context)


@game_night_bp.route("/game_night/<int:game_night_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def edit_game_night(game_night_id):
    game_night, people, current_attendees = game_night_services.get_game_night_details(
        game_night_id
    )

    if request.method == "POST":
        date_str = request.form.get("date")
        notes = request.form.get("notes")
        attendees_ids = request.form.getlist("attendees")

        success, message = game_night_services.edit_game_night(
            game_night_id, date_str, notes, attendees_ids
        )
        flash(message, "success" if success else "error")

        if success:
            return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

    context = {"game_night": game_night, "people": people, "current_attendees": current_attendees}
    return render_template("edit_game_night.html", **context)


@game_night_bp.route("/game_night/<int:game_night_id>/manage_game", methods=["POST"])
@login_required
@admin_required
def manage_game_in_night(game_night_id):
    action = request.form.get("action")
    game_night_game_id = request.form.get("game_night_game_id")
    game_id = request.form.get("game_id")
    round_number = request.form.get("round_number")

    success, message = game_night_services.manage_game_in_night(
        game_night_id, game_id, action, round_number, game_night_game_id
    )
    flash(message, "success" if success else "error")

    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))


@game_night_bp.route(
    "/game_night/<int:game_night_id>/log_results/<int:game_night_game_id>", methods=["GET", "POST"]
)
@login_required
@admin_required
def log_results(game_night_id, game_night_game_id):
    if request.method == "POST":
        data = request.get_json()
        if not data:
            flash("No data received", "error")
            return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

        success, message = game_night_services.log_results(game_night_id, game_night_game_id, data)
        flash(message, "success" if success else "error")
        return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

    game_night_game, players, existing_results = game_night_services.get_log_results_data(
        game_night_game_id
    )

    context = {
        "game_night_id": game_night_id,
        "game_night_game": game_night_game,
        "players": players,
        "existing_results": existing_results,
    }
    return render_template("log_results.html", **context)


@game_night_bp.route("/game_night/<int:game_night_id>/toggle/<string:field>", methods=["POST"])
@login_required
@admin_required
def toggle_game_night_field(game_night_id, field):
    success, message = game_night_services.toggle_game_night_field(game_night_id, field)
    flash(message, "success" if success else "error")
    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))


@game_night_bp.route("/game_night/<int:game_night_id>/add_game", methods=["GET", "POST"])
@login_required
@admin_required
def add_game_to_night(game_night_id):
    if request.method == "POST":
        game_id = request.form.get("game_id", type=int)
        round_number = request.form.get("round", type=int)

        success, message = game_night_services.manage_game_in_night(
            game_night_id=game_night_id, game_id=game_id, action="add", round_number=round_number
        )

        flash(message, "success" if success else "danger")
        return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

    """Render the page for selecting a game and round to add to the game night."""
    game_night = game_night_services.get_game_night_by_id(game_night_id)  # Fetch game night details

    # Capture filters from request args
    name_filter = request.args.get("name", "").strip()
    players_filter = request.args.get("players", type=int)
    playtime_filter = request.args.get("playtime", type=int)

    # Fetch games that match criteria
    games = game_night_services.get_filtered_games_for_game_night(
        game_night_id, name_filter, players_filter, playtime_filter, current_user_id=current_user.id
    )

    # ✅ Get the next round number
    existing_rounds = [
        gng.round for gng in GameNightGame.query.filter_by(game_night_id=game_night_id).all()
    ]
    next_round = max(existing_rounds, default=0) + 1

    attending_person_ids = {player.people_id for player in game_night.players}

    context = {
        "game_night": game_night,
        "games": games,
        "filters": {
            "name": name_filter,
            "players": players_filter,
            "playtime": playtime_filter,
        },
        "next_round": next_round,
        "attending_person_ids": attending_person_ids,
    }
    return render_template("add_game_to_night.html", **context)


@game_night_bp.route("/game_night/<int:game_night_id>/delete", methods=["POST"])
@login_required
@admin_required
def delete_game_night(game_night_id):
    success, message = game_night_services.delete_game_night(game_night_id)
    flash(message, "success" if success else "error")
    return redirect(url_for("main.index"))


@game_night_bp.route("/game_night/<int:game_night_id>/create_availability_poll", methods=["POST"])
@login_required
@admin_required
def create_availability_poll(game_night_id):
    from app.services.poll_services import create_availability_poll as _create_poll

    _create_poll(game_night_id, current_user.id)
    flash("Availability poll created.", "success")
    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))


@game_night_bp.route("/game_night/<int:game_night_id>/recap")
def recap_game_night(game_night_id):
    """Public read-only recap of a completed game night."""
    details = game_night_services.get_recap_details(game_night_id)
    return render_template("recap_game_night.html", **details)
