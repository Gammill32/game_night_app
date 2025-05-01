# blueprints/games.py

from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.services import games_services
from app.utils import admin_required

games_bp = Blueprint("games", __name__)


@games_bp.route("/games", methods=["GET"])
@login_required
def games_index():
    name_filter = request.args.get("name", "").strip()
    players_filter = request.args.get("players", type=int) if request.args.get("players_enabled") else None
    playtime_filter = request.args.get("playtime", type=int) if request.args.get("playtime_enabled") else None
    min_rating_filter = request.args.get("min_rating", type=int) if request.args.get("min_rating_enabled") else None
    
    games_with_ownership = games_services.get_filtered_games(current_user.id, name_filter, players_filter, playtime_filter, min_rating_filter)
    
    context = {
        "games": games_with_ownership
    }
    return render_template("games_index.html", **context)


@games_bp.route("/game/add", methods=["GET", "POST"])
@login_required
def add_game():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        bgg_id = request.form.get("bgg_id", "").strip()
        
        success, message = games_services.add_game(current_user.id, name, bgg_id)
        flash(message, "success" if success else "error")
        
        return redirect(url_for("games.add_game"))
    
    context = {}
    return render_template("add_game.html", **context)


@games_bp.route("/game/<int:game_id>")
@login_required
def view_game(game_id):
    game, leaderboard, game_nights, user_rating = games_services.get_game_details(game_id, current_user.id)

    context = {
        "game": game,
        "leaderboard": leaderboard,
        "game_nights": game_nights,
        "user_rating": user_rating,
    }
    return render_template("view_game.html", **context)


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
    
    context = {
        "games": wishlist_games
    }
    return render_template("wishlist.html", **context)


@games_bp.route("/wishlist/add", methods=["GET", "POST"])
@login_required
def add_to_wishlist():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        bgg_id = request.form.get("bgg_id", "").strip()
        
        success, message = games_services.add_game_to_wishlist(current_user.id, name, bgg_id)
        flash(message, "success" if success else "error")
        
        return redirect(url_for("games.wishlist"))
    
    context = {}
    return render_template("add_to_wishlist.html", **context)


@games_bp.route("/wishlist/remove/<int:game_id>", methods=["POST"])
@login_required
def remove_from_wishlist(game_id):
    success, message = games_services.modify_wishlist(current_user.id, game_id, remove=True)
    flash(message, "success" if success else "error")
    return redirect(url_for("games.wishlist"))

@games_bp.route("/wishlist/toggle/<int:game_id>", methods=["POST"])
@login_required
def toggle_wishlist(game_id):
    from app.models import Wishlist, OwnedBy  # Adjust if needed

    # If already owned, prevent wishlisting
    owns_game = OwnedBy.query.filter_by(game_id=game_id, person_id=current_user.id).first()
    if owns_game:
        flash("You already own this game — no need to wishlist it.", "info")
        return redirect(request.referrer or url_for("games.wishlist"))

    existing = Wishlist.query.filter_by(game_id=game_id, person_id=current_user.id).first()
    if existing:
        success, message = games_services.modify_wishlist(current_user.id, game_id, remove=True)
    else:
        success, message = games_services.modify_wishlist(current_user.id, game_id, add=True)

    flash(message, "success" if success else "error")
    return redirect(request.referrer or url_for("games.wishlist"))

@games_bp.route("/game/<int:game_id>/rating", methods=["POST"])
@login_required
def update_rating(game_id):
    ranking = request.form.get("ranking", type=int)

    success, message = games_services.update_game_rating(game_id, current_user.id, ranking)

    flash(message, "success" if success else "error")
    return redirect(url_for("games.view_game", game_id=game_id))

@games_bp.route("/games/<int:game_id>/update_tutorial", methods=["POST"])
@login_required
@admin_required
def update_tutorial_url(game_id):
    tutorial_url = request.form.get("tutorial_url", "").strip()

    games_services.update_tutorial_url(game_id, tutorial_url)
    flash("Tutorial URL updated.", "success")

    return redirect(url_for("games.view_game", game_id=game_id))