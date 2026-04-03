# blueprints/auth.py

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func

from app.extensions import db
from app.models import Game, GameNightGame, Player, Result
from app.services import auth_services
from app.utils import flash_if_no_action

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password")

        success, message, user = auth_services.login(email, password)

        if success:
            login_user(user)
            if user.temp_pass:
                flash("Please update your password.", "warning")
                return redirect(url_for("auth.update_password"))
            next_url = request.args.get("next") or ""
            if next_url and (not next_url.startswith("/") or next_url.startswith("//")):
                next_url = ""
            return redirect(next_url or url_for("main.index"))
        else:
            flash(message, "error")

    context = {}
    return render_template("login.html", **context)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/signup", methods=["GET", "POST"])
@flash_if_no_action("Please provide all required fields to sign up.", "error")
def signup():
    if request.method == "POST":
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password")

        success, message = auth_services.signup(first_name, last_name, email, password)
        flash(message, "success" if success else "error")

        if success:
            return redirect(url_for("auth.login"))

    context = {}
    return render_template("signup.html", **context)


@auth_bp.route("/forgot_password", methods=["GET", "POST"])
@flash_if_no_action("Please enter your email address to reset your password.", "error")
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        success, message = auth_services.forgot_password(email)
        flash(message, "success" if success else "error")

        if success:
            return redirect(url_for("auth.login"))

    context = {}
    return render_template("forgot_password.html", **context)


@auth_bp.route("/update_password", methods=["GET", "POST"])
@login_required
def update_password():
    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        success, message = auth_services.update_password(
            current_user, current_password, new_password, confirm_password
        )
        flash(message, "success" if success else "error")

        if success:
            return redirect(url_for("main.index"))

    context = {}
    return render_template("update_password.html", **context)


@auth_bp.route("/manage_user", methods=["GET", "POST"])
@login_required
def manage_user():
    """Displays user profile and game stats."""
    user = current_user

    games_played = (
        db.session.query(func.count(Result.id))
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .join(Player, Result.player_id == Player.id)
        .filter(Player.people_id == user.id)
        .scalar()
        or 0
    )

    total_wins = (
        db.session.query(func.count(Result.id))
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .join(Player, Result.player_id == Player.id)
        .filter(Player.people_id == user.id, Result.position == 1)
        .scalar()
        or 0
    )

    win_percentage = round((total_wins / games_played * 100) if games_played > 0 else 0, 2)

    def get_game_stats(game_id):
        """Fetch win percentage, total wins, and average finish for a game."""
        total_wins = (
            db.session.query(func.count(Result.id))
            .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
            .join(Player, Result.player_id == Player.id)
            .filter(
                Player.people_id == user.id, GameNightGame.game_id == game_id, Result.position == 1
            )
            .scalar()
        )
        total_played = (
            db.session.query(func.count(Result.id))
            .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
            .join(Player, Result.player_id == Player.id)
            .filter(Player.people_id == user.id, GameNightGame.game_id == game_id)
            .scalar()
        )
        avg_finish = (
            db.session.query(func.avg(Result.position))
            .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
            .join(Player, Result.player_id == Player.id)
            .filter(Player.people_id == user.id, GameNightGame.game_id == game_id)
            .scalar()
        )

        win_percentage = round((total_wins / total_played * 100) if total_played > 0 else 0, 2)
        avg_finish = round(avg_finish, 2) if avg_finish else None

        return total_wins, win_percentage, avg_finish

    most_played_game_query = (
        db.session.query(Game, func.count(Result.id).label("play_count"))
        .join(GameNightGame, GameNightGame.game_id == Game.id)
        .join(Result, Result.game_night_game_id == GameNightGame.id)
        .join(Player, Result.player_id == Player.id)
        .filter(Player.people_id == user.id)
        .group_by(Game.id)
        .order_by(func.count(Result.id).desc())
        .first()
    )

    most_played_game = most_played_game_query[0] if most_played_game_query else None
    most_played_stats = get_game_stats(most_played_game.id) if most_played_game else (0, 0, None)

    most_wins_game_query = (
        db.session.query(Game, func.count(Result.id).label("win_count"))
        .join(GameNightGame, GameNightGame.game_id == Game.id)
        .join(Result, Result.game_night_game_id == GameNightGame.id)
        .join(Player, Result.player_id == Player.id)
        .filter(Player.people_id == user.id, Result.position == 1)
        .group_by(Game.id)
        .order_by(func.count(Result.id).desc())
        .first()
    )

    most_wins_game = most_wins_game_query[0] if most_wins_game_query else None
    most_wins_stats = get_game_stats(most_wins_game.id) if most_wins_game else (0, 0, None)

    stats = {
        "games_played": games_played,
        "wins": total_wins,
        "win_percentage": win_percentage,
        "most_played_game": most_played_game,
        "most_played_stats": most_played_stats,
        "most_wins_game": most_wins_game,
        "most_wins_stats": most_wins_stats,
    }

    context = {"person": user, "stats": stats}
    return render_template("manage_user.html", **context)
