# utils/decorators.py
from functools import wraps

from flask import flash, redirect, request, url_for
from flask_login import current_user


def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not (current_user.admin or current_user.owner):
            flash("Access denied. Admins only.", "error")
            return redirect(url_for("main.index"))
        return f(*args, **kwargs)

    return decorated_function


def game_night_access_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from app.models import Player  # Import inside to avoid circular imports

        game_night_id = kwargs.get("game_night_id")
        if game_night_id is None:
            flash("Game night ID is required.", "error")
            return redirect(url_for("main.index"))

        is_participant = Player.query.filter_by(
            game_night_id=game_night_id, people_id=current_user.id
        ).first()

        if not is_participant and not (current_user.admin or current_user.owner):
            flash("Access denied. You are not part of this game night.", "error")
            return redirect(url_for("main.index"))

        return f(*args, **kwargs)

    return decorated_function


def flash_if_no_action(message="No data provided.", category="error"):
    """Decorator to check if a request contains form data, and flash a message if it does not."""

    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if request.method == "POST" and not request.form:
                flash(message, category)
                return redirect(request.referrer or url_for("main.index"))
            return f(*args, **kwargs)

        return decorated_function

    return decorator
