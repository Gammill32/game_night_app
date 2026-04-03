import secrets
from datetime import datetime, timedelta

from sqlalchemy import func

from app.extensions import bcrypt
from app.models import Person, db
from app.utils import send_email


def login(email, password):
    """Authenticate user and return success status, message, and user instance."""
    user = Person.query.filter(func.lower(Person.email) == email).first()
    if user and bcrypt.check_password_hash(user.password, password):
        if (
            user.temp_pass
            and user.temp_pass_expires_at
            and datetime.utcnow() > user.temp_pass_expires_at
        ):
            return False, "Your temporary password has expired. Please request a new one.", None
        return True, "Login successful.", user
    return False, "Invalid email or password.", None


def signup(first_name, last_name, email, password):
    """Complete signup for a pre-created user by setting email and password."""
    email = email.strip().lower()
    first_name = first_name.strip().lower()
    last_name = last_name.strip().lower()

    # Email already taken by any user
    if Person.query.filter(func.lower(Person.email) == email).first():
        return False, "An account with this email already exists."

    # Try to find a matching person by name
    user = (
        Person.query.filter(func.lower(Person.first_name) == first_name)
        .filter(func.lower(Person.last_name) == last_name)
        .first()
    )

    if not user:
        return False, "No matching user found with that name. Please contact an admin."

    if user.email or user.password:
        return (
            False,
            "This user has already completed signup. Please use the forgot password or contact an admin.",
        )

    # Set email and password
    user.email = email
    user.password = bcrypt.generate_password_hash(password).decode("utf-8")
    user.temp_pass = False
    db.session.commit()

    return True, "Signup completed successfully! You can now log in."


def forgot_password(email):
    """Generate a temporary password and send it to the user's email."""
    user = Person.query.filter_by(email=email).first()
    if not user:
        return False, "Email not found."

    temp_password = secrets.token_urlsafe(8)
    user.password = bcrypt.generate_password_hash(temp_password).decode("utf-8")
    user.temp_pass = True
    user.temp_pass_expires_at = datetime.utcnow() + timedelta(hours=24)
    db.session.commit()

    subject = "Password Reset for Game Night App"
    html_body = f"""
    <p>Hello {user.first_name},</p>
    <p>Your temporary password is: <strong>{temp_password}</strong></p>
    <p>Please log in and change your password.</p>
    """
    send_email(user.email, subject, html_body)

    return True, "A temporary password has been sent to your email."


def update_password(user, current_password, new_password, confirm_password):
    """Update user password if the current password is correct."""
    if not bcrypt.check_password_hash(user.password, current_password):
        return False, "Current password is incorrect."

    if new_password != confirm_password:
        return False, "New passwords do not match."

    user.password = bcrypt.generate_password_hash(new_password).decode("utf-8")
    user.temp_pass = False
    user.temp_pass_expires_at = None
    db.session.commit()

    return True, "Password updated successfully."
