# utils/utils.py
from flask_mail import Message
from flask import current_app
from fetch_bgg_data import fetch_game_details, parse_game_details

def send_email(to, subject, html_body):
    """Helper function to send emails."""
    from app import mail
    
    with current_app.app_context():  # Ensure the correct application context
        msg = Message(subject, sender=current_app.config['MAIL_USERNAME'], recipients=[to])
        msg.html = html_body
        mail.send(msg)

def fetch_and_parse_bgg_data(bgg_id):
    """Fetch and parse game details from BoardGameGeek."""
    xml_data = fetch_game_details(bgg_id)
    if xml_data:
        return parse_game_details(xml_data)
    return {}