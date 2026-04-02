from app.extensions import db
from app.models import (
    Player,
    Result,
    TrackerField,
    TrackerSession,
    TrackerTeam,
    TrackerValue,
    tracker_team_players,
)


def get_or_create_configuring_session(game_night_game_id):
    """Return the existing configuring session or create a fresh one."""
    session = TrackerSession.query.filter_by(
        game_night_game_id=game_night_game_id, status="configuring"
    ).first()
    if session:
        return session
    session = TrackerSession(
        game_night_game_id=game_night_game_id,
        mode="individual",
        status="configuring",
    )
    db.session.add(session)
    db.session.commit()
    return session


def discard_session(session_id):
    """Delete a tracker session and all its children (cascade handles FK children)."""
    session = TrackerSession.query.get(session_id)
    if session:
        db.session.delete(session)
        db.session.commit()
