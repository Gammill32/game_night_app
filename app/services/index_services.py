# app/services/game_night_service.py
from app.models import db
from sqlalchemy import text
from datetime import timedelta
import calendar

def get_game_nights(user, start_date=None, end_date=None):
    """Fetches game nights based on user role, optionally filtering by date range."""
    
    # Determine which SQL view to use
    table_name = "admin_game_nights_list" if user.owner else "user_game_nights_list"

    # Base query
    query = f"SELECT game_night_id, date FROM {table_name}"

    # Parameters dictionary
    params = {}

    # Add filtering by user ID if needed
    if not user.owner:
        query += " WHERE user_id = :user_id"
        params["user_id"] = user.id

    # Add date filtering if start_date and end_date are provided
    if start_date and end_date:
        if user.owner:
            query += " WHERE" if "WHERE" not in query else " AND"
        else:
            query += " AND"
        query += " date BETWEEN :start_date AND :end_date"
        params["start_date"] = start_date
        params["end_date"] = end_date

    # Always order results
    query += " ORDER BY date DESC" if not start_date else " ORDER BY date ASC"

    return db.session.execute(text(query), params).mappings().all()
        
def get_earliest_game_night():
    """Retrieves the earliest game night date."""
    return db.session.scalar(text("SELECT earliest_date FROM public.earliest_game_night"))

def get_recent_and_future_game_nights(user):
    """Fetches recent and future game nights."""
    if user.owner:
        query = """
            SELECT game_night_id, date
            FROM admin_recent_future_game_nights
            """
        return db.session.execute(text(query)).fetchall()
    else:
        query = """
            SELECT game_night_id, date, user_id
            FROM user_recent_future_game_nights
            WHERE user_id = :user_id
        """
        return db.session.execute(text(query), {"user_id": user.id}).mappings().all()

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
