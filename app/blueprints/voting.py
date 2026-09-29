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
    from app.models import GameNight, GameNominations, Player
    from app.services import game_picker_services

    game_night = GameNight.query.get_or_404(game_night_id)
    items, player_count = game_picker_services.picker_items(game_night, current_user.id)
    me = Player.query.filter_by(game_night_id=game_night_id, people_id=current_user.id).first()
    mine = (
        me and GameNominations.query.filter_by(game_night_id=game_night_id, player_id=me.id).first()
    )
    my_game_id = mine.game_id if mine else None
    # Games someone else nominated can't be nominated again.
    available = [i for i in items if not i["nominated_by"] or i["game"].id == my_game_id]
    return render_template(
        "nominate_game.html",
        game_night=game_night,
        sections=[(None, available)],
        player_count=player_count,
        my_nomination=mine.game if mine else None,
    )


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
