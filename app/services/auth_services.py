import hashlib
from datetime import timedelta

from sqlalchemy import func

from app.extensions import bcrypt
from app.models import AuthThrottle, Person, db
from app.utils import send_email

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_BYTES = 72  # bcrypt refuses anything longer


def password_problem(password):
    """What's wrong with a new password, or None if it's fine. The one rule
    for signup, reset, and changing it from the profile."""
    if not password or len(password) < PASSWORD_MIN_LENGTH:
        return f"Use at least {PASSWORD_MIN_LENGTH} characters for your password."
    if len(password.encode("utf-8")) > PASSWORD_MAX_BYTES:
        return "That password is too long; keep it under 70 characters."
    return None


def hash_password(password):
    return bcrypt.generate_password_hash(password).decode("utf-8")


# Throttling lives in the database so every worker and thread sees the same
# counts (Flask-Limiter's only shared backends are Redis/Memcached/MongoDB).
LOGIN_WINDOW = 15 * 60
LOGIN_EMAIL_LIMIT = 10  # failed sign-ins for one email per window
LOGIN_IP_LIMIT = 30  # failed sign-ins from one address per window
FORGOT_WINDOW = 60 * 60
FORGOT_EMAIL_LIMIT = 3  # reset emails to one address per window
FORGOT_IP_LIMIT = 10  # reset requests from one address per window
TOO_MANY_LOGINS = "Too many sign-in attempts. Wait a few minutes and try again."


def _throttle_on():
    from flask import current_app

    return current_app.config.get("AUTH_THROTTLE", True)


def _email_key(kind, email):
    return f"{kind}:email:" + hashlib.sha256(email.encode("utf-8")).hexdigest()[:40]


def _over_limit(key, limit, window):
    since = func.now() - timedelta(seconds=window)
    count = AuthThrottle.query.filter(
        AuthThrottle.key == key, AuthThrottle.created_at > since
    ).count()
    return count >= limit


def _record(*keys):
    AuthThrottle.query.filter(AuthThrottle.created_at < func.now() - timedelta(days=1)).delete(
        synchronize_session=False
    )
    db.session.add_all([AuthThrottle(key=key) for key in keys if key])
    db.session.commit()


def login(email, password, ip=None):
    """Authenticate user and return success status, message, and user instance."""
    if not email or not password:
        return False, "Enter your email and password.", None
    throttle = _throttle_on()
    email_key, ip_key = _email_key("login", email), f"login:ip:{ip}" if ip else None
    if throttle and (
        _over_limit(email_key, LOGIN_EMAIL_LIMIT, LOGIN_WINDOW)
        or (ip_key and _over_limit(ip_key, LOGIN_IP_LIMIT, LOGIN_WINDOW))
    ):
        return False, TOO_MANY_LOGINS, None
    user = Person.query.filter(func.lower(Person.email) == email).first()
    if user and user.password and bcrypt.check_password_hash(user.password, password):
        return True, "Login successful.", user
    if throttle:
        _record(email_key, ip_key)
    return False, "Invalid email or password.", None


INVITE_MAX_AGE = 14 * 24 * 60 * 60  # invite links work for two weeks
INVITE_USED = "That invite link has expired or was already used. Ask for a new one."


def _invite_serializer():
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="person-invite")


def _invite_fingerprint(person):
    # Deactivating someone gives them a new session token, which also voids
    # invites sent before, so restoring them doesn't revive old links.
    return hashlib.sha256((person.session_token or "").encode("utf-8")).hexdigest()[:16]


def make_invite_token(person):
    return _invite_serializer().dumps({"id": person.id, "st": _invite_fingerprint(person)})


def invite_link(person):
    from flask import url_for

    return url_for("auth.signup", invite=make_invite_token(person), _external=True)


def person_for_invite(token):
    """The unclaimed person an invite link is for, or None if the link is
    bad, expired, or already used (the person has signed up since)."""
    from itsdangerous import BadSignature, SignatureExpired

    try:
        data = _invite_serializer().loads(token, max_age=INVITE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("id"), int):
        return None
    person = db.session.get(Person, data["id"])
    if person is None or not person.active or person.email or person.password:
        return None
    if _invite_fingerprint(person) != data.get("st"):
        return None
    return person


def can_invite(user, person):
    """Admins can invite anyone who hasn't signed up. Hosts can invite
    unclaimed people who play on a night they host, unless an admin has given
    that person rights (only an admin's link should hand those over)."""
    from app.models import GameNight, Player

    if person is None or not person.active or person.email or person.password or person.owner:
        return False
    if user.admin or user.owner:
        return True
    if not user.can_host or person.admin or person.can_host:
        return False
    return (
        db.session.query(Player.id)
        .join(GameNight, GameNight.id == Player.game_night_id)
        .filter(Player.people_id == person.id, GameNight.host_id == user.id)
        .first()
        is not None
    )


def invitable_people(user):
    """Unclaimed people this user can send an invite link to."""
    unclaimed = (
        Person.query.filter(
            Person.active.is_(True), Person.email.is_(None), Person.password.is_(None)
        )
        .order_by(Person.last_name, Person.first_name)
        .all()
    )
    return [p for p in unclaimed if can_invite(user, p)]


INVITE_ONLY = (
    "Sign-up is by invite. Ask an admin or your host for your invite link, "
    "then open it to create your account."
)


def signup(email, password, invite=None):
    """Claim the (unclaimed) person an invite link was made for, keeping any
    rights an admin gave them. Sign-up is invite-only: no link, no account."""
    if not invite:
        return False, INVITE_ONLY
    person = person_for_invite(invite)
    if person is None:
        return False, INVITE_USED
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False, "Enter a valid email address."
    problem = password_problem(password)
    if problem:
        return False, problem
    if Person.query.filter(func.lower(Person.email) == email).first():
        return (
            False,
            "An account with this email already exists. Sign in, or reset your password.",
        )

    person.email = email
    person.password = hash_password(password)
    db.session.commit()

    return True, "You're signed up! You can now log in."


RESET_MAX_AGE = 60 * 60  # reset links work for an hour
FORGOT_MESSAGE = "If that email has an account, we've sent a link to reset the password."


def _reset_serializer():
    from flask import current_app
    from itsdangerous import URLSafeTimedSerializer

    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="password-reset")


def _password_fingerprint(user):
    """A digest of the stored password hash: changes whenever the password
    does, without putting any of the hash itself in a readable token."""
    return hashlib.sha256((user.password or "").encode("utf-8")).hexdigest()[:32]


def make_reset_token(user):
    # Carries a fingerprint of the current password, so the link stops working
    # once the password has been changed (i.e. it can only be used once).
    return _reset_serializer().dumps({"id": user.id, "pw": _password_fingerprint(user)})


def user_for_reset_token(token):
    """The person a reset link is for, or None if it's invalid, used or expired."""
    from itsdangerous import BadSignature, SignatureExpired

    try:
        data = _reset_serializer().loads(token, max_age=RESET_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    user = db.session.get(Person, data.get("id"))
    if user is None or not user.active or _password_fingerprint(user) != data.get("pw"):
        return None
    return user


def forgot_password(email, ip=None):
    """Email a one-time reset link. Says the same thing whether or not the
    email has an account, so the form can't be used to find out."""
    from flask import url_for

    email = (email or "").strip().lower()
    if _throttle_on():
        email_key, ip_key = _email_key("forgot", email), f"forgot:ip:{ip}" if ip else None
        if _over_limit(email_key, FORGOT_EMAIL_LIMIT, FORGOT_WINDOW) or (
            ip_key and _over_limit(ip_key, FORGOT_IP_LIMIT, FORGOT_WINDOW)
        ):
            return True, FORGOT_MESSAGE  # same answer; just don't send
        _record(email_key, ip_key)
    user = Person.query.filter(func.lower(Person.email) == email).first()
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
    problem = password_problem(new_password)
    if problem:
        return False, problem
    if new_password != confirm_password:
        return False, "The passwords don't match."
    user.password = hash_password(new_password)
    user.rotate_session_token()  # sign out anyone else using the old password
    db.session.commit()
    return True, "Password changed. You can sign in now."


def update_password(user, current_password, new_password, confirm_password):
    """Update user password if the current password is correct."""
    if not user.password or not bcrypt.check_password_hash(user.password, current_password or ""):
        return False, "Current password is incorrect."

    problem = password_problem(new_password)
    if problem:
        return False, problem
    if new_password != confirm_password:
        return False, "New passwords do not match."

    user.password = hash_password(new_password)
    user.rotate_session_token()  # the caller logs this session back in
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
        problem = password_problem(new_password)
        if problem:
            return False, problem
        if new_password != confirm_password:
            return False, "New passwords do not match."
        user.password = hash_password(new_password)
        user.rotate_session_token()  # the caller logs this session back in

    db.session.commit()
    changed = [what for what, did in (("Email", changing_email), ("password", new_password)) if did]
    return True, f"{' and '.join(changed).capitalize()} updated."
