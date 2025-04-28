from flask import render_template
from app.models import db, GameNight, Game, GameVotes, Player, Person, GameNominations
from datetime import datetime
import pytz
from sqlalchemy import func
from app.utils import send_email
from app.extensions import scheduler
from apscheduler.triggers.cron import CronTrigger

def check_and_send_reminders():
    """Checks for upcoming game nights and sends reminder emails to participants."""
    central_timezone = pytz.timezone("America/Chicago")
    today_central = datetime.now(central_timezone).date()

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
                ).label('weighted_score'),
                func.count(GameVotes.id).label('vote_count')
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

        leader_data = {
            'game': leader[0] if leader else None,
            'weighted_score': leader[1] if leader else None,
            'vote_count': leader[2] if leader else 0,
        } if leader else None

        players = Player.query.filter_by(game_night_id=game_night.id).all()
        for player in players:
            user = Person.query.get(player.people_id)

            has_nominated = GameNominations.query.filter_by(game_night_id=game_night.id, player_id=player.id).first()
            has_voted = GameVotes.query.filter_by(game_night_id=game_night.id, player_id=player.id).first()

            html_body = render_template(
                'email_templates/reminder_body.html',
                user=user,
                game_night=game_night,
                has_nominated=has_nominated,
                has_voted=has_voted,
                leader=leader_data
            )

            send_email(user.email, "Game Night Reminder", html_body)

def start_scheduler(app):
    """Start the background scheduler for reminders."""
    from app.services.reminders_services import check_and_send_reminders

    scheduler.configure(timezone="America/Chicago")

    with app.app_context():  # Create jobs within the app context
        scheduler.add_job(
            func=check_and_send_reminders,
            trigger=CronTrigger(hour=10, minute=18),
            id="daily_game_night_reminder",
            replace_existing=True
        )

    scheduler.start()