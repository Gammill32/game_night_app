"""Date polls: find a night that works for everyone.

An admin picks a date range (optionally only some weekdays); the poll gets one
option per date. Each person answers Yes / If needed / No per date. The
summary ranks dates by Yes, then Yes + If needed. When the admin picks a
date, the game night is created with everyone who said Yes or If needed as
players, the date poll closes, and the night's RSVP (availability) poll is
created with those answers carried over: Yes → Can Make It, If needed → Maybe.
"""

from datetime import date, datetime, timedelta

from app.extensions import db
from app.models import GameNight, Player, Poll, PollOption, PollResponse
from app.services import poll_services

ANSWERS = ("yes", "maybe", "no")
ANSWER_LABELS = {"yes": "Yes", "maybe": "If needed", "no": "No"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MAX_DATES = 60


def dates_in_range(start: date, end: date, weekdays: set[int]) -> tuple[list[date], str | None]:
    """Every date from start to end (inclusive) on the given weekdays (0 = Monday)."""
    if end < start:
        return [], "The end date is before the start date."
    if not weekdays:
        return [], "Pick at least one day of the week."
    dates = []
    day = start
    while day <= end:
        if day.weekday() in weekdays:
            dates.append(day)
            if len(dates) > MAX_DATES:
                return [], f"That's more than {MAX_DATES} dates; narrow the range or the days."
        day += timedelta(days=1)
    if not dates:
        return [], "No dates in that range fall on the days you picked."
    return dates, None


def parse_form(form) -> tuple[list[date], str | None]:
    """Dates for a new date poll: hand-picked (date_mode=pick) or a range."""
    if form.get("date_mode") == "pick":
        return picked_dates(form.getlist("dates"))
    try:
        start = date.fromisoformat(form.get("start_date", ""))
        end = date.fromisoformat(form.get("end_date", ""))
    except ValueError:
        return [], "Pick a start and end date."
    weekdays = {int(d) for d in form.getlist("weekdays") if d.isdigit() and int(d) < 7}
    return dates_in_range(start, end, weekdays)


def picked_dates(raw: list[str]) -> tuple[list[date], str | None]:
    try:
        dates = sorted({date.fromisoformat(d) for d in raw if d})
    except ValueError:
        return [], "One of those dates isn't valid."
    if not dates:
        return [], "Tap at least one date on the calendar."
    if len(dates) > MAX_DATES:
        return [], f"That's more than {MAX_DATES} dates."
    return dates, None


def label_for(day: date) -> str:
    return day.strftime("%a, %b %-d")


def create_date_poll(
    title: str,
    description: str | None,
    dates: list[date],
    created_by_id: int,
    closes_at: datetime | None = None,
    private: bool = False,
    invitee_ids: list[int] | None = None,
) -> Poll:
    poll = poll_services.create_poll(
        title,
        description,
        [label_for(d) for d in dates],
        created_by_id,
        multi_select=True,
        closes_at=closes_at,
        private=private,
        invitee_ids=invitee_ids,
    )
    poll.date_poll = True
    for option, day in zip(poll.options, dates, strict=True):  # type: ignore[attr-defined]
        option.option_date = day
    db.session.commit()
    return poll


def my_answers(poll: Poll, person_id: int) -> dict[int, str]:
    return {
        r.option_id: r.answer
        for r in PollResponse.query.filter_by(poll_id=poll.id, person_id=person_id)
        if r.answer
    }


def submit_answers(poll: Poll, person_id: int, form) -> tuple[bool, str]:
    """Answers come in as answer_<option_id> = yes / maybe / no."""
    if not poll_services.poll_is_active(poll):
        return False, "This poll is no longer accepting responses."
    answers = {}
    for option in poll.options:  # type: ignore[attr-defined]
        value = form.get(f"answer_{option.id}")
        if value in ANSWERS:
            answers[option.id] = value
    if not answers:
        return False, "Answer at least one date."
    changed = poll_services.has_responded(poll, person_id)
    PollResponse.query.filter_by(poll_id=poll.id, person_id=person_id).delete()
    for option_id, answer in answers.items():
        db.session.add(
            PollResponse(poll_id=poll.id, option_id=option_id, person_id=person_id, answer=answer)
        )
    db.session.commit()
    return True, "Answers updated." if changed else "Thanks! Your dates are in."


def summary(poll: Poll) -> list[dict]:
    """Per date: who said what, and whether it's one of the best dates."""
    by_option: dict[int, dict[str, list]] = {
        o.id: {a: [] for a in ANSWERS}
        for o in poll.options  # type: ignore[attr-defined]
    }
    for r in poll.responses:  # type: ignore[attr-defined]
        if r.answer in ANSWERS and r.person is not None and r.option_id in by_option:
            by_option[r.option_id][r.answer].append(r.person)
    rows = []
    for option in poll.options:  # type: ignore[attr-defined]
        people = {
            a: sorted(ps, key=lambda p: p.first_name.lower())
            for a, ps in by_option[option.id].items()
        }
        rows.append(
            {
                "option": option,
                "yes": people["yes"],
                "maybe": people["maybe"],
                "no": people["no"],
                "score": (len(people["yes"]), len(people["yes"]) + len(people["maybe"])),
                "past": option.option_date is not None and option.option_date < date.today(),
            }
        )
    best = max((r["score"] for r in rows if r["score"][1] > 0), default=None)
    for r in rows:
        r["best"] = best is not None and r["score"] == best
    return rows


def respondent_count(poll: Poll) -> int:
    return len({r.person_id for r in poll.responses if r.person_id})  # type: ignore[attr-defined]


def pick_date(poll: Poll, option_id: int, admin_id: int) -> tuple[bool, str, GameNight | None]:
    if not poll.date_poll:
        return False, "That isn't a date poll.", None
    if poll.picked_game_night_id is not None:
        return False, "A date has already been picked for this poll.", None
    option = db.session.get(PollOption, option_id)
    if option is None or option.poll_id != poll.id or option.option_date is None:
        return False, "Pick one of the poll's dates.", None

    answers = {
        r.person_id: r.answer
        for r in PollResponse.query.filter_by(poll_id=poll.id, option_id=option.id)
        if r.person_id and r.answer in ("yes", "maybe")
    }
    night = GameNight(date=option.option_date)
    db.session.add(night)
    db.session.flush()
    for person_id in answers:
        db.session.add(Player(game_night_id=night.id, people_id=person_id))
    poll.closed = True
    poll.picked_game_night_id = night.id
    db.session.commit()

    poll_services.create_availability_poll(night.id, admin_id)
    rsvp = night.availability_poll
    by_label = {o.label: o.id for o in rsvp.options}
    for person_id, answer in answers.items():
        label = "Can Make It" if answer == "yes" else "Maybe"
        db.session.add(
            PollResponse(poll_id=rsvp.id, option_id=by_label[label], person_id=person_id)
        )
    db.session.commit()
    n = len(answers)
    return (
        True,
        f"Game night created for {night.date.strftime('%B %-d')} with the {n} "
        f"{'person' if n == 1 else 'people'} who said Yes or If needed; their RSVPs are filled in. "
        "Add anyone else, notes and food below.",
        night,
    )
