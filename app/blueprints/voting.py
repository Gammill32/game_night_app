from flask import Blueprint, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app.services import voting_services
from app.utils import game_night_access_required, flash_if_no_action

voting_bp = Blueprint("voting", __name__)

@voting_bp.route("/game_night/<int:game_night_id>/nominate", methods=["POST"])
@login_required
@game_night_access_required
def nominate_game(game_night_id):
    success, message = voting_services.nominate_game(game_night_id, current_user.id, request.form.get("game_id"))
    flash(message, "success" if success else "error")
    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))

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
    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id))
