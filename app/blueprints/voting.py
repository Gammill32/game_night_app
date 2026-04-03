from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.services import voting_services
from app.utils import flash_if_no_action, game_night_access_required

voting_bp = Blueprint("voting", __name__)


@voting_bp.route("/game_night/<int:game_night_id>/nominate", methods=["POST"])
@login_required
@game_night_access_required
def nominate_game(game_night_id):
    success, message = voting_services.nominate_game(
        game_night_id, current_user.id, request.form.get("game_id")
    )
    flash(message, "success" if success else "error")

    context = {"game_night_id": game_night_id}
    return redirect(url_for("game_night.view_game_night", **context))


@voting_bp.route("/game_night/<int:game_night_id>/nominate", methods=["GET"])
@login_required
@game_night_access_required
def nominate_game_page(game_night_id):
    """Show a page where user can visually nominate a game."""
    context = voting_services.get_nominate_game_page_context(game_night_id, current_user.id)
    return render_template("nominate_game.html", **context)


@voting_bp.route("/game_night/<int:game_night_id>/vote", methods=["POST"])
@login_required
@game_night_access_required
@flash_if_no_action("No votes were submitted. Please rank at least one game.", "error")
def vote_game(game_night_id):
    votes_dict = {}
    for key, value in request.form.items():
        if key.startswith("votes[") and key.endswith("]"):
            game_id = int(key[6:-1])
            if value.strip():
                try:
                    votes_dict[game_id] = int(value)
                except ValueError:
                    continue
            else:
                votes_dict[game_id] = None

    success, message = voting_services.vote_game(game_night_id, current_user.id, votes_dict)
    flash(message, "success" if success else "error")

    context = {"game_night_id": game_night_id}
    return redirect(url_for("game_night.view_game_night", **context))
