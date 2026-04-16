# blueprints/games.py

from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Game, OwnedBy
from app.services import badge_services, games_services, index_services
from app.services.bgg_service import BGGService
from app.utils import admin_required

games_bp = Blueprint("games", __name__)


@games_bp.route("/games", methods=["GET"], strict_slashes=False)
@login_required
def games_index():
    name_filter = request.args.get("name", "").strip()
    players_filter = (
        request.args.get("players", type=int) if request.args.get("players_enabled") else None
    )
    playtime_filter = (
        request.args.get("playtime", type=int) if request.args.get("playtime_enabled") else None
    )
    min_rating_filter = (
        request.args.get("min_rating", type=int) if request.args.get("min_rating_enabled") else None
    )

    games_with_ownership = games_services.get_filtered_games(
        current_user.id, name_filter, players_filter, playtime_filter, min_rating_filter
    )
    play_stats = games_services.get_play_stats()
    bridesmaid_games = games_services.get_bridesmaid_games()
    recently_played = games_services.get_recently_played_games()

    context = {
        "games": games_with_ownership,
        "play_stats": play_stats,
        "bridesmaid_games": bridesmaid_games,
        "recently_played": recently_played,
        "today": date.today(),
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
    game, leaderboard, game_nights, user_rating = games_services.get_game_details(
        game_id, current_user.id
    )
    play_stats = games_services.get_play_stats()
    game_stat = play_stats.get(game_id)

    context = {
        "game": game,
        "leaderboard": leaderboard,
        "game_nights": game_nights,
        "user_rating": user_rating,
        "game_stat": game_stat,
        "today": date.today(),
    }
    return render_template("view_game.html", **context)


@games_bp.route("/game/<int:game_id>/claim", methods=["POST"])
@login_required
def claim_game(game_id):
    success, message = games_services.modify_ownership(current_user.id, game_id, add=True)
    flash(message, "success" if success else "error")
    return redirect(request.referrer or url_for("games.games_index"))


@games_bp.route("/game/<int:game_id>/remove_ownership", methods=["POST"])
@login_required
def remove_ownership(game_id):
    success, message = games_services.modify_ownership(current_user.id, game_id, add=False)
    flash(message, "success" if success else "error")
    return redirect(request.referrer or url_for("games.games_index"))


@games_bp.route("/collection", methods=["GET"])
@login_required
def collection():
    items = games_services.get_group_collection()
    user_owned = {item["game"].id for item in items if current_user.id in item["owner_ids"]}
    return render_template("collection.html", items=items, user_owned=user_owned)


@games_bp.route("/collection/mine", methods=["GET"])
@login_required
def my_collection():
    games = games_services.get_my_collection(current_user.id)
    return render_template("my_collection.html", games=games)


@games_bp.route("/wishlist", methods=["GET"])
@login_required
def wishlist():
    items = games_services.get_group_wishlist(current_user.id)
    return render_template("wishlist.html", items=items)


@games_bp.route("/wishlist/mine", methods=["GET"])
@login_required
def my_wishlist():
    wishlist_games = games_services.get_wishlist(current_user.id)
    return render_template("my_wishlist.html", games=wishlist_games)


@games_bp.route("/wishlist/add", methods=["GET", "POST"])
@login_required
def add_to_wishlist():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        bgg_id = request.form.get("bgg_id", "").strip()

        success, message = games_services.add_game_to_wishlist(current_user.id, name, bgg_id)
        flash(message, "success" if success else "error")

        return redirect(url_for("games.my_wishlist"))

    context = {}
    return render_template("add_to_wishlist.html", **context)


@games_bp.route("/wishlist/remove/<int:game_id>", methods=["POST"])
@login_required
def remove_from_wishlist(game_id):
    success, message = games_services.modify_wishlist(current_user.id, game_id, remove=True)
    flash(message, "success" if success else "error")
    return redirect(url_for("games.my_wishlist"))


@games_bp.route("/wishlist/vote/<int:game_id>", methods=["POST"])
@login_required
def vote_wishlist(game_id):
    success, message = games_services.toggle_wishlist_vote(current_user.id, game_id)
    flash(message, "success" if success else "info")
    return redirect(url_for("games.wishlist"))


@games_bp.route("/wishlist/toggle/<int:game_id>", methods=["POST"])
@login_required
def toggle_wishlist(game_id):
    from app.models import Wishlist

    # If already owned, prevent wishlisting
    owns_game = OwnedBy.query.filter_by(game_id=game_id, person_id=current_user.id).first()
    if owns_game:
        flash("You already own this game — no need to wishlist it.", "info")
        return redirect(request.referrer or url_for("games.my_wishlist"))

    existing = Wishlist.query.filter_by(game_id=game_id, person_id=current_user.id).first()
    if existing:
        success, message = games_services.modify_wishlist(current_user.id, game_id, remove=True)
    else:
        success, message = games_services.modify_wishlist(current_user.id, game_id, add=True)

    flash(message, "success" if success else "error")
    return redirect(request.referrer or url_for("games.my_wishlist"))


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


@games_bp.route("/user_stats", methods=["GET"])
@login_required
def user_stats():
    # Retrieve filter parameters from the request
    game_ids = request.args.getlist("game_ids", type=int)
    opponent_ids = request.args.getlist("opponent_ids", type=int)
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")
    sort_by = request.args.get("sort_by", "wins")
    sort_order = request.args.get("sort_order", "desc")

    # Default date range
    if not start_date:
        earliest = index_services.get_earliest_game_night()
        start_date = earliest.isoformat() if earliest else ""

    if not end_date:
        end_date = date.today().isoformat()

    # Fetch filtered user stats
    stats = games_services.get_user_stats(
        user_id=current_user.id,
        game_ids=game_ids,
        opponent_ids=opponent_ids,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    # Get selected game and opponent display names for tags
    selected_games = games_services.get_selected_games(game_ids)
    selected_opponents_raw = games_services.get_selected_opponents(opponent_ids)
    selected_opponents = [
        {"id": p.id, "name": f"{p.first_name} {p.last_name}"} for p in selected_opponents_raw
    ]

    return render_template(
        "user_stats.html",
        stats=stats,
        sort_by=sort_by,
        sort_order=sort_order,
        start_date=start_date,
        end_date=end_date,
        selected_game_ids=game_ids,
        selected_opponent_ids=opponent_ids,
        selected_game_names=selected_games,
        selected_opponent_names=selected_opponents,
        badges=badge_services.get_person_badges(current_user.id),
    )


@games_bp.route("/games/bgg-search")
@login_required
def bgg_search():
    query = request.args.get("q", "").strip()
    if request.args.get("select"):
        return render_template(
            "_bgg_selected.html",
            bgg_id=request.args.get("select", ""),
            name=request.args.get("name", ""),
            year=request.args.get("year", ""),
            thumbnail=request.args.get("thumbnail", ""),
        )
    if request.args.get("reset"):
        return render_template("_bgg_widget_blank.html")
    if len(query) < 3:
        return ""
    results = BGGService.search(query)
    return render_template("_bgg_results.html", results=results, query=query)


@games_bp.route("/games/<int:game_id>/bgg-details")
@login_required
def bgg_details(game_id: int):
    """HTMX endpoint: fetch BGG enrichment data for a game and return fragment."""
    game = db.session.get(Game, game_id)
    if game is None:
        return render_template("_bgg_error.html", message="Game not found."), 404
    if not game.bgg_id:
        return render_template("_bgg_error.html", message="No BGG data available for this game.")
    details = BGGService.fetch_details(game.bgg_id)
    if not details:
        return render_template("_bgg_error.html", message="Could not reach BoardGameGeek.")
    return render_template("_bgg_details.html", details=details)
