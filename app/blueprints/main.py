# blueprints/main.py

import calendar
from datetime import date, datetime

import pytz
from flask import Blueprint, current_app, render_template, request
from flask_login import current_user, login_required

from app.services import index_services

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
@login_required
def index():
    """Homepage with a calendar of game nights using SQL views."""

    # Define Central Time Zone
    central_timezone = pytz.timezone(current_app.config["APP_TIMEZONE"])
    today_central = datetime.now(central_timezone).date()

    # Get year and month from query parameters or default to current date
    year = request.args.get("year", type=int, default=today_central.year)
    month = request.args.get("month", type=int, default=today_central.month)

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

    # Open polls the user can see, split by whether they've answered
    from app.services import poll_services

    open_polls = [
        poll_services.view_context(poll, current_user.id)
        for poll in poll_services.open_polls_for(current_user)
    ]

    # Create context dictionary
    context = {
        "game_nights": game_nights,
        "upcoming": index_services.get_upcoming_nights(current_user, today_central),
        "recent": index_services.get_recent_nights(current_user, today_central),
        "polls_to_answer": [c for c in open_polls if not c["user_votes"]],
        "polls_answered": [c for c in open_polls if c["user_votes"]],
        "calendar": index_services.get_calendar_data(year, month),
        "current_month": start_date,
        "prev_month": prev_month,
        "next_month": next_month,
        "today": today_central,
        "months": months,
        "years": years,
    }
    return render_template("index.html", **context)


@main_bp.route("/game_nights/all")
@login_required
def all_game_nights():
    """Displays all game nights based on user role."""
    game_nights = index_services.get_game_nights(current_user)

    # Create context dictionary
    context = {"game_nights": game_nights}
    return render_template("all_game_nights.html", **context)
