"""Outgoing email that isn't a single message.

Single emails (password resets, reminders) go through app.utils.send_email;
this holds the batch sends, which share one SMTP session.
"""

from flask import current_app
from flask_mail import Message

from app.extensions import mail


def poll_share_body(poll, person, poll_url: str) -> str:
    return (
        f"Hi {person.first_name},\n\n"
        + (
            f"Help pick a date for the next game night: {poll.title}\n"
            if poll.date_poll
            else f"There's a Game Night poll for you: {poll.title}\n"
        )
        + (f"{poll.description}\n" if poll.description else "")
        + ("\nSay which dates work for you here:\n" if poll.date_poll else "\nAnswer it here:\n")
        + f"{poll_url}\n\n"
        "You'll be asked to sign in first. Forgot your password? "
        "The sign-in page has a reset link.\n\n"
        "— Game Night"
    )


def send_poll_invites(poll, recipients, poll_url: str) -> set[int]:
    """Email each recipient a link to the poll. Returns the ids of the people
    it was sent to.

    One SMTP session for the whole batch (Flask-Mail's bulk recipe,
    mail.connect()), not a connect + TLS + login per person. A failed address
    doesn't stop the rest, so the caller can name whoever didn't get it."""
    sent_ids: set[int] = set()
    try:
        with mail.connect() as conn:
            for person in recipients:
                try:
                    conn.send(
                        Message(
                            subject=f"Game Night Poll: {poll.title}",
                            recipients=[person.email],
                            body=poll_share_body(poll, person, poll_url),
                        )
                    )
                    sent_ids.add(person.id)
                except Exception:
                    current_app.logger.exception("Poll share email to %s failed", person.email)
    except Exception:  # couldn't connect or log in (or quit) at all
        current_app.logger.exception("Poll share: SMTP session failed")
    return sent_ids
