"""Payment methods and pay links.

People add the handles they like to be paid with on their profile and mark
one preferred. When a night splits a food cost, everyone who owes the buyer
sees the buyer's handles, preferred first:

  * Venmo — https://venmo.com/<username>?txn=pay&amount=12.50&note=...
    prefills the amount and note (opens the app on phones);
  * Cash App — https://cash.app/$<cashtag>/12.50 prefills the amount (Cash App
    links can't carry a note);
  * PayPal — https://paypal.me/<username>/12.50USD prefills the amount (no note);
  * Zelle and Apple Cash have no web pay links: show the email/phone to copy.

Opening a link never marks a share paid; people still tick Paid.
Ported from Poker Night (docs/poker_night_spec.md §18.5 in homelab-docs).
"""

import re
from urllib.parse import quote, urlencode

from app.extensions import db
from app.models import PAYMENT_KINDS, PaymentHandle

LABELS = {
    "venmo": "Venmo",
    "cashapp": "Cash App",
    "zelle": "Zelle",
    "paypal": "PayPal",
    "applecash": "Apple Cash",
}
PLACEHOLDERS = {
    "venmo": "@your-username",
    "cashapp": "$YourCashtag",
    "zelle": "email or phone",
    "paypal": "paypal.me/yourname",
    "applecash": "phone number",
}

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _phone(raw):
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        return None
    return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"


def normalize(kind, raw):
    """Clean up what someone typed. Returns (value, error)."""
    raw = (raw or "").strip()
    if not raw:
        return None, "Enter the handle."
    if kind == "venmo":
        value = re.sub(r"^(https?://)?(www\.)?venmo\.com/(u/)?", "", raw, flags=re.I).lstrip("@")
        if not re.fullmatch(r"[A-Za-z0-9_-]{2,30}", value):
            return None, "A Venmo username is letters, numbers, - and _, like @Sam-Smith-12."
        return value, None
    if kind == "cashapp":
        value = re.sub(r"^(https?://)?cash\.app/", "", raw, flags=re.I).lstrip("$")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", value) or not re.search(r"[A-Za-z]", value):
            return None, "A $Cashtag has up to 20 letters and numbers, with at least one letter."
        return value, None
    if kind == "paypal":
        value = re.sub(r"^(https?://)?(www\.)?paypal\.me/", "", raw, flags=re.I).strip("/")
        if not re.fullmatch(r"[A-Za-z0-9]{1,20}", value):
            return (
                None,
                "A PayPal.me name is up to 20 letters and numbers, from paypal.me/yourname.",
            )
        return value, None
    if kind == "zelle":
        if _EMAIL.match(raw):
            return raw.lower(), None
        phone = _phone(raw)
        return (phone, None) if phone else (None, "Enter the email or US phone number Zelle uses.")
    if kind == "applecash":
        phone = _phone(raw)
        return (phone, None) if phone else (None, "Enter the phone number Apple Cash uses.")
    return None, "Pick a payment method."


def add_handle(person, kind, raw, preferred=False):
    if kind not in PAYMENT_KINDS:
        return False, "Pick a payment method."
    value, error = normalize(kind, raw)
    if error:
        return False, error
    if any(h.kind == kind and h.value == value for h in person.payment_handles):
        return False, f"You already have that {LABELS[kind]}."
    handle = PaymentHandle(person_id=person.id, kind=kind, value=value)
    person.payment_handles.append(handle)
    if preferred or len(person.payment_handles) == 1:
        _make_preferred(person, handle)
    db.session.commit()
    return True, f"Added {LABELS[kind]} {display(handle)}."


def _make_preferred(person, handle):
    for h in person.payment_handles:
        h.preferred = h is handle


def set_preferred(person, handle_id):
    handle = _own(person, handle_id)
    if handle is None:
        return False, "That payment method isn't yours."
    _make_preferred(person, handle)
    db.session.commit()
    return True, f"{LABELS[handle.kind]} is now your preferred way to be paid."


def delete_handle(person, handle_id):
    handle = _own(person, handle_id)
    if handle is None:
        return False, "That payment method isn't yours."
    was_preferred = handle.preferred
    person.payment_handles.remove(handle)
    db.session.flush()
    if was_preferred and person.payment_handles:
        _make_preferred(person, person.payment_handles[0])
    db.session.commit()
    return True, f"Removed {LABELS[handle.kind]}."


def _own(person, handle_id):
    return next((h for h in person.payment_handles if h.id == handle_id), None)


def display(handle):
    if handle.kind == "venmo":
        return "@" + handle.value
    if handle.kind == "cashapp":
        return "$" + handle.value
    if handle.kind == "paypal":
        return "paypal.me/" + handle.value
    return handle.value


def note_for(game_night, what="food"):
    """The payment note, e.g. "Game Night 10/4 food"."""
    return f"Game Night {game_night.date.month}/{game_night.date.day} {what}"


def _dollars(cents):
    return f"{cents // 100}.{cents % 100:02d}"


def pay_link(handle, amount_cents, note):
    """(url, prefills_amount) or (None, False) where no web link exists."""
    amount = _dollars(amount_cents)
    if handle.kind == "venmo":
        query = urlencode({"txn": "pay", "amount": amount, "note": note}, quote_via=quote)
        return f"https://venmo.com/{quote(handle.value)}?{query}", True
    if handle.kind == "cashapp":
        return f"https://cash.app/${quote(handle.value)}/{amount}", True
    if handle.kind == "paypal":
        return f"https://paypal.me/{quote(handle.value)}/{amount}USD", True
    return None, False


def options_for(person, amount_cents, note):
    """Everything settle-up shows for paying `person`, preferred first:
    [{kind, label, display, url, preferred}]."""
    if person is None:
        return []
    rows = []
    for h in sorted(person.payment_handles, key=lambda h: (not h.preferred, h.id or 0)):
        url, _ = pay_link(h, amount_cents, note)
        rows.append(
            {
                "kind": h.kind,
                "label": LABELS[h.kind],
                "display": display(h),
                "copy_text": display(h) if h.kind in ("venmo", "cashapp") else h.value,
                "url": url,
                "preferred": h.preferred,
            }
        )
    return rows
