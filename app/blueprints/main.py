# blueprints/main.py

from flask import Blueprint, render_template, request
from flask_login import login_required, current_user
from datetime import datetime, date
import calendar
import pytz
from app.services import index_services

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

    # Define start and end dates for the month
    start_date = date(year, month, 1)
    end_date = start_date.replace(day=calendar.monthrange(year, month)[1])

    # Fetch game nights
    game_nights = index_services.get_game_nights(current_user, start_date, end_date)

    # Get earliest game night
    earliest_game_night = index_services.get_earliest_game_night()
    earliest_year = earliest_game_night.year if earliest_game_night else today_central.year

    # Calculate previous and next months
    prev_month, next_month = index_services.get_navigation_dates(start_date, earliest_game_night)

    # Generate dropdown options
    months = [(i, calendar.month_name[i]) for i in range(1, 13)]
    years = list(range(earliest_year, today_central.year + 11))

    # Fetch recent and future game nights
    all_game_nights = index_services.get_recent_and_future_game_nights(current_user)

    # Create context dictionary
    context = {
        "game_nights": game_nights,
        "game_nights_list": all_game_nights,
        "calendar": index_services.get_calendar_data(year, month),
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
    game_nights = index_services.get_game_nights(current_user)

    # Create context dictionary
    context = {
        "game_nights": game_nights
    }

    return render_template('all_game_nights.html', **context)
