# blueprints/reminders.py

from flask import Blueprint, render_template
from flask_mail import Message
from app.models import db, GameNight, Game, GameVotes, Player, Person, GameNominations
from datetime import datetime
import pytz

reminders_bp = Blueprint("reminders", __name__)

def send_email(to, subject, html_body):
    """Helper function to send emails."""
    from app import mail, app  # Import the mail and app instances
    with app.app_context():  # Ensure we use the correct application context
        msg = Message(subject, sender=app.config['MAIL_USERNAME'], recipients=[to])
        msg.html = html_body
        mail.send(msg)

def check_and_send_reminders():
    """Checks for upcoming game nights and sends reminder emails to participants."""
    from flask import current_app  # Import the app instance to get the correct context

    with current_app.app_context():  # Use the app context for database queries
        central_timezone = pytz.timezone("America/Chicago")
        today_central = datetime.now(central_timezone).date()

        # Query game nights happening today
        game_nights = GameNight.query.filter_by(date=today_central).all()
        if not game_nights:
            return

        for game_night in game_nights:
            # Determine the current leader in game votes with weighted scoring
            leader = (
                db.session.query(
                    Game,
                    func.sum(
                        db.case(
                            (GameVotes.rank == 1, 3),  # Rank 1: 3 points
                            (GameVotes.rank == 2, 2),  # Rank 2: 2 points
                            (GameVotes.rank == 3, 1),  # Rank 3: 1 point
                        )
                    ).label('weighted_score'),
                    func.count(GameVotes.id).label('vote_count')  # Total votes
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

            # Query all players for this game night
            players = Player.query.filter_by(game_night_id=game_night.id).all()
            for player in players:
                user = Person.query.get(player.people_id)

                has_nominated = GameNominations.query.filter_by(game_night_id=game_night.id, player_id=player.id).first()
                has_voted = GameVotes.query.filter_by(game_night_id=game_night.id, player_id=player.id).first()

                # Render the email template
                html_body = render_template(
                    'email_templates/reminder_body.html',
                    user=user,
                    game_night=game_night,
                    has_nominated=has_nominated,
                    has_voted=has_voted,
                    leader=leader_data  # Pass the leader data to the template
                )

                # Send the email
                send_email(user.email, "Game Night Reminder", html_body)
