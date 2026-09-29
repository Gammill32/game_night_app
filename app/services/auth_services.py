from datetime import datetime

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
        Person.query.filter_by(active=True)
        .filter(func.lower(Person.first_name) == first_name)
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


RESET_MAX_AGE = 60 * 60  # reset links work for an hour
FORGOT_MESSAGE = "If that email has an account, we've sent a link to reset the password."


def _reset_serializer():
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def make_reset_token(user):
    # Includes part of the current password hash, so the link stops working
    # once the password has been changed (i.e. it can only be used once).
    return _reset_serializer().dumps({"id": user.id, "pw": (user.password or "")[-12:]})


def user_for_reset_token(token):
    """The person a reset link is for, or None if it's invalid, used or expired."""
    from itsdangerous import BadSignature, SignatureExpired

    try:
        data = _reset_serializer().loads(token, max_age=RESET_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(Person, data.get("id"))
    if user is None or not user.active or (user.password or "")[-12:] != data.get("pw"):
        return None
    return user


def forgot_password(email):
    """Email a one-time reset link. Says the same thing whether or not the
    email has an account, so the form can't be used to find out."""
    from flask import url_for

    user = Person.query.filter(func.lower(Person.email) == (email or "").strip().lower()).first()
    if user and user.active and user.password:
        link = url_for("auth.reset_password", token=make_reset_token(user), _external=True)
        html_body = f"""
        <p>Hello {user.first_name},</p>
        <p>Someone asked to reset your Game Night password. If it was you, use this link
        within the next hour:</p>
        <p><a href="{link}">{link}</a></p>
        <p>If you didn't ask, you can ignore this email; your password hasn't changed.</p>
        """
        try:
            send_email(user.email, "Reset your Game Night password", html_body)
        except Exception:
            import logging

            logging.getLogger(__name__).exception("Password reset email failed for %s", user.id)
    return True, FORGOT_MESSAGE


def reset_password(user, new_password, confirm_password):
    if not new_password or len(new_password) < 8:
        return False, "Use at least 8 characters."
    if new_password != confirm_password:
        return False, "The passwords don't match."
    user.password = bcrypt.generate_password_hash(new_password).decode("utf-8")
    user.temp_pass = False
    user.temp_pass_expires_at = None
    db.session.commit()
    return True, "Password changed. You can sign in now."


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


def update_profile(user, current_password, email, new_password, confirm_password):
    """Change email and/or password from the profile page. Either change
    needs the current password."""
    email = (email or "").strip().lower()
    new_password = new_password or ""
    changing_email = email != (user.email or "")
    if not changing_email and not new_password:
        return False, "Nothing to update."
    if not user.password or not bcrypt.check_password_hash(user.password, current_password or ""):
        return False, "Current password is incorrect."

    if changing_email:
        if not email or "@" not in email:
            return False, "Enter a valid email address."
        taken = Person.query.filter(func.lower(Person.email) == email, Person.id != user.id).first()
        if taken:
            return False, "An account with this email already exists."
        user.email = email

    if new_password:
        if new_password != confirm_password:
            return False, "New passwords do not match."
        user.password = bcrypt.generate_password_hash(new_password).decode("utf-8")
        user.temp_pass = False
        user.temp_pass_expires_at = None

    db.session.commit()
    changed = [what for what, did in (("Email", changing_email), ("password", new_password)) if did]
    return True, f"{' and '.join(changed).capitalize()} updated."
