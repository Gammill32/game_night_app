# utils/utils.py
from flask import current_app
from flask_mail import Message
from sqlalchemy.orm import joinedload

from app.models import GameNight, Player


def send_email(to, subject, html_body):
    """Helper function to send emails."""
    from app import mail

    with current_app.app_context():  # Ensure the correct application context
        msg = Message(subject, sender=current_app.config["MAIL_USERNAME"], recipients=[to])
        msg.html = html_body
        mail.send(msg)


def get_game_night_and_sorted_players(game_night_id):
    """
    Fetch a game night and its players, sorted alphabetically
    by last name and first name.

    :param game_night_id: ID of the game night
    :return: Tuple (game_night, sorted list of Player objects)
    """
    game_night = GameNight.query.get_or_404(game_night_id)

    players = (
        Player.query.filter_by(game_night_id=game_night_id).options(joinedload(Player.person)).all()
    )

    sorted_players = sorted(players, key=lambda p: (p.person.last_name, p.person.first_name))

    return game_night, sorted_players
