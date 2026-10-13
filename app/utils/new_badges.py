"""Expose the signed-in person's newest badges to base.html for the "New badge!" dialog.

The template calls ``newest_badges()`` once per full page; HTMX partials never
call it, so they cost nothing. The browser compares the ids with the last one it
has shown (localStorage ``gn_badge_seen``) and opens the dialog for newer ones.
"""

from flask import url_for
from flask_login import current_user

from app.services.badge_services import newest_awards

LIMIT = 10


def newest_badges() -> list[dict]:
    if not current_user.is_authenticated:
        return []
    return [
        {
            "id": pb.id,
            "icon": pb.badge.icon,
            "name": pb.badge.name,
            "rule": pb.badge.description,
            "night_url": url_for("game_night.view_game_night", game_night_id=pb.game_night_id)
            + "#badges"
            if pb.game_night_id
            else "",
        }
        for pb in newest_awards(current_user.id, LIMIT)
    ]


def register(app) -> None:
    @app.context_processor
    def _inject_newest_badges():
        return {"newest_badges": newest_badges}
