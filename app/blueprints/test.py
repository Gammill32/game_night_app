from flask import Blueprint, redirect, url_for, flash, jsonify
from app.utils import send_email, game_night_access_required
from flask_login import login_required, current_user
from app.models import GameVotes, Player, GameNightNominationsVotes

test_bp = Blueprint("test", __name__)

@test_bp.route("/send_test_email", methods=["GET"])
@login_required  # Ensure user is logged in
def send_test_email():
    """Route to send a test email to the current user."""
    subject = "Test Email"
    html_body = f"Hello {current_user.first_name},<br><br>This is a test email."

    send_email(current_user.email, subject, html_body)  # Send email

    flash(f"Test email sent to {current_user.email}.", "success")
    return redirect(url_for("main.index"))

@test_bp.route("/game_night/<int:game_night_id>/test", methods=["GET"])
@login_required
@game_night_access_required
def test_game_night(game_night_id):
    """Test route to fetch and display game night nominations, votes, and user-specific data."""

    # Fetch the current user's player record for this game night
    current_player = Player.query.filter_by(game_night_id=game_night_id, people_id=current_user.id).first()

    # Fetch the user's votes
    user_votes = {}
    if current_player:
        user_votes_query = GameVotes.query.filter_by(
            game_night_id=game_night_id,
            player_id=current_player.id
        ).all()
        user_votes = {vote.game_id: vote.rank for vote in user_votes_query}

    # Fetch nominations and vote scores using the SQL View
    nominations = [
        {
            "game_id": nomination.game_id,
            "game_name": nomination.game_name,
            "image_url": nomination.image_url,  # ✅ Image URL
            "total_nominations": nomination.total_nominations,
            "vote_score": nomination.vote_score,
            "user_vote": user_votes.get(nomination.game_id, None)  # ✅ User Vote
        }
        for nomination in GameNightNominationsVotes.query.filter_by(game_night_id=game_night_id).order_by(
            GameNightNominationsVotes.vote_score.desc(),
            GameNightNominationsVotes.total_nominations.desc(),
            GameNightNominationsVotes.game_name
        ).all()
    ]

    return jsonify({
        "user_votes": user_votes,  # ✅ Separate user votes
        "nominations": nominations
    })