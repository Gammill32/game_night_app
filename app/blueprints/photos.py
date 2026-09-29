# blueprints/photos.py
"""Game night photos: upload, view (the night's players and admins), delete."""

from flask import Blueprint, abort, flash, redirect, request, send_file, url_for
from flask_login import current_user, login_required

from app.extensions import db
from app.models import GameNight, GameNightPhoto
from app.services import media_services, photo_services
from app.utils import game_night_access_required

photos_bp = Blueprint("photos", __name__, url_prefix="/game_night/<int:game_night_id>/photos")


def _photo(game_night_id, photo_id):
    photo = db.session.get(GameNightPhoto, photo_id)
    if photo is None or photo.game_night_id != game_night_id:
        abort(404)
    return photo


def _back(game_night_id):
    return redirect(url_for("game_night.view_game_night", game_night_id=game_night_id) + "#photos")


@photos_bp.route("", methods=["POST"])
@login_required
@game_night_access_required
def upload(game_night_id):
    game_night = db.get_or_404(GameNight, game_night_id)
    success, message = photo_services.upload(
        game_night, current_user, request.files.get("photo"), request.form.get("caption")
    )
    flash(message, "success" if success else "error")
    return _back(game_night_id)


@photos_bp.route("/<int:photo_id>/<any(full, thumb):size>")
@login_required
@game_night_access_required
def image(game_night_id, photo_id, size):
    photo = _photo(game_night_id, photo_id)
    path = media_services.path_for(photo.path if size == "full" else photo.thumb_path)
    if path is None:
        abort(404)
    response = send_file(path, mimetype="image/jpeg", max_age=86400)
    response.headers["Cache-Control"] = "private, max-age=86400"
    return response


@photos_bp.route("/<int:photo_id>/delete", methods=["POST"])
@login_required
@game_night_access_required
def delete(game_night_id, photo_id):
    success, message = photo_services.delete(_photo(game_night_id, photo_id), current_user)
    flash(message, "success" if success else "error")
    return _back(game_night_id)
