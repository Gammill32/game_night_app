# blueprints/main.py

from flask import Blueprint, render_template, request, current_app
from flask_login import login_required, current_user
from app.models import db, GameNight, Player
from datetime import datetime, date, timedelta
import calendar
import pytz
from sqlalchemy import func, text

main_bp = Blueprint("main", __name__)

@main_bp.route("/")
@login_required
def index():
    #test 1
    """Homepage with a calendar of game nights using SQL views."""
    
    # Define Central Time Zone
    central_timezone = pytz.timezone("America/Chicago")
    today_central = datetime.now(central_timezone).date()

    # Get year and month from query parameters or default to current date
    year = request.args.get('year', type=int, default=today_central.year)
    month = request.args.get('month', type=int, default=today_central.month)

    # Generate the calendar for the specified month
    cal = calendar.Calendar(firstweekday=6)  # Start on Sunday
    month_days = cal.monthdayscalendar(year, month)

    # Define start and end dates for the month
    start_date = date(year, month, 1)
    end_date = start_date + timedelta(days=calendar.monthrange(year, month)[1] - 1)

    # Fetch game nights based on user role using SQL views
    if current_user.owner or current_user.admin:
        # Owners and admins see all game nights
        query = """
            SELECT game_night_id, date, notes, final, closed 
            FROM public.game_nights_list
            WHERE date BETWEEN :start_date AND :end_date
            ORDER BY date ASC
        """
        game_nights = db.session.execute(text(query), {"start_date": start_date, "end_date": end_date}).mappings().all()
    else:
        # Regular users see only their game nights
        query = """
            SELECT game_night_id, date, notes, final, closed 
            FROM public.game_nights_list
            WHERE user_id = :user_id
            AND date BETWEEN :start_date AND :end_date
            ORDER BY date ASC
        """
        game_nights = db.session.execute(
            text(query), 
            {"user_id": current_user.id, "start_date": start_date, "end_date": end_date}
        ).mappings().all()

    # Get the earliest game night date from the view
    earliest_game_night = db.session.scalar(text("SELECT earliest_date FROM public.earliest_game_night"))
    earliest_year = earliest_game_night.year if earliest_game_night else today_central.year

    # Calculate previous and next months
    prev_month = (start_date.replace(day=1) - timedelta(days=1)).replace(day=1)
    if earliest_game_night and prev_month < earliest_game_night.replace(day=1):
        prev_month = None  # Disable navigation before the earliest game night

    next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)

    # Generate dropdown options
    months = [(i, calendar.month_name[i]) for i in range(1, 13)]
    years = list(range(earliest_year, today_central.year + 11))

    # Fetch recent and future game nights using the optimized view
    if current_user.owner or current_user.admin:
        query = "SELECT game_night_id, date, notes, final, closed FROM admin_recent_future_game_nights"
        all_game_nights = db.session.execute(text(query)).fetchall()
    else:
        query = """
            SELECT game_night_id, date, notes, final, closed, user_id FROM user_recent_future_game_nights
            WHERE user_id = :user_id
        """
        all_game_nights = db.session.execute(text(query), {"user_id": current_user.id}).mappings().all()

    # Create context dictionary
    context = {
        "game_nights": game_nights,
        "game_nights_list": all_game_nights,  # Pass the optimized list
        "calendar": month_days,
        "current_month": start_date,
        "prev_month": prev_month,
        "next_month": next_month,
        "today": today_central,
        "months": months,
        "years": years
    }

    return render_template('index.html', **context)

@main_bp.route("/game_nights/all")
@login_required
def all_game_nights():
    """Displays all game nights based on user role."""
    with db.session.begin():
        if current_user.owner:
            # Owners see all game nights
            game_nights = GameNight.query.order_by(GameNight.date.asc()).all()
        else:
            # Regular users and admins see only game nights they are part of
            game_nights = GameNight.query.join(Player).filter(
                Player.people_id == current_user.id
            ).order_by(GameNight.date.asc()).all()

    return render_template('all_game_nights.html', game_nights=game_nights)

@main_bp.route("/db_test")
def db_test():
    try:
        game_night_count = GameNight.query.count()  # No need for app context
        return {"status": "ok", "game_night_count": game_night_count}, 200
    except Exception as e:
        return {"status": "error", "message": str(e)}, 500
