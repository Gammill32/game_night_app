from datetime import datetime

from app.extensions import db
from app.models import Poll, PollOption, PollResponse


def poll_is_active(poll: Poll) -> bool:
    """Single source of truth for whether a poll accepts responses."""
    if poll.closed:
        return False
    if poll.closes_at is not None and poll.closes_at <= datetime.utcnow():
        return False
    return True


def create_poll(
    title: str,
    description: str | None,
    option_labels: list[str],
    created_by_id: int | None,
    multi_select: bool,
    closes_at: datetime | None = None,
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
    )
    db.session.add(poll)
    db.session.flush()

    for i, label in enumerate(option_labels):
        db.session.add(PollOption(poll_id=poll.id, label=label.strip(), display_order=i))

    db.session.commit()
    return poll


def create_availability_poll(game_night_id: int, user_id: int) -> Poll:
    """Create a standard Can/Maybe/Can't poll linked to a game night."""
    from app.models import GameNight

    gn = GameNight.query.get_or_404(game_night_id)
    date_str = gn.date.strftime("%B %-d, %Y")
    poll = create_poll(
        title=f"Availability — Game Night {date_str}",
        description=None,
        option_labels=["Can Make It", "Maybe", "Can't Make It"],
        created_by_id=user_id,
        multi_select=False,
    )
    poll.game_night_id = game_night_id
    db.session.commit()
    return poll


def get_poll_by_token(token: str) -> Poll | None:
    """Fetch a poll by its shareable token."""
    return Poll.query.filter_by(token=token).first()


def has_responded(poll: Poll, person_id: int | None, respondent_name: str | None) -> bool:
    """Check if this respondent has already submitted a response."""
    query = PollResponse.query.filter_by(poll_id=poll.id)
    if person_id is not None:
        return query.filter_by(person_id=person_id).first() is not None
    if respondent_name:
        normalised = respondent_name.strip().lower()
        existing = query.filter(PollResponse.person_id.is_(None)).all()
        return any((r.respondent_name or "").strip().lower() == normalised for r in existing)
    return False


def submit_response(
    poll: Poll,
    option_ids: list[int],
    person_id: int | None,
    respondent_name: str | None,
) -> tuple[bool, str]:
    """Submit a response. Returns (success, message)."""
    if not poll_is_active(poll):
        return False, "This poll is no longer accepting responses."

    original_name = respondent_name
    normalised_name = respondent_name.strip().lower() if respondent_name else None

    if poll.multi_select:
        existing = _get_existing_responses(poll, person_id, normalised_name)
        for r in existing:
            db.session.delete(r)
    else:
        if has_responded(poll, person_id, normalised_name):
            return False, "You have already responded to this poll."

    valid_ids = {opt.id for opt in poll.options}  # type: ignore[attr-defined]
    for oid in option_ids:
        if oid not in valid_ids:
            return False, "Invalid option selected."

    for oid in option_ids:
        db.session.add(
            PollResponse(
                poll_id=poll.id,
                option_id=oid,
                person_id=person_id,
                respondent_name=original_name,
            )
        )

    db.session.commit()
    return True, "Response recorded. Thank you!"


def get_results(poll: Poll) -> list[dict]:
    """Return response counts per option, sorted by display_order."""
    results = []
    for option in poll.options:  # type: ignore[attr-defined]
        count = PollResponse.query.filter_by(poll_id=poll.id, option_id=option.id).count()
        results.append({"option_id": option.id, "label": option.label, "count": count})
    return results


def _get_existing_responses(
    poll: Poll,
    person_id: int | None,
    normalised_name: str | None,
) -> list[PollResponse]:
    query = PollResponse.query.filter_by(poll_id=poll.id)
    if person_id is not None:
        return query.filter_by(person_id=person_id).all()
    if normalised_name:
        all_anon = query.filter(PollResponse.person_id.is_(None)).all()
        return [r for r in all_anon if (r.respondent_name or "").strip().lower() == normalised_name]
    return []
