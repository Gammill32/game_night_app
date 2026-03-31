# app/services/game_night_service.py
import calendar
from datetime import timedelta

from sqlalchemy import text

from app.models import (
    AdminGameNightList,
    AdminRecentFutureGameNight,
    UserGameNightList,
    UserRecentFutureGameNight,
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


def get_recent_and_future_game_nights(user):
    """Fetches recent and future game nights."""
    if user.owner:
        return AdminRecentFutureGameNight.query.order_by(
            AdminRecentFutureGameNight.date.desc()
        ).all()
    else:
        return (
            UserRecentFutureGameNight.query.filter_by(user_id=user.id)
            .order_by(UserRecentFutureGameNight.date.desc())
            .all()
        )


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
