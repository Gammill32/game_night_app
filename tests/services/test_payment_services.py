import datetime
from types import SimpleNamespace

import pytest

from app.models import PaymentHandle
from app.services import payment_services
from tests.conftest import login


@pytest.mark.parametrize(
    "kind,raw,value",
    [
        ("venmo", "@Sam-Smith-12", "Sam-Smith-12"),
        ("venmo", "https://venmo.com/u/Sam-Smith-12", "Sam-Smith-12"),
        ("cashapp", "$SamS", "SamS"),
        ("cashapp", "https://cash.app/$SamS", "SamS"),
        ("paypal", "paypal.me/samsmith", "samsmith"),
        ("zelle", "Sam@Example.com", "sam@example.com"),
        ("zelle", "+1 312-555-0199", "(312) 555-0199"),
        ("applecash", "312.555.0199", "(312) 555-0199"),
    ],
)
def test_handles_are_normalized(kind, raw, value):
    assert payment_services.normalize(kind, raw) == (value, None)


@pytest.mark.parametrize(
    "kind,raw",
    [
        ("venmo", "sam smith"),
        ("cashapp", "$12345"),
        ("zelle", "nope"),
        ("applecash", "555"),
        ("paypal", ""),
    ],
)
def test_bad_handles_are_rejected(kind, raw):
    value, error = payment_services.normalize(kind, raw)
    assert value is None and error


def test_pay_links_prefill_the_amount():
    note = payment_services.note_for(SimpleNamespace(date=datetime.date(2026, 10, 4)))
    assert note == "Game Night 10/4 food"
    h = lambda kind, value: PaymentHandle(kind=kind, value=value)  # noqa: E731
    assert payment_services.pay_link(h("venmo", "Sam-Smith"), 1250, note) == (
        "https://venmo.com/Sam-Smith?txn=pay&amount=12.50&note=Game%20Night%2010%2F4%20food",
        True,
    )
    assert (
        payment_services.pay_link(h("cashapp", "SamS"), 700, note)[0]
        == "https://cash.app/$SamS/7.00"
    )
    assert payment_services.pay_link(h("paypal", "samsmith"), 1999, note)[0] == (
        "https://paypal.me/samsmith/19.99USD"
    )
    assert payment_services.pay_link(h("zelle", "sam@example.com"), 100, note) == (None, False)


def test_preferred_handles(make_person):
    sam = make_person("Sam")
    assert payment_services.add_handle(sam, "zelle", "sam@example.com")[0]
    assert sam.payment_handles[0].preferred  # the first one is preferred
    assert payment_services.add_handle(sam, "venmo", "@Sam-S", preferred=True)[0]
    assert [h.kind for h in sam.payment_handles if h.preferred] == ["venmo"]
    assert not payment_services.add_handle(sam, "venmo", "Sam-S")[0]  # duplicate
    opts = payment_services.options_for(sam, 500, "Game Night 1/1 food")
    assert sorted(o["kind"] for o in opts) == ["venmo", "zelle"]
    venmo = next(h for h in sam.payment_handles if h.kind == "venmo")
    assert payment_services.delete_handle(sam, venmo.id)[0]
    assert sam.payment_handles[0].preferred  # the remaining one takes over
    other = make_person("Other")
    assert not payment_services.set_preferred(other, sam.payment_handles[0].id)[0]


def test_profile_page_adds_and_removes_handles(client, make_person):
    sam = make_person("Sam")
    login(client, sam)
    assert "Payment Methods" in client.get("/manage_user").get_data(as_text=True)
    client.post("/manage_user/payment", data={"kind": "cashapp", "value": "$Sam1"})
    page = client.get("/manage_user").get_data(as_text=True)
    assert "$Sam1" in page
    h = sam.payment_handles[0]
    client.post(f"/manage_user/payment/{h.id}", data={"action": "delete"})
    assert sam.payment_handles == []
