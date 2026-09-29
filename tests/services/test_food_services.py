from werkzeug.datastructures import MultiDict

from app.extensions import db as _db
from app.models import FoodExpense, FoodItem
from app.services import food_services, payment_services
from app.services.poll_services import create_availability_poll, submit_response
from tests.conftest import login


def test_split_adds_up_exactly():
    shares = food_services.split(1000, {7, 3, 5})
    assert shares == {3: 334, 5: 333, 7: 333}
    assert sum(shares.values()) == 1000


def test_parse_money():
    assert food_services.parse_money("$45") == 4500
    assert food_services.parse_money("12.5") == 1250
    assert food_services.parse_money("1,234.56") == 123456
    for bad in ("", "abc", "-3", "0", "1.234"):
        try:
            food_services.parse_money(bad)
        except food_services.FoodError:
            continue
        raise AssertionError(bad)


def test_signup_list_claims(make_person, make_night):
    admin, ann, bo = make_person("Adm", admin=True), make_person("Ann"), make_person("Bo")
    gn = make_night(ann, bo, food_mode="signup")

    ok, _ = food_services.add_item(gn, admin, "Chips")
    assert ok
    chips = FoodItem.query.filter_by(game_night_id=gn.id, name="Chips").one()
    assert chips.claimed_by is None  # admin builds the list

    assert food_services.add_item(gn, bo, "Salsa")[0]
    assert FoodItem.query.filter_by(name="Salsa", game_night_id=gn.id).one().claimed_by == bo.id

    assert food_services.claim_item(gn, chips, ann)[0]
    ok, msg = food_services.claim_item(gn, chips, bo)
    assert not ok and "Ann" in msg
    assert not food_services.delete_item(gn, chips, bo)[0]  # not the adder or an admin
    assert food_services.claim_item(gn, chips, ann, claim=False)[0]
    assert chips.claimed_by is None

    gn.final = True
    _db.session.commit()
    assert not food_services.add_item(gn, ann, "Soda")[0]


def test_split_cost_defaults_to_rsvp_in_and_tracks_payment(make_person, make_night):
    ann, bo, cy = make_person("Ann"), make_person("Bo"), make_person("Cy")
    gn = make_night(ann, bo, cy, food_mode="split")
    ok, _ = create_availability_poll(gn.id, ann.id)
    poll = gn.availability_poll
    submit_response(poll, [poll.options[0].id], ann.id)  # can make it
    submit_response(poll, [poll.options[0].id], bo.id)  # can make it
    submit_response(poll, [poll.options[2].id], cy.id)  # can't

    ok, msg = food_services.add_expense(
        gn, ann, MultiDict({"description": "Pizza", "amount": "30.01", "paid_by": str(ann.id)})
    )
    assert ok, msg
    expense = FoodExpense.query.filter_by(game_night_id=gn.id).one()
    shares = {s.person_id: s for s in expense.shares}
    assert set(shares) == {ann.id, bo.id}  # Cy said no
    assert shares[ann.id].amount_cents + shares[bo.id].amount_cents == 3001
    assert shares[ann.id].paid  # the buyer's own share

    # Bo sees pay links to Ann's Venmo with the amount filled in
    payment_services.add_handle(ann, "venmo", "@Ann-T")
    rows = food_services.expense_rows(gn, bo)
    bo_row = next(s for s in rows[0]["shares"] if s["mine"])
    assert bo_row["pay_options"][0]["url"].startswith("https://venmo.com/Ann-T?txn=pay&amount=15.0")
    assert food_services.my_food_summary(gn, bo)

    assert not food_services.set_paid(shares[bo.id], cy)[0]  # a bystander can't
    assert food_services.set_paid(shares[bo.id], bo)[0]
    assert food_services.expense_rows(gn, bo)[0]["outstanding"] == 0
    assert not food_services.my_food_summary(gn, bo)


def test_changing_covered_keeps_paid_shares(make_person, make_night):
    ann, bo, cy = make_person("Ann"), make_person("Bo"), make_person("Cy")
    gn = make_night(ann, bo, cy, food_mode="split")
    food_services.add_expense(
        gn,
        ann,
        MultiDict(
            [
                ("description", "Wings"),
                ("amount", "20"),
                ("covered_set", "1"),
                ("covered", str(ann.id)),
                ("covered", str(bo.id)),
            ]
        ),
    )
    expense = FoodExpense.query.filter_by(game_night_id=gn.id).one()
    bo_share = next(s for s in expense.shares if s.person_id == bo.id)
    food_services.set_paid(bo_share, bo)

    form = MultiDict([("covered", str(ann.id)), ("covered", str(bo.id)), ("covered", str(cy.id))])
    assert not food_services.set_covered(gn, expense, cy, form)[0]  # not the logger
    assert food_services.set_covered(gn, expense, ann, form)[0]
    by_person = {s.person_id: s for s in expense.shares}
    assert len(by_person) == 3 and by_person[bo.id].paid and not by_person[cy.id].paid


def test_food_routes_and_page(client, make_person, make_night):
    ann, bo, outsider = make_person("Ann"), make_person("Bo"), make_person("Out")
    gn = make_night(ann, bo, food_mode="both", food_note="Taco night")
    login(client, bo)
    client.post(f"/game_night/{gn.id}/food/items", data={"name": "Guac"})
    client.post(
        f"/game_night/{gn.id}/food/expenses",
        data={"description": "Tortillas", "amount": "8", "paid_by": str(bo.id)},
    )
    page = client.get(f"/game_night/{gn.id}").get_data(as_text=True)
    assert "Taco night" in page and "Guac" in page and "Tortillas" in page

    login(client, outsider)
    resp = client.post(f"/game_night/{gn.id}/food/items", data={"name": "Nope"})
    assert resp.status_code == 302
    assert FoodItem.query.filter_by(game_night_id=gn.id, name="Nope").count() == 0


def test_start_night_with_provided_food(client, make_person):
    from app.models import GameNight

    admin, ann = make_person("Adm", admin=True), make_person("Ann")
    login(client, admin)
    resp = client.post(
        "/game_night/start",
        data={
            "date": "2031-01-02",
            "notes": "",
            "attendees": [str(ann.id)],
            "food_mode": "provided",
            "food_provider_id": str(admin.id),
            "food_note": "Chili",
        },
    )
    gn = GameNight.query.filter_by(food_note="Chili").one()
    assert resp.headers["Location"].endswith(f"/game_night/{gn.id}")
    assert gn.food_mode == "provided" and gn.food_provider_id == admin.id
    login(client, ann)
    page = client.get(f"/game_night/{gn.id}").get_data(as_text=True)
    assert "is providing food" in page and "Chili" in page
    _db.session.delete(gn)
    _db.session.commit()


def test_reminder_email_lists_food_and_what_you_owe(app, make_person, make_night, monkeypatch):
    import datetime

    import pytz

    from app.services import reminders_services

    ann, bo = make_person("Ann"), make_person("Bo")
    today = datetime.datetime.now(pytz.timezone(app.config["APP_TIMEZONE"])).date()
    gn = make_night(ann, bo, date=today, food_mode="both")
    food_services.add_item(gn, ann, "Chips")
    food_services.add_expense(
        gn, ann, MultiDict({"description": "Pizza", "amount": "20", "paid_by": str(ann.id)})
    )
    sent = {}
    monkeypatch.setattr(
        reminders_services, "send_email", lambda to, subject, body: sent.__setitem__(to, body)
    )
    reminders_services.check_and_send_reminders()
    assert "Chips: Ann" in sent[ann.email]
    assert "You owe Ann $10.00 for Pizza" in sent[bo.email]
