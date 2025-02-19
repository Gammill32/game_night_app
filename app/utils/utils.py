# utils/utils.py
from app.models import db, Result, GameNightGame
from sqlalchemy import func
from flask_mail import Message
from app import mail, app

def send_email(to, subject, html_body):
    """Helper function to send emails."""
    with app.app_context():  # Ensure the correct application context
        msg = Message(subject, sender=app.config['MAIL_USERNAME'], recipients=[to])
        msg.html = html_body
        mail.send(msg)
        
def determine_top_places(game_night_id):
    """Calculate top player rankings for a game night."""
    results = (
        db.session.query(Result.player_id, Result.position, func.count(Result.id).label('count'))
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .filter(GameNightGame.game_night_id == game_night_id)
        .group_by(Result.player_id, Result.position)
        .order_by(Result.player_id, Result.position)
        .all()
    )

    if not results:
        return None

    player_scores = {}
    max_position = 0
    for player_id, position, count in results:
        if player_id not in player_scores:
            player_scores[player_id] = {}
        player_scores[player_id][position] = count
        max_position = max(max_position, position)

    for scores in player_scores.values():
        for pos in range(1, max_position + 1):
            scores.setdefault(pos, 0)

    sorted_players = sorted(
        player_scores.items(),
        key=lambda item: tuple(-item[1].get(pos, 0) for pos in range(1, max_position + 1))
    )

    places = []
    current_place = 1
    current_group = []

    for i, (player_id, scores) in enumerate(sorted_players):
        if i > 0:
            prev_scores = sorted_players[i - 1][1]
            if scores != prev_scores:
                places.append((current_place, current_group))
                current_group = []
                current_place += 1

        current_group.append(player_id)

    if current_group:
        places.append((current_place, current_group))

    return places
