# blueprints/game_night.py


from flask import (
    Blueprint,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.services import (
    admin_services,
    food_services,
    game_night_services,
    game_picker_services,
    night_policy,
    photo_services,
    poll_services,
    tracker_services,
)
from app.services.errors import ServiceError
from app.utils import game_night_access_required, host_required, night_manager_required
from app.utils.dates import local_today
from app.utils.errors import service_error_response

game_night_bp = Blueprint("game_night", __name__)


@game_night_bp.errorhandler(ServiceError)
def _refused(error):
    """A refused change to a night: back to the night's page."""
    night_id = (request.view_args or {}).get("game_night_id")
    target = url_for("game_night.view_game_night", game_night_id=night_id) if night_id else None
    return service_error_response(error, redirect_to=target)


@game_night_bp.route("/game_night/start", methods=["GET", "POST"])
@login_required
@host_required
def start_game_night():
    form = request.form
    if request.method == "POST":
        try:
            food = food_services.parse_food_settings(form, current_user.id)
            game_night = game_night_services.start_game_night(
                form.get("date"),
                form.get("notes"),
                form.getlist("attendees"),
                food,
                host_id=current_user.id,
                address=form.get("address"),
                rsvp_poll=bool(form.get("rsvp_poll")),
            )
        except ServiceError as e:
            flash(str(e), "error")  # stay on the form
        else:
            message = "Game night started."
            if form.get("rsvp_poll"):
                message = "Game night started. Players can RSVP on its page."
            flash(message, "success")
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
    context["tracker_sessions"] = tracker_services.open_sessions_by_game(
        [gng.game_night_game_id for gng in context.get("game_night_games", [])]
    )
    context["night_polls"] = [
        poll_services.view_context(poll, current_user.id)
        for poll in context["game_night"].polls
        if poll_services.can_view(poll, current_user)
    ]
    game_night = context["game_night"]
    context["can_manage"] = night_policy.can_manage(game_night, current_user)
    context["voting_open"] = night_policy.voting_open(game_night)
    context["ready_to_finalize"] = night_policy.ready_to_finalize(game_night, local_today())
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
        host_id = None
        if current_user.is_admin_or_owner and form.get("host_id") is not None:
            raw = form.get("host_id", "")
            host_id = int(raw) if raw.isdigit() else 0  # 0 = no host
        try:
            food = food_services.parse_food_settings(form, current_user.id)
            message = game_night_services.edit_game_night(
                game_night_id,
                form.get("date"),
                form.get("notes"),
                form.getlist("attendees"),
                food,
                host_id=host_id,
                address=form.get("address"),
            )
        except ServiceError as e:
            flash(str(e), "error")  # stay on the form
        else:
            flash(message, "success")
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

    message = game_night_services.manage_game_in_night(
        game_night_id, game_id, action, round_number, game_night_game_id
    )
    flash(message, "success")

    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))


@game_night_bp.route(
    "/game_night/<int:game_night_id>/log_results/<int:game_night_game_id>", methods=["GET", "POST"]
)
@login_required
@night_manager_required
def log_results(game_night_id, game_night_game_id):
    if request.method == "POST":
        data = request.get_json(silent=True)
        if not data:
            flash("No data received", "error")
            return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

        # A refused body gets a 400 from the ServiceError handler ({"error": ...}).
        message = game_night_services.log_results(game_night_id, game_night_game_id, data)
        flash(message, "success")
        # The page posts with fetch; answer with where to go rather than redirecting,
        # so the flash survives until the browser loads that page.
        url = url_for(
            "game_night.view_game_night",
            game_night_id=game_night_id,
            saved=game_night_game_id,  # which game the winner sweep plays on
            _anchor="played",
        )
        return jsonify(redirect=url)

    game_night_game, players, existing_results = game_night_services.get_log_results_data(
        game_night_id, game_night_game_id
    )
    if game_night_game.game_night.final:
        flash("This game night is finalized. Reopen it to make changes.", "error")
        return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

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
    message = game_night_services.toggle_game_night_field(game_night_id, field)
    flash(message, "success")
    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))


@game_night_bp.route("/game_night/<int:game_night_id>/finalize", methods=["POST"])
@login_required
@night_manager_required
def finalize_game_night(game_night_id):
    changed, message = game_night_services.finalize(game_night_id)
    flash(message, "success" if changed else "info")
    params = {"finalized": 1} if changed else {}
    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id, **params))


@game_night_bp.route("/game_night/<int:game_night_id>/unfinalize", methods=["POST"])
@login_required
@night_manager_required
def unfinalize_game_night(game_night_id):
    changed, message = game_night_services.unfinalize(game_night_id)
    flash(message, "success" if changed else "info")
    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))


@game_night_bp.route("/game_night/<int:game_night_id>/add_game", methods=["GET", "POST"])
@login_required
@night_manager_required
def add_game_to_night(game_night_id):
    if request.method == "POST":
        game_id = request.form.get("game_id", type=int)
        round_number = request.form.get("round", type=int)

        message = game_night_services.manage_game_in_night(
            game_night_id=game_night_id, game_id=game_id, action="add", round_number=round_number
        )
        flash(message, "success")
        return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

    game_night = game_night_services.get_game_night_by_id(game_night_id)
    if game_night.final:
        flash("This game night is finalized. Reopen it to make changes.", "error")
        return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))
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
    try:
        message = game_night_services.delete_game_night(game_night_id)
    except ServiceError as e:
        return service_error_response(e, redirect_to=url_for("main.index"))
    flash(message, "success")
    return redirect(url_for("main.index"))


@game_night_bp.route("/game_night/<int:game_night_id>/create_availability_poll", methods=["POST"])
@login_required
@night_manager_required
def create_availability_poll(game_night_id):
    polls_url = url_for("game_night.view_game_night", game_night_id=game_night_id) + "#polls"
    try:
        message = poll_services.create_availability_poll(game_night_id, current_user.id)
    except ServiceError as e:
        return service_error_response(e, redirect_to=polls_url)
    flash(message, "success")
    return redirect(polls_url)


@game_night_bp.route("/game_night/<int:game_night_id>/recap")
def recap_game_night(game_night_id):
    """Public read-only recap of a completed game night."""
    details = game_night_services.get_recap_details(game_night_id)
    return render_template("recap_game_night.html", **details)
