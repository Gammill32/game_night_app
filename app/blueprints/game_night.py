# blueprints/game_night.py

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.models import TrackerSession
from app.services import (
    admin_services,
    food_services,
    game_night_services,
    game_picker_services,
    photo_services,
    poll_services,
)
from app.utils import game_night_access_required, host_required, night_manager_required

game_night_bp = Blueprint("game_night", __name__)


@game_night_bp.route("/game_night/start", methods=["GET", "POST"])
@login_required
@host_required
def start_game_night():
    form = request.form
    if request.method == "POST":
        try:
            food = food_services.parse_food_settings(form, current_user.id)
        except food_services.FoodError as e:
            flash(str(e), "error")
        else:
            success, message, game_night = game_night_services.start_game_night(
                form.get("date"),
                form.get("notes"),
                form.getlist("attendees"),
                food,
                host_id=current_user.id,
            )
            if success and form.get("rsvp_poll"):
                poll_services.create_availability_poll(game_night.id, current_user.id)
                message = "Game night started. Players can RSVP on its page."
            flash(message, "success" if success else "error")
            if success:
                return redirect(url_for("game_night.view_game_night", game_night_id=game_night.id))

    context = {
        "people": admin_services.get_all_people(),
        "food_mode_labels": food_services.FOOD_MODE_LABELS,
        "food_mode": form.get("food_mode", "none"),
        "food_provider_id": None,
        "food_note": form.get("food_note"),
    }
    return render_template("start_game_night.html", **context)


@game_night_bp.route("/people/quick_add", methods=["POST"])
@login_required
@host_required
def quick_add_person():
    """From the player picker: add someone who isn't on the site yet (name
    only; they claim the account on the sign-up page). JSON for the picker."""
    from flask import jsonify

    success, message, person = admin_services.create_person(
        request.form.get("first_name"), request.form.get("last_name")
    )
    if person is not None and person.active:
        # Newly added, or already here (then just pick them).
        return jsonify(
            {"id": person.id, "name": f"{person.first_name} {person.last_name}", "message": message}
        )
    return jsonify({"error": message}), 400


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
    context["night_polls"] = [
        poll_services.view_context(poll, current_user.id)
        for poll in context["game_night"].polls
        if poll_services.can_view(poll, current_user)
    ]
    game_night = context["game_night"]
    context["can_manage"] = game_night.managed_by(current_user)
    context["can_upload_photos"] = photo_services.can_upload(game_night, current_user)
    if game_night.food_mode != "none":
        context["food_rows"] = food_services.expense_rows(game_night, current_user)
        context["food_coverable"] = food_services.coverable(game_night)
        context["food_default_covered"] = food_services.default_covered(game_night)
        context["food_is_player"] = food_services.is_player(game_night, current_user)
    context["can_delete_photo"] = photo_services.can_delete
    return render_template("view_game_night.html", **context)


@game_night_bp.route("/game_night/<int:game_night_id>/edit", methods=["GET", "POST"])
@login_required
@night_manager_required
def edit_game_night(game_night_id):
    game_night, people, current_attendees = game_night_services.get_game_night_details(
        game_night_id
    )

    if request.method == "POST":
        form = request.form
        try:
            food = food_services.parse_food_settings(form, current_user.id)
        except food_services.FoodError as e:
            flash(str(e), "error")
        else:
            host_id = None
            if current_user.is_admin_or_owner and form.get("host_id") is not None:
                raw = form.get("host_id", "")
                host_id = int(raw) if raw.isdigit() else 0  # 0 = no host
            success, message = game_night_services.edit_game_night(
                game_night_id,
                form.get("date"),
                form.get("notes"),
                form.getlist("attendees"),
                food,
                host_id=host_id,
            )
            flash(message, "success" if success else "error")
            if success:
                return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

    context = {
        "game_night": game_night,
        "people": people,
        "current_attendees": current_attendees,
        "food_mode_labels": food_services.FOOD_MODE_LABELS,
        "food_mode": game_night.food_mode,
        "food_provider_id": game_night.food_provider_id,
        "food_note": game_night.food_note,
        "host_choices": admin_services.get_all_people(),
    }
    return render_template("edit_game_night.html", **context)


@game_night_bp.route("/game_night/<int:game_night_id>/manage_game", methods=["POST"])
@login_required
@night_manager_required
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
@night_manager_required
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
@night_manager_required
def toggle_game_night_field(game_night_id, field):
    success, message = game_night_services.toggle_game_night_field(game_night_id, field)
    flash(message, "success" if success else "error")
    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))


@game_night_bp.route("/game_night/<int:game_night_id>/add_game", methods=["GET", "POST"])
@login_required
@night_manager_required
def add_game_to_night(game_night_id):
    if request.method == "POST":
        game_id = request.form.get("game_id", type=int)
        round_number = request.form.get("round", type=int)

        success, message = game_night_services.manage_game_in_night(
            game_night_id=game_night_id, game_id=game_id, action="add", round_number=round_number
        )

        flash(message, "success" if success else "danger")
        return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

    game_night = game_night_services.get_game_night_by_id(game_night_id)
    items, player_count = game_picker_services.picker_items(game_night, current_user.id)
    nominated = sorted(
        (i for i in items if i["nominated_by"]), key=lambda i: (-i["vote_score"], i["game"].name)
    )
    others = [i for i in items if not i["nominated_by"]]
    existing_rounds = [gng.round for gng in game_night.game_night_games]
    return render_template(
        "add_game_to_night.html",
        game_night=game_night,
        sections=[("Nominated", nominated), ("Everything else" if nominated else None, others)],
        player_count=player_count,
        next_round=max(existing_rounds, default=0) + 1,
    )


@game_night_bp.route("/game_night/<int:game_night_id>/delete", methods=["POST"])
@login_required
@night_manager_required
def delete_game_night(game_night_id):
    success, message = game_night_services.delete_game_night(game_night_id)
    flash(message, "success" if success else "error")
    return redirect(url_for("main.index"))


@game_night_bp.route("/game_night/<int:game_night_id>/create_availability_poll", methods=["POST"])
@login_required
@night_manager_required
def create_availability_poll(game_night_id):
    success, message = poll_services.create_availability_poll(game_night_id, current_user.id)
    flash(message, "success" if success else "error")
    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id) + "#polls")


@game_night_bp.route("/game_night/<int:game_night_id>/recap")
def recap_game_night(game_night_id):
    """Public read-only recap of a completed game night."""
    details = game_night_services.get_recap_details(game_night_id)
    return render_template("recap_game_night.html", **details)
