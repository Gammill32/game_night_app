from flask import Blueprint, redirect, url_for, flash
from app.utils import send_email
from flask_login import login_required, current_user

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