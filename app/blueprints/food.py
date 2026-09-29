# blueprints/food.py
"""Food on a game night: sign-up list and split costs."""

from flask import Blueprint, abort, flash, redirect, request, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import FoodExpense, FoodExpenseShare, FoodItem, GameNight
from app.services import food_services, media_services
from app.utils import game_night_access_required

food_bp = Blueprint("food", __name__, url_prefix="/game_night/<int:game_night_id>/food")


def _done(result, game_night_id):
    success, message = result
    flash(message, "success" if success else "error")
    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id) + "#food")


def _get(model, obj_id, game_night_id):
    obj = db.session.get(model, obj_id)
    if obj is None:
        abort(404)
    owner = obj.expense if isinstance(obj, FoodExpenseShare) else obj
    if owner.game_night_id != game_night_id:
        abort(404)
    return obj


@food_bp.route("/items", methods=["POST"])
@login_required
@game_night_access_required
def add_item(game_night_id):
    game_night = db.get_or_404(GameNight, game_night_id)
    result = food_services.add_item(
        game_night, current_user, request.form.get("name"), claim=request.form.get("claim") == "1"
    )
    return _done(result, game_night_id)


@food_bp.route("/items/<int:item_id>/claim", methods=["POST"])
@login_required
@game_night_access_required
def claim_item(game_night_id, item_id):
    game_night = db.get_or_404(GameNight, game_night_id)
    item = _get(FoodItem, item_id, game_night_id)
    result = food_services.claim_item(
        game_night, item, current_user, claim=request.form.get("claim", "1") == "1"
    )
    return _done(result, game_night_id)


@food_bp.route("/items/<int:item_id>/delete", methods=["POST"])
@login_required
@game_night_access_required
def delete_item(game_night_id, item_id):
    game_night = db.get_or_404(GameNight, game_night_id)
    item = _get(FoodItem, item_id, game_night_id)
    return _done(food_services.delete_item(game_night, item, current_user), game_night_id)


@food_bp.route("/expenses", methods=["POST"])
@login_required
@game_night_access_required
def add_expense(game_night_id):
    game_night = db.get_or_404(GameNight, game_night_id)
    result = food_services.add_expense(
        game_night, current_user, request.form, request.files.get("receipt")
    )
    return _done(result, game_night_id)


@food_bp.route("/expenses/<int:expense_id>/covered", methods=["POST"])
@login_required
@game_night_access_required
def covered(game_night_id, expense_id):
    game_night = db.get_or_404(GameNight, game_night_id)
    expense = _get(FoodExpense, expense_id, game_night_id)
    return _done(
        food_services.set_covered(game_night, expense, current_user, request.form), game_night_id
    )


@food_bp.route("/expenses/<int:expense_id>/delete", methods=["POST"])
@login_required
@game_night_access_required
def delete_expense(game_night_id, expense_id):
    game_night = db.get_or_404(GameNight, game_night_id)
    expense = _get(FoodExpense, expense_id, game_night_id)
    return _done(food_services.delete_expense(game_night, expense, current_user), game_night_id)


@food_bp.route("/shares/<int:share_id>/paid", methods=["POST"])
@login_required
@game_night_access_required
def share_paid(game_night_id, share_id):
    share = _get(FoodExpenseShare, share_id, game_night_id)
    result = food_services.set_paid(share, current_user, paid=request.form.get("paid", "1") == "1")
    return _done(result, game_night_id)


@food_bp.route("/expenses/<int:expense_id>/receipt")
@login_required
@game_night_access_required
def receipt(game_night_id, expense_id):
    expense = _get(FoodExpense, expense_id, game_night_id)
    path = media_services.path_for(expense.receipt_path)
    if path is None:
        abort(404)
    response = send_file(path, mimetype="image/jpeg", max_age=3600)
    response.headers["Cache-Control"] = "private, max-age=3600"
    return response
