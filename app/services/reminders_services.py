from datetime import datetime, timedelta

import pytz
from apscheduler.triggers.cron import CronTrigger
from flask import current_app, render_template, url_for

from app.extensions import db, scheduler
from app.models import GameNight, GameNominations, GameVotes, Player
from app.services import food_services
from app.utils import send_email

REMINDER_HOUR, REMINDER_MINUTE = 8, 45
# APScheduler's default misfire_grace_time is 1 second: if the scheduler
# thread wakes any later than that (busy process, clock adjustment) the run is
# logged as missed and skipped until tomorrow. An hour still sends a morning
# reminder. (It doesn't help across a restart: jobs live in memory, so a
# process that's down at 8:45 never sees that run.)
MISFIRE_GRACE_SECONDS = 60 * 60


def _get_timezone():
    tz_name = current_app.config.get("APP_TIMEZONE", "America/Chicago")
    return pytz.timezone(tz_name)


def _leader(game_night):
    """The nominated game with the most points so far, or None."""
    from app.models import GameNightNominationsVotes

    return (
        GameNightNominationsVotes.query.filter_by(game_night_id=game_night.id)
        .filter(GameNightNominationsVotes.total_nominations > 0)
        .order_by(GameNightNominationsVotes.vote_score.desc())
        .first()
    )


def check_and_send_reminders():
    """Email the players of tomorrow's and today's game nights (run once a day).

    Each step is isolated: a failure in the address cleanup or in one night is
    logged and the rest still go out."""
    from app.services import game_night_services

    tz = _get_timezone()
    today = datetime.now(tz).date()
    # Addresses are only kept until the night is over.
    try:
        game_night_services.clear_past_addresses(today)
    except Exception:
        current_app.logger.exception("Clearing past night addresses failed")
        db.session.rollback()
    base_url = current_app.config.get("APP_BASE_URL", "https://gamenight.sgammill.com")

    nights = GameNight.query.filter(
        GameNight.date.in_([today, today + timedelta(days=1)]), GameNight.final.is_(False)
    ).all()
    for game_night in nights:
        try:
            _remind_night(game_night, today, base_url)
        except Exception:
            current_app.logger.exception("Reminders for game night %s failed", game_night.id)
            db.session.rollback()


def _remind_night(game_night, today, base_url):
    from app.services import poll_services

    when = "tonight" if game_night.date == today else "tomorrow"
    rsvps = poll_services.rsvps_for_night(game_night)
    has_rsvp_poll = game_night.availability_poll is not None
    leader = _leader(game_night)
    with current_app.test_request_context(base_url=base_url):
        link = url_for("game_night.view_game_night", game_night_id=game_night.id, _external=True)

    for player in Player.query.filter_by(game_night_id=game_night.id).all():
        user = player.person
        if not user or not user.email or not user.active:
            continue
        answer = rsvps.get(user.id)
        if answer == "Can't Make It":
            continue  # they told us; don't nag
        voting_open = not game_night.closed
        html_body = render_template(
            "email_templates/reminder_body.html",
            user=user,
            game_night=game_night,
            when=when,
            link=link,
            needs_rsvp=has_rsvp_poll and answer is None,
            maybe=answer == "Maybe",
            needs_nomination=voting_open
            and not GameNominations.query.filter_by(
                game_night_id=game_night.id, player_id=player.id
            ).first(),
            needs_votes=voting_open
            and leader is not None
            and not GameVotes.query.filter_by(
                game_night_id=game_night.id, player_id=player.id
            ).first(),
            leader=leader,
            signer=game_night.host.first_name if game_night.host else None,
            food_lines=food_services.reminder_lines(game_night),
            owed=food_services.my_food_summary(game_night, user),
        )
        subject = f"Game night {when}" + (
            f" ({game_night.date.strftime('%a, %b %-d')})" if when == "tomorrow" else ""
        )
        try:
            send_email(user.email, subject, html_body)
            current_app.logger.info("Reminder email sent to %s", user.email)
        except Exception:
            current_app.logger.exception("Failed to send reminder email to %s", user.email)


def start_scheduler(app):
    """Start the background scheduler for reminders."""
    with app.app_context():
        tz = pytz.timezone(app.config.get("APP_TIMEZONE", "America/Chicago"))

    scheduler.configure(timezone=tz)

    def job_with_app_context():
        with app.app_context():
            check_and_send_reminders()

    scheduler.add_job(
        func=job_with_app_context,
        trigger=CronTrigger(hour=REMINDER_HOUR, minute=REMINDER_MINUTE, timezone=tz),
        id="daily_game_night_reminder",
        replace_existing=True,
        misfire_grace_time=MISFIRE_GRACE_SECONDS,
        coalesce=True,
        max_instances=1,
    )

    scheduler.start()
