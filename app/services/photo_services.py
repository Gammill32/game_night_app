"""Photos on the game night page (ported from Poker Night).

The night's players (and admins) can upload photos with an optional caption.
Uploads go through media_services: JPEG, PNG or HEIC in, a cleaned JPEG out
(EXIF, including GPS, stripped) plus a thumbnail, stored under MEDIA_DIR —
never in the database. Only people who can see the night can view them. The
uploader or an admin can delete a photo.
"""

from app.extensions import db
from app.models import GameNightPhoto, Player
from app.services import media_services

FULL_SIDE = 2400
THUMB_SIDE = 480


def is_player(game_night, user):
    return (
        Player.query.filter_by(game_night_id=game_night.id, people_id=user.id).first() is not None
    )


def can_upload(game_night, user):
    return user.is_admin_or_owner or is_player(game_night, user)


def can_delete(photo, user):
    return photo.uploader_id == user.id or user.is_admin_or_owner


def upload(game_night, user, file_storage, caption=""):
    if not can_upload(game_night, user):
        return False, "Only players at this game night can add photos."
    try:
        rel, thumb = media_services.save_image(
            file_storage, f"photos/{game_night.id}", FULL_SIDE, THUMB_SIDE
        )
    except media_services.MediaError as e:
        return False, str(e)
    db.session.add(
        GameNightPhoto(
            game_night_id=game_night.id,
            uploader_id=user.id,
            path=rel,
            thumb_path=thumb,
            caption=(caption or "").strip()[:200] or None,
        )
    )
    db.session.commit()
    return True, "Photo added."


def delete(photo, user):
    if not can_delete(photo, user):
        return False, "Only whoever uploaded it or an admin can delete a photo."
    media_services.delete(photo.path, photo.thumb_path)
    db.session.delete(photo)
    db.session.commit()
    return True, "Photo deleted."


def files_for_night(game_night):
    """Every uploaded file belonging to a night, for cleanup when it's deleted."""
    return [f for photo in game_night.photos for f in (photo.path, photo.thumb_path)]
