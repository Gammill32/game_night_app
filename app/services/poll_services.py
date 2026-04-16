from datetime import datetime

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


def create_poll(
    title: str,
    description: str | None,
    option_labels: list[str],
    created_by_id: int | None,
    multi_select: bool,
    closes_at: datetime | None = None,
    private: bool = False,
    invitee_ids: list[int] | None = None,
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
) -> None:
    """Update poll metadata, option labels, and invitees."""
    poll.title = title
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
