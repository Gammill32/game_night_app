# utils/utils.py
from flask_mail import Message
from flask import current_app

def send_email(to, subject, html_body):
    """Helper function to send emails."""
    from app import mail
    
    with current_app.app_context():  # Ensure the correct application context
        msg = Message(subject, sender=current_app.config['MAIL_USERNAME'], recipients=[to])
        msg.html = html_body
        mail.send(msg)
