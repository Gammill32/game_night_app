# app/services/game_night_service.py
from app.models import db
from sqlalchemy import text
from datetime import date, timedelta
import calendar

def get_game_nights(user, start_date, end_date):
    """Fetches game nights based on user role using SQL views."""
    if user.owner:
        query = """
            SELECT game_night_id, date
            FROM admin_game_nights_list
            WHERE date BETWEEN :start_date AND :end_date
            ORDER BY date ASC
        """
        return db.session.execute(text(query), {"start_date": start_date, "end_date": end_date}).mappings().all()
    else:
        query = """
            SELECT game_night_id, date 
            FROM user_game_nights_list
            WHERE user_id = :user_id
            AND date BETWEEN :start_date AND :end_date
            ORDER BY date ASC
        """
        return db.session.execute(
            text(query), 
            {"user_id": user.id, "start_date": start_date, "end_date": end_date}
        ).mappings().all()

def get_all_game_nights(user):
    """Fetches all game nights based on the user's role."""
    with db.session.begin():
        if user.owner:
            query = """
                SELECT game_night_id, date 
                FROM admin_game_nights_list
                ORDER BY date DESC
            """
            return db.session.execute(text(query)).mappings().all()
        else:
            query = """
                SELECT game_night_id, date 
                FROM user_game_nights_list
                WHERE user_id = :user_id
                ORDER BY date DESC
            """
            return db.session.execute(text(query), {"user_id": user.id}).mappings().all()
        
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