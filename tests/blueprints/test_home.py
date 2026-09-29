import datetime as dt

import pytz

from app.services.poll_services import create_availability_poll, create_poll, submit_response
from tests.conftest import login


def test_home_shows_upcoming_and_open_polls(app, client, make_person, make_night):
    ann, bo, adm = make_person("Ann"), make_person("Bo"), make_person("Adm")
    today = dt.datetime.now(pytz.timezone(app.config["APP_TIMEZONE"])).date()
    soon = make_night(ann, bo, date=today + dt.timedelta(days=3), notes="Bring snacks")
    make_night(bo, date=today + dt.timedelta(days=5))  # Ann isn't in this one
    past = make_night(ann, date=today - dt.timedelta(days=7), final=True)
    create_availability_poll(soon.id, adm.id)
    general = create_poll("Next big game?", None, ["A", "B"], adm.id, False)
    answered = create_poll("Snack vote", None, ["Chips", "Salsa"], adm.id, False)
    submit_response(answered, [answered.options[0].id], ann.id)

    login(client, ann)
    page = " ".join(client.get("/").get_data(as_text=True).split())
    assert "In 3 days" in page and "Bring snacks" in page and "RSVP needed" in page
    assert "In 5 days" not in page
    assert past.date.strftime("%B %-d, %Y") in page
    # unanswered polls are answerable right here, the RSVP poll included
    assert f'id="poll-{general.id}"' in page and f'id="poll-{soon.availability_poll.id}"' in page
    assert "Needs your answer" in page and "Snack vote" in page and "✓ answered" in page

    from app.extensions import db as _db

    for poll in (general, answered):
        _db.session.delete(poll)
    _db.session.commit()
