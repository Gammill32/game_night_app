# app/services/game_night_service.py
import calendar
from datetime import timedelta

from sqlalchemy import text

from app.models import (
    AdminGameNightList,
    GameNight,
    Player,
    UserGameNightList,
    db,
)


def get_game_nights(user, start_date=None, end_date=None):
    """Fetches game nights based on user role, optionally filtering by date range."""

    # Select the appropriate model
    GameNightModel = AdminGameNightList if user.owner else UserGameNightList

    # Start the query
    query = GameNightModel.query

    # Filter by user ID if needed
    if not user.owner:
        query = query.filter_by(user_id=user.id)

    # Apply date filtering if provided
    if start_date and end_date:
        query = query.filter(GameNightModel.date.between(start_date, end_date))

    # Order results
    query = query.order_by(GameNightModel.date.asc() if start_date else GameNightModel.date.desc())

    return query.all()


def get_earliest_game_night():
    """Retrieves the earliest game night date."""
    return db.session.scalar(text("SELECT earliest_date FROM public.earliest_game_night"))


def get_calendar_data(year, month):
    """Generates calendar data for the given month."""
    cal = calendar.Calendar(firstweekday=6)  # Start on Sunday
    return cal.monthdayscalendar(year, month)


def get_navigation_dates(start_date, earliest_game_night):
    """Computes previous and next month navigation."""
    prev_month = (start_date.replace(day=1) - timedelta(days=1)).replace(day=1)
    if earliest_game_night and prev_month < earliest_game_night.replace(day=1):
        prev_month = None  # Disable navigation before the earliest game night

    next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
    return prev_month, next_month


def _visible_nights(user):
    """Owners see every night; everyone else sees the nights they're in."""
    query = GameNight.query
    if not user.owner:
        query = query.join(Player, Player.game_night_id == GameNight.id).filter(
            Player.people_id == user.id
        )
    return query


def get_upcoming_nights(user, today, limit=6):
    """Upcoming nights with what the viewer needs at a glance."""
    from app.services import food_services, poll_services

    nights = (
        _visible_nights(user)
        .filter(GameNight.date >= today)
        .order_by(GameNight.date.asc())
        .limit(limit)
        .all()
    )
    cards = []
    for night in nights:
        player_ids = [p.people_id for p in night.players]
        rsvps = poll_services.rsvps_for_night(night)
        answers = [rsvps.get(pid) for pid in player_ids]
        cards.append(
            {
                "night": night,
                "is_player": user.id in player_ids,
                "player_count": len(player_ids),
                "my_rsvp": rsvps.get(user.id),
                "has_rsvp_poll": night.availability_poll is not None,
                "rsvp_in": answers.count("Can Make It"),
                "rsvp_maybe": answers.count("Maybe"),
                "rsvp_none": answers.count(None),
                "bringing": [i.name for i in night.food_items if i.claimed_by == user.id],
                "owed": food_services.my_food_summary(night, user),
                "days_away": (night.date - today).days,
                "next_step": _next_voting_step(night, user.id),
            }
        )
    return cards


def _next_voting_step(night, user_id):
    """'nominate' / 'rank' while voting is open and the player hasn't yet."""
    from app.models import GameNominations, GameVotes

    if night.closed or night.final:
        return None
    me = next((p for p in night.players if p.people_id == user_id), None)
    if me is None:
        return None
    if not GameNominations.query.filter_by(game_night_id=night.id, player_id=me.id).first():
        return "nominate"
    if not GameVotes.query.filter_by(game_night_id=night.id, player_id=me.id).first():
        return "rank"
    return None


def get_recent_nights(user, today, limit=5):
    return (
        _visible_nights(user)
        .filter(GameNight.date < today)
        .order_by(GameNight.date.desc())
        .limit(limit)
        .all()
    )


def get_all_night_cards(user):
    """Every night the user can see, newest first, with counts and the winner."""
    from sqlalchemy import func

    from app.models import GameNightGame, GameNightRankings, Person

    nights = _visible_nights(user).order_by(GameNight.date.desc()).all()
    ids = [n.id for n in nights]
    players = dict(
        db.session.query(Player.game_night_id, func.count(Player.id))
        .filter(Player.game_night_id.in_(ids))
        .group_by(Player.game_night_id)
        .all()
    )
    games = dict(
        db.session.query(GameNightGame.game_night_id, func.count(GameNightGame.id))
        .filter(GameNightGame.game_night_id.in_(ids))
        .group_by(GameNightGame.game_night_id)
        .all()
    )
    winners: dict[int, list[str]] = {}
    for night_id, first_name in (
        db.session.query(GameNightRankings.game_night_id, Person.first_name)
        .join(Player, Player.id == GameNightRankings.player_id)
        .join(Person, Person.id == Player.people_id)
        .filter(GameNightRankings.game_night_id.in_(ids), GameNightRankings.rank == 1)
    ):
        winners.setdefault(night_id, []).append(first_name)
    return [
        {
            "night": n,
            "players": players.get(n.id, 0),
            "games": games.get(n.id, 0),
            "winners": winners.get(n.id, []) if n.final else [],
        }
        for n in nights
    ]
