# blueprints/games.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.services import games_services

games_bp = Blueprint("games", __name__)

@games_bp.route("/games", methods=["GET"])
@login_required
def games_index():
    name_filter = request.args.get("name", "").strip()
    players_filter = request.args.get("players", type=int)
    playtime_filter = request.args.get("playtime", type=int)
    
    games_with_ownership = games_services.get_filtered_games(current_user.id, name_filter, players_filter, playtime_filter)
    return render_template("games_index.html", games=games_with_ownership)

@games_bp.route("/game/add", methods=["GET", "POST"])
@login_required
def add_game():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        bgg_id = request.form.get("bgg_id", "").strip()
        
        success, message = games_services.add_game(current_user.id, name, bgg_id)
        flash(message, "success" if success else "error")
        
        return redirect(url_for("games.add_game"))
    
    return render_template("add_game.html")

@games_bp.route("/game/<int:game_id>")
@login_required
def view_game(game_id):
    game, leaderboard, game_nights = games_services.get_game_details(game_id)
    return render_template("view_game.html", game=game, leaderboard=leaderboard, game_nights=game_nights)

@games_bp.route("/game/<int:game_id>/claim", methods=["POST"])
@login_required
def claim_game(game_id):
    success, message = games_services.modify_ownership(current_user.id, game_id, add=True)
    if success:
        games_services.modify_wishlist(current_user.id, game_id, remove=True)  # Remove from wishlist if ownership is claimed
    flash(message, "success" if success else "error")
    return redirect(url_for("games.games_index"))

@games_bp.route("/game/<int:game_id>/remove_ownership", methods=["POST"])
@login_required
def remove_ownership(game_id):
    success, message = games_services.modify_ownership(current_user.id, game_id, add=False)
    flash(message, "success" if success else "error")
    return redirect(url_for("games.games_index"))

@games_bp.route("/wishlist", methods=["GET"])
@login_required
def wishlist():
    wishlist_games = games_services.get_wishlist(current_user.id)
    return render_template("wishlist.html", games=wishlist_games)

@games_bp.route("/wishlist/add", methods=["GET", "POST"])
@login_required
def add_to_wishlist():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        bgg_id = request.form.get("bgg_id", "").strip()
        
        success, message = games_services.add_game_to_wishlist(current_user.id, name, bgg_id)
        flash(message, "success" if success else "error")
        
        return redirect(url_for("games.wishlist"))
    
    return render_template("add_to_wishlist.html")

@games_bp.route("/wishlist/remove/<int:game_id>", methods=["POST"])
@login_required
def remove_from_wishlist(game_id):
    success, message = games_services.modify_wishlist(current_user.id, game_id, remove=True)
    flash(message, "success" if success else "error")
    return redirect(url_for("games.wishlist"))
