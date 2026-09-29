from datetime import datetime

import pytz
from flask import current_app
from sqlalchemy import func
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import Poll, PollInvitee, PollOption, PollResponse


def poll_is_active(poll: Poll) -> bool:
    """Single source of truth for whether a poll accepts responses."""
    if poll.closed:
        return False
    if poll.closes_at is not None and poll.closes_at <= datetime.utcnow():
        return False
    return True


def _tz():
    return pytz.timezone(current_app.config["APP_TIMEZONE"])


def parse_closes_at(raw: str) -> datetime | None:
    """A datetime-local form value (local time) → naive UTC for storage.
    Raises ValueError on a bad value."""
    raw = (raw or "").strip()
    if not raw:
        return None
    local = _tz().localize(datetime.fromisoformat(raw))
    return local.astimezone(pytz.utc).replace(tzinfo=None)


def to_local(utc_naive: datetime | None) -> datetime | None:
    """Stored naive UTC → local time, for display and form values."""
    if utc_naive is None:
        return None
    return pytz.utc.localize(utc_naive).astimezone(_tz())


def create_poll(
    title: str,
    description: str | None,
    option_labels: list[str],
    created_by_id: int | None,
    multi_select: bool,
    closes_at: datetime | None = None,
    private: bool = False,
    invitee_ids: list[int] | None = None,
    game_night_id: int | None = None,
) -> Poll:
    """Create a new poll with options. Returns the saved Poll."""
    for _attempt in range(3):
        token = Poll.generate_token()
        if not Poll.query.filter_by(token=token).first():
            break
    else:
        raise RuntimeError("Could not generate a unique poll token after 3 attempts")

    poll = Poll(
        title=title,
        description=description,
        created_by=created_by_id,
        multi_select=multi_select,
        closes_at=closes_at,
        token=token,
        private=private,
        game_night_id=game_night_id,
    )
    db.session.add(poll)
    db.session.flush()

    for i, label in enumerate(option_labels):
        db.session.add(PollOption(poll_id=poll.id, label=label.strip(), display_order=i))

    if private and invitee_ids:
        for person_id in invitee_ids:
            db.session.add(PollInvitee(poll_id=poll.id, person_id=person_id))

    db.session.commit()
    return poll


def update_poll(
    poll: Poll,
    title: str,
    description: str | None,
    closes_at: datetime | None,
    multi_select: bool,
    private: bool,
    invitee_ids: list[int] | None,
    option_updates: dict[int, str],
    game_night_id: int | None = None,
) -> None:
    """Update poll metadata, option labels, invitees and linked night.

    An availability poll stays on its night; other polls can be linked to any
    night or none."""
    poll.title = title
    if not poll.availability:
        poll.game_night_id = game_night_id
    poll.description = description
    poll.closes_at = closes_at
    poll.multi_select = multi_select
    poll.private = private

    for option in poll.options:  # type: ignore[attr-defined]
        if option.id in option_updates and option_updates[option.id].strip():
            option.label = option_updates[option.id].strip()

    # Replace invitees
    PollInvitee.query.filter_by(poll_id=poll.id).delete()
    if private and invitee_ids:
        for person_id in invitee_ids:
            db.session.add(PollInvitee(poll_id=poll.id, person_id=person_id))

    db.session.commit()


def create_availability_poll(game_night_id: int, user_id: int) -> tuple[bool, str]:
    """Create the night's Can/Maybe/Can't poll. Its answers are the RSVPs."""
    from app.models import GameNight

    gn = GameNight.query.get_or_404(game_night_id)
    if gn.availability_poll is not None:
        return False, "This game night already has an availability poll."
    poll = create_poll(
        title=availability_title(gn.date),
        description=None,
        option_labels=AVAILABILITY_OPTIONS,
        created_by_id=user_id,
        multi_select=False,
        game_night_id=game_night_id,
    )
    poll.availability = True
    db.session.commit()
    return True, "Availability poll created. Players can answer it on this page."


AVAILABILITY_OPTIONS = ["Can Make It", "Maybe", "Can't Make It"]


def availability_title(date) -> str:
    return f"Availability — Game Night {date.strftime('%B %-d, %Y')}"


def get_poll_by_token(token: str) -> Poll | None:
    """Fetch a poll by its shareable token."""
    return Poll.query.filter_by(token=token).first()


def can_view(poll: Poll, user) -> bool:
    """Polls need a login. Admins see everything; a private poll is for its
    invitees; a poll linked to a game night is for that night's players."""
    if not user.is_authenticated:
        return False
    if user.admin or user.owner:
        return True
    if poll.private:
        return any(inv.person_id == user.id for inv in poll.invitees)  # type: ignore[attr-defined]
    if poll.game_night_id is not None:
        from app.models import Player

        return (
            Player.query.filter_by(game_night_id=poll.game_night_id, people_id=user.id).first()
            is not None
        )
    return True


def open_polls_for(user) -> list[Poll]:
    """Open polls this user can see, newest first."""
    from sqlalchemy.orm import selectinload

    polls = (
        Poll.query.filter_by(closed=False)
        .options(selectinload(Poll.invitees), selectinload(Poll.game_night))  # type: ignore[arg-type]
        .order_by(Poll.created_at.desc())
        .all()
    )
    return [p for p in polls if poll_is_active(p) and can_view(p, user)]


def has_responded(poll: Poll, person_id: int) -> bool:
    """Check if this person has already answered."""
    return PollResponse.query.filter_by(poll_id=poll.id, person_id=person_id).first() is not None


def submit_response(poll: Poll, option_ids: list[int], person_id: int) -> tuple[bool, str]:
    """Record a person's answer, replacing any earlier one. Returns (success, message)."""
    if not poll_is_active(poll):
        return False, "This poll is no longer accepting responses."
    if not option_ids:
        return False, "Please select at least one option."
    if not poll.multi_select and len(option_ids) > 1:
        return False, "Pick one option."

    valid_ids = {opt.id for opt in poll.options}  # type: ignore[attr-defined]
    if any(oid not in valid_ids for oid in option_ids):
        return False, "Invalid option selected."

    changed = has_responded(poll, person_id)
    PollResponse.query.filter_by(poll_id=poll.id, person_id=person_id).delete()
    for oid in dict.fromkeys(option_ids):
        db.session.add(PollResponse(poll_id=poll.id, option_id=oid, person_id=person_id))

    db.session.commit()
    return True, "Answer updated." if changed else "Response recorded. Thank you!"


def view_context(poll: Poll, person_id: int) -> dict:
    """Everything the poll widget needs for one viewer."""
    active = poll_is_active(poll)
    if poll.date_poll:
        from app.services import date_poll_services

        answers = date_poll_services.my_answers(poll, person_id)
        return {
            "poll": poll,
            "active": active,
            "user_votes": set(answers),
            "date_answers": answers,
            "date_rows": date_poll_services.summary(poll) if answers or not active else None,
            "results": None,
        }
    user_votes = get_user_responses(poll, person_id)
    return {
        "poll": poll,
        "active": active,
        "user_votes": user_votes,
        "results": get_results(poll) if user_votes or not active else None,
    }


def rsvps_for_night(game_night) -> dict[int, str]:
    """{person_id: availability answer} from the night's availability poll."""
    poll = game_night.availability_poll
    if poll is None:
        return {}
    labels = {opt.id: opt.label for opt in poll.options}
    return {
        r.person_id: labels[r.option_id]
        for r in poll.responses
        if r.person_id is not None and r.option_id in labels
    }


def get_results(poll: Poll) -> list[dict]:
    """Return response counts per option, sorted by display_order."""
    # Single GROUP BY query fetches all counts at once
    count_rows = (
        db.session.query(
            PollResponse.option_id,
            func.count(PollResponse.id).label("count"),
        )
        .filter(PollResponse.poll_id == poll.id)
        .group_by(PollResponse.option_id)
        .all()
    )
    counts = {row.option_id: row.count for row in count_rows}

    return [
        {"option_id": option.id, "label": option.label, "count": counts.get(option.id, 0)}
        for option in poll.options  # type: ignore[attr-defined]
    ]


def get_user_responses(poll: Poll, person_id: int) -> set[int]:
    """Return the set of option IDs a logged-in user voted for."""
    responses = PollResponse.query.filter_by(poll_id=poll.id, person_id=person_id).all()
    return {r.option_id for r in responses}


def get_detailed_results(poll: Poll) -> list[dict]:
    """Return response counts per option with voter details."""
    results = []
    for option in poll.options:  # type: ignore[attr-defined]
        responses = (
            PollResponse.query.options(joinedload(PollResponse.person))  # type: ignore[arg-type]
            .filter_by(poll_id=poll.id, option_id=option.id)
            .all()
        )
        voters = []
        for r in responses:
            if r.person_id and r.person:
                name = f"{r.person.first_name} {r.person.last_name}"
            else:
                name = r.respondent_name or "Anonymous"
            voters.append({"name": name, "person_id": r.person_id})
        results.append(
            {
                "option_id": option.id,
                "label": option.label,
                "count": len(responses),
                "voters": voters,
            }
        )
    return results
