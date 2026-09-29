# blueprints/games.py

from datetime import date

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import Game, OwnedBy
from app.services import badge_services, games_services
from app.services.bgg_service import BGGService
from app.utils import admin_required

games_bp = Blueprint("games", __name__)


@games_bp.route("/games", methods=["GET"], strict_slashes=False)
@login_required
def games_index():
    scope = request.args.get("scope", "all")
    if scope not in ("all", "mine", "unowned"):
        scope = "all"
    if scope == "unowned" and not current_user.is_admin_or_owner:
        scope = "all"
    context = {
        "games": games_services.get_filtered_games(current_user.id, scope=scope),
        "play_stats": games_services.get_play_stats(),
        "bridesmaid_games": games_services.get_bridesmaid_games(),
        "today": date.today(),
        "scope": scope,
    }
    return render_template("games_index.html", **context)


@games_bp.route("/game/add", methods=["GET", "POST"])
@login_required
def add_game():
    if request.method == "POST":
        form = request.form
        success, message, game = games_services.add_game(
            current_user.id,
            form.get("name", "").strip(),
            form.get("bgg_id", "").strip(),
            form.get("game_id", "").strip(),
        )
        flash(message, "success" if success else "error")
        if game is not None:
            return redirect(url_for("games.view_game", game_id=game.id))
        return redirect(url_for("games.add_game"))
    return render_template("add_game.html")


@games_bp.route("/game/<int:game_id>")
@login_required
def view_game(game_id):
    from app.models import Person

    context = games_services.get_game_details(game_id, current_user.id)
    game = context["game"]
    assignable_owners = []
    if current_user.is_admin_or_owner:
        owned_ids = {ob.person_id for ob in game.owners}
        assignable_owners = [
            p
            for p in Person.query.filter_by(active=True)
            .order_by(Person.first_name, Person.last_name)
            .all()
            if p.id not in owned_ids
        ]
    context.update(
        game_stat=games_services.get_play_stats().get(game_id),
        today=date.today(),
        assignable_owners=assignable_owners,
    )
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


@games_bp.route("/game/<int:game_id>/admin_ownership", methods=["POST"])
@login_required
@admin_required
def admin_modify_ownership(game_id):
    person_id = request.form.get("person_id", type=int)
    action = request.form.get("action", "add")
    if person_id is None:
        flash("Select a person.", "error")
        return redirect(url_for("games.view_game", game_id=game_id))
    success, message = games_services.modify_ownership(
        person_id, game_id, add=(action == "add"), actor_is_self=False
    )
    flash(message, "success" if success else "error")
    return redirect(url_for("games.view_game", game_id=game_id))


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
        form = request.form
        success, message, game = games_services.add_game_to_wishlist(
            current_user.id,
            form.get("name", "").strip(),
            form.get("bgg_id", "").strip(),
            form.get("game_id", "").strip(),
        )
        flash(message, "success" if success else "error")
        if success:
            return redirect(url_for("games.my_wishlist"))
        return redirect(url_for("games.add_to_wishlist"))
    return render_template("add_to_wishlist.html")


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
    return redirect(
        url_for("games.my_wishlist" if request.form.get("next") == "mine" else "games.wishlist")
    )


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
    game_ids = request.args.getlist("game_ids", type=int)
    opponent_ids = request.args.getlist("opponent_ids", type=int)
    start_date = request.args.get("start_date", "")
    end_date = request.args.get("end_date", "")
    sort_by = request.args.get("sort_by", "wins")
    sort_order = request.args.get("sort_order", "desc")
    user_id = current_user.id

    stats = games_services.get_user_stats(
        user_id=user_id,
        game_ids=game_ids,
        opponent_ids=opponent_ids,
        start_date=start_date,
        end_date=end_date,
        sort_by=sort_by,
        sort_order=sort_order,
    )
    # Choices for the filter chips: everyone you've played with / every game
    # you've played, all time, most first.
    all_games = games_services.get_user_stats(user_id, sort_by="games_played")
    all_opponents = games_services.get_head_to_head(user_id)

    today = date.today()
    presets = [
        ("All time", "", ""),
        ("This year", date(today.year, 1, 1).isoformat(), ""),
        ("Last 12 months", date(today.year - 1, today.month, 1).isoformat(), ""),
        (
            "Last year",
            date(today.year - 1, 1, 1).isoformat(),
            date(today.year - 1, 12, 31).isoformat(),
        ),
    ]

    return render_template(
        "user_stats.html",
        stats=stats,
        sort_by=sort_by,
        sort_order=sort_order,
        start_date=start_date,
        end_date=end_date,
        presets=presets,
        custom_dates=(start_date, end_date) not in [(ps, pe) for _, ps, pe in presets],
        selected_game_ids=game_ids,
        selected_opponent_ids=opponent_ids,
        game_choices=[
            {"id": g.game_id, "name": g.game_name, "count": g.games_played} for g in all_games
        ],
        opponent_choices=[
            {"id": o["person_id"], "name": o["name"], "count": o["games"]} for o in all_opponents
        ],
        head_to_head=games_services.get_head_to_head(user_id, game_ids, start_date, end_date),
        badges=badge_services.get_person_badges(user_id),
        badge_count=badge_services.total_badges(),
        earned_on=badge_services.earned_on,
        summary=games_services.summarize_user_stats(stats),
    )


@games_bp.route("/badges")
@login_required
def badges():
    return render_template(
        "badges.html",
        rows=badge_services.catalog(current_user.id),
        earned_on=badge_services.earned_on,
    )


@games_bp.route("/games/bgg-search")
@login_required
def bgg_search():
    """HTMX: the find-a-game widget (search results, a chosen game, or reset)."""
    args = request.args
    mode = "wish" if args.get("mode") == "wish" else "own"
    if args.get("select") or args.get("select_game"):
        return render_template(
            "_bgg_selected.html",
            bgg_id=args.get("select", ""),
            game_id=args.get("select_game", ""),
            name=args.get("name", ""),
            year=args.get("year", ""),
            image=args.get("image", ""),
            mode=mode,
        )
    if args.get("reset"):
        return render_template("_bgg_widget_blank.html", mode=mode)
    query = args.get("q", "").strip()
    if len(query) < 2:
        return ""
    found = games_services.search_for_adding(query, current_user.id)
    return render_template("_bgg_results.html", query=query, mode=mode, **found)


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
