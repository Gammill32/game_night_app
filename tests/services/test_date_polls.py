import datetime as dt

from werkzeug.datastructures import MultiDict

from app.extensions import db as _db
from app.models import Poll
from app.services import date_poll_services as dps
from app.services.poll_services import rsvps_for_night, view_context
from tests.conftest import login


def test_dates_in_range_filters_weekdays():
    # Oct 1 2026 is a Thursday; Fri=4, Sat=5
    dates, err = dps.dates_in_range(dt.date(2026, 10, 1), dt.date(2026, 10, 14), {4, 5})
    assert err is None
    assert dates == [dt.date(2026, 10, d) for d in (2, 3, 9, 10)]
    assert dps.dates_in_range(dt.date(2026, 10, 5), dt.date(2026, 10, 1), {4})[1]
    assert dps.dates_in_range(dt.date(2026, 10, 1), dt.date(2026, 10, 1), set())[1]
    assert (
        "more than"
        in dps.dates_in_range(dt.date(2026, 1, 1), dt.date(2026, 12, 31), set(range(7)))[1]
    )


def _poll(author):
    dates = [dt.date(2031, 3, 7), dt.date(2031, 3, 8), dt.date(2031, 3, 14)]
    return dps.create_date_poll("When?", None, dates, author.id)


def test_answers_summary_and_pick(make_person):
    adm, ann, bo, cy = (make_person(n) for n in ("Adm", "Ann", "Bo", "Cy"))
    poll = _poll(adm)
    o1, o2, o3 = poll.options
    assert o1.option_date == dt.date(2031, 3, 7) and o1.label == "Fri, Mar 7"

    assert not dps.submit_answers(poll, ann.id, MultiDict())[0]
    dps.submit_answers(
        poll, ann.id, MultiDict({f"answer_{o1.id}": "yes", f"answer_{o2.id}": "yes"})
    )
    dps.submit_answers(
        poll, bo.id, MultiDict({f"answer_{o1.id}": "no", f"answer_{o2.id}": "maybe"})
    )
    dps.submit_answers(poll, cy.id, MultiDict({f"answer_{o2.id}": "yes", f"answer_{o3.id}": "yes"}))
    ok, msg = dps.submit_answers(poll, cy.id, MultiDict({f"answer_{o2.id}": "yes"}))
    assert ok and "updated" in msg.lower()

    rows = {r["option"].id: r for r in dps.summary(poll)}
    assert rows[o2.id]["best"] and not rows[o1.id]["best"]
    assert [p.id for p in rows[o2.id]["maybe"]] == [bo.id]
    assert view_context(poll, ann.id)["date_answers"] == {o1.id: "yes", o2.id: "yes"}

    ok, msg, night = dps.pick_date(poll, o2.id, adm.id)
    assert ok, msg
    assert night.date == dt.date(2031, 3, 8)
    assert {p.people_id for p in night.players} == {ann.id, bo.id, cy.id}
    assert rsvps_for_night(night) == {ann.id: "Can Make It", bo.id: "Maybe", cy.id: "Can Make It"}
    assert poll.closed and poll.picked_game_night_id == night.id
    assert not dps.pick_date(poll, o1.id, adm.id)[0]

    _db.session.delete(night.availability_poll)
    _db.session.delete(poll)
    _db.session.delete(night)
    _db.session.commit()


def test_create_date_poll_route_and_pick(admin_client, make_person):
    ann = make_person("Ann")
    resp = admin_client.post(
        "/polls/create",
        data={
            "kind": "dates",
            "title": "Date route poll",
            "start_date": "2031-05-01",
            "end_date": "2031-05-10",
            "weekdays": ["4", "5"],
        },
    )
    assert resp.status_code == 302
    poll = Poll.query.filter_by(title="Date route poll").one()
    assert poll.date_poll and len(poll.options) == 4

    client = admin_client.application.test_client()
    login(client, ann)
    page = client.get(f"/poll/{poll.token}").get_data(as_text=True)
    assert f'name="answer_{poll.options[0].id}"' in page
    resp = client.post(f"/poll/{poll.token}/respond", data={f"answer_{poll.options[0].id}": "yes"})
    assert "Who&#39;s free" in resp.get_data(as_text=True) or "Who's free" in resp.get_data(
        as_text=True
    )

    from flask import g

    g.pop("_login_user", None)  # two clients share one app context; see conftest
    page = admin_client.get(f"/polls/{poll.id}/results").get_data(as_text=True)
    assert "Pick this date" in page and "Ann" in page
    resp = admin_client.post(f"/polls/{poll.id}/pick/{poll.options[0].id}")
    assert "/edit" in resp.headers["Location"]
    night = poll.picked_game_night
    _db.session.delete(night.availability_poll)
    _db.session.delete(poll)
    _db.session.delete(night)
    _db.session.commit()
