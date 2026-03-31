import logging
from datetime import datetime

import pytz
from apscheduler.triggers.cron import CronTrigger
from flask import render_template
from sqlalchemy import func

from app.extensions import scheduler
from app.models import Game, GameNight, GameNominations, GameVotes, Person, Player, db
from app.utils import send_email

# Define timezone globally
central = pytz.timezone("America/Chicago")


def check_and_send_reminders():
    """Checks for upcoming game nights and sends reminder emails to participants."""
    today_central = datetime.now(central).date()

    game_nights = GameNight.query.filter_by(date=today_central).all()
    if not game_nights:
        return

    for game_night in game_nights:
        leader = (
            db.session.query(
                Game,
                func.sum(
                    db.case(
                        (GameVotes.rank == 1, 3),
                        (GameVotes.rank == 2, 2),
                        (GameVotes.rank == 3, 1),
                    )
                ).label("weighted_score"),
                func.count(GameVotes.id).label("vote_count"),
            )
            .join(GameVotes, Game.id == GameVotes.game_id)
            .filter(GameVotes.game_night_id == game_night.id)
            .group_by(Game.id)
            .order_by(
                func.sum(
                    db.case(
                        (GameVotes.rank == 1, 3),
                        (GameVotes.rank == 2, 2),
                        (GameVotes.rank == 3, 1),
                    )
                ).desc()
            )
            .first()
        )

        leader_data = (
            {
                "game": leader[0] if leader else None,
                "weighted_score": leader[1] if leader else None,
                "vote_count": leader[2] if leader else 0,
            }
            if leader
            else None
        )

        players = Player.query.filter_by(game_night_id=game_night.id).all()
        for player in players:
            user = Person.query.get(player.people_id)

            has_nominated = GameNominations.query.filter_by(
                game_night_id=game_night.id, player_id=player.id
            ).first()
            has_voted = GameVotes.query.filter_by(
                game_night_id=game_night.id, player_id=player.id
            ).first()

            html_body = render_template(
                "email_templates/reminder_body.html",
                user=user,
                game_night=game_night,
                has_nominated=has_nominated,
                has_voted=has_voted,
                leader=leader_data,
            )

            try:
                send_email(user.email, "Game Night Reminder", html_body)
                logging.info(f"Reminder email sent to {user.email}")
            except Exception as e:
                logging.error(f"Failed to send reminder email to {user.email}: {e}")


def start_scheduler(app):
    """Start the background scheduler for reminders."""
    scheduler.configure(timezone=central)

    def job_with_app_context():
        with app.app_context():
            check_and_send_reminders()

    scheduler.add_job(
        func=job_with_app_context,
        trigger=CronTrigger(hour=8, minute=45, timezone=central),
        id="daily_game_night_reminder",
        replace_existing=True,
    )

    scheduler.start()
