"""Food on a game night (ported from Poker Night's host & food feature).

Each night has a food mode:
  * none — nothing shown;
  * provided — someone (usually the admin who set up the night) has it
    covered, with an optional note like "tacos";
  * signup — a list of who's bringing what: admins add items for people to
    claim, and players add what they're bringing;
  * split — someone buys the food and logs the cost (optional receipt photo);
    it's split evenly among the people it covers, and everyone who owes the
    buyer gets pay links built from the buyer's payment methods. The debtor,
    the buyer or an admin ticks each share paid;
  * both — sign-up list and split costs.

The list and the costs can be changed until the night is finalized; shares
can be marked paid at any time.
"""

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models import FOOD_MODES, FoodExpense, FoodExpenseShare, FoodItem, Person, Player
from app.services import media_services, payment_services, poll_services

FOOD_MODE_LABELS = {
    "none": "No food plans",
    "provided": "Provided",
    "signup": "Sign-up list",
    "split": "Split the cost",
    "both": "Sign-up list + split the cost",
}


class FoodError(ValueError):
    pass


def money(cents):
    return f"${cents // 100:,}.{cents % 100:02d}"


def parse_money(raw):
    """ "$12.50", "12.5" or "12" → cents. Raises FoodError."""
    text = re.sub(r"[\s$,]", "", raw or "")
    try:
        amount = Decimal(text)
    except InvalidOperation:
        raise FoodError("Enter the amount in dollars, like 45.00.") from None
    if amount <= 0 or amount != amount.quantize(Decimal("0.01")):
        raise FoodError("Enter the amount in dollars, like 45.00.")
    if amount > 10000:
        raise FoodError("That's more than $10,000 — check the amount.")
    return int(amount * 100)


# ---------------------------------------------------------------------------
# Who can do what
# ---------------------------------------------------------------------------


def player_ids(game_night):
    return {p.people_id for p in Player.query.filter_by(game_night_id=game_night.id)}


def is_player(game_night, user):
    return user.id in player_ids(game_night)


def food_open(game_night):
    """The list and costs can change until the night is finalized."""
    return not game_night.final


# ---------------------------------------------------------------------------
# Food mode (set from the start / edit night forms)
# ---------------------------------------------------------------------------


def parse_food_settings(form, default_provider_id):
    """(mode, provider_id, note) from a night form. Raises FoodError."""
    mode = form.get("food_mode") or "none"
    if mode not in FOOD_MODES:
        raise FoodError("Pick a food option.")
    provider_id = None
    note = (form.get("food_note") or "").strip()[:120] or None
    if mode == "provided":
        raw = form.get("food_provider_id") or ""
        provider_id = int(raw) if raw.isdigit() else default_provider_id
        if db.session.get(Person, provider_id) is None:
            raise FoodError("Pick who's providing the food.")
    return mode, provider_id, note


def apply_food_settings(game_night, mode, provider_id, note):
    game_night.food_mode = mode
    game_night.food_provider_id = provider_id
    game_night.food_note = note


# ---------------------------------------------------------------------------
# Sign-up list
# ---------------------------------------------------------------------------


def add_item(game_night, user, name, claim=False):
    if not game_night.food_signup:
        return False, "This night doesn't have a food sign-up list."
    if not food_open(game_night):
        return False, "This game night is finalized."
    name = (name or "").strip()[:80]
    if not name:
        return False, "Say what the item is, e.g. chips or a 12-pack."
    item = FoodItem(game_night_id=game_night.id, name=name, added_by=user.id)
    # Players adding something are bringing it; admins adding items build a
    # list for others to claim unless they tick "I'm bringing it".
    if claim or not user.is_admin_or_owner:
        item.claimed_by = user.id
    db.session.add(item)
    db.session.commit()
    if item.claimed_by == user.id:
        return True, f"Added: you're bringing {name}."
    return True, f"Added {name} to the list."


def claim_item(game_night, item, user, claim=True):
    if not food_open(game_night):
        return False, "This game night is finalized."
    if not is_player(game_night, user):
        return False, "Only players at this game night can sign up."
    db.session.query(FoodItem).filter_by(id=item.id).with_for_update().one()
    db.session.refresh(item)
    if claim:
        if item.claimed_by and item.claimed_by != user.id:
            return False, f"{item.claimer.first_name} is already bringing that."
        item.claimed_by = user.id
        db.session.commit()
        return True, f"You're bringing {item.name}."
    if item.claimed_by != user.id:
        return False, "You haven't signed up for that."
    item.claimed_by = None
    db.session.commit()
    return True, f"You're no longer bringing {item.name}."


def delete_item(game_night, item, user):
    if not food_open(game_night):
        return False, "This game night is finalized."
    if not (user.is_admin_or_owner or item.added_by == user.id):
        return False, "Only an admin or whoever added it can remove it."
    db.session.delete(item)
    db.session.commit()
    return True, f"Removed {item.name}."


# ---------------------------------------------------------------------------
# Split costs
# ---------------------------------------------------------------------------


def default_covered(game_night):
    """Players who said they can make it on the availability poll, or every
    player if nobody has said so (or there's no poll)."""
    players = player_ids(game_night)
    rsvps = poll_services.rsvps_for_night(game_night)
    coming = {pid for pid in players if rsvps.get(pid) == "Can Make It"}
    return coming or players


def coverable(game_night):
    """Everyone a cost can be split among or paid by: the night's players."""
    people = [
        p.person
        for p in Player.query.filter_by(game_night_id=game_night.id).join(Player.person).all()
    ]
    return sorted(people, key=lambda p: (p.first_name.lower(), p.last_name.lower()))


def split(amount_cents, covered_ids):
    """{person_id: share}: an even split, with leftover cents going one each to
    the lowest ids so the shares add up exactly."""
    ids = sorted(covered_ids)
    base, extra = divmod(amount_cents, len(ids))
    return {pid: base + (1 if n < extra else 0) for n, pid in enumerate(ids)}


def _set_shares(expense, covered_ids):
    """Replace an expense's shares. The buyer's own share is already paid."""
    previously_paid = {s.person_id for s in expense.shares if s.paid}
    expense.shares.clear()
    db.session.flush()  # delete the old rows before inserting, for the unique constraint
    now = datetime.utcnow()
    for pid, cents in split(expense.amount_cents, covered_ids).items():
        paid = pid == expense.paid_by or pid in previously_paid
        expense.shares.append(
            FoodExpenseShare(
                person_id=pid, amount_cents=cents, paid=paid, paid_at=now if paid else None
            )
        )


def _parse_covered(game_night, form):
    allowed = player_ids(game_night)
    ids = {int(x) for x in form.getlist("covered") if str(x).isdigit()} & allowed
    if not ids:
        raise FoodError("Pick at least one person to split it between.")
    return ids


def can_edit_expense(expense, user):
    return user.is_admin_or_owner or expense.created_by == user.id


def add_expense(game_night, user, form, receipt=None):
    if not game_night.food_split:
        return False, "This night doesn't split food costs."
    if not food_open(game_night):
        return False, "This game night is finalized."
    try:
        description = (form.get("description") or "").strip()[:120]
        if not description:
            raise FoodError("Say what it was, e.g. pizza or drinks.")
        amount = parse_money(form.get("amount"))
        raw_payer = form.get("paid_by") or str(user.id)
        if not raw_payer.isdigit() or int(raw_payer) not in player_ids(game_night):
            raise FoodError("Pick who paid from the list of players.")
        covered = (
            _parse_covered(game_night, form)
            if form.get("covered_set")
            else default_covered(game_night)
        )
        if not covered:
            raise FoodError("This night has no players to split it between.")
        receipt_path = None
        if receipt is not None and receipt.filename:
            receipt_path, _ = media_services.save_image(receipt, f"receipts/{game_night.id}", 2000)
    except (FoodError, media_services.MediaError) as e:
        return False, str(e)
    expense = FoodExpense(
        game_night_id=game_night.id,
        description=description,
        amount_cents=amount,
        paid_by=int(raw_payer),
        receipt_path=receipt_path,
        created_by=user.id,
    )
    db.session.add(expense)
    _set_shares(expense, covered)
    db.session.commit()
    return True, f"Logged {money(amount)} for {description}, split {len(covered)} ways."


def set_covered(game_night, expense, user, form):
    if not food_open(game_night):
        return False, "This game night is finalized."
    if not can_edit_expense(expense, user):
        return False, "Only whoever logged it or an admin can change who it covers."
    try:
        covered = _parse_covered(game_night, form)
    except FoodError as e:
        return False, str(e)
    _set_shares(expense, covered)
    db.session.commit()
    return True, f"{expense.description} is now split {len(covered)} ways."


def delete_expense(game_night, expense, user):
    if not food_open(game_night):
        return False, "This game night is finalized."
    if not can_edit_expense(expense, user):
        return False, "Only whoever logged it or an admin can remove it."
    media_services.delete(expense.receipt_path)
    db.session.delete(expense)
    db.session.commit()
    return True, f"Removed {expense.description}."


def set_paid(share, user, paid=True):
    """The person who owes, the buyer, or an admin can tick a share paid."""
    expense = share.expense
    if share.person_id == expense.paid_by:
        return False, "That's the buyer's own share."
    if not (user.is_admin_or_owner or user.id in (share.person_id, expense.paid_by)):
        return False, "Only the person who owes it, the buyer or an admin can change that."
    share.paid = paid
    share.paid_at = datetime.utcnow() if paid else None
    db.session.commit()
    if not paid:
        return True, f"{share.person.first_name}'s share of {expense.description} is unpaid again."
    who = "You" if share.person_id == user.id else share.person.first_name
    return True, f"{who} paid {expense.payer.first_name} {money(share.amount_cents)}."


def files_for_night(game_night):
    return [e.receipt_path for e in game_night.food_expenses if e.receipt_path]


# ---------------------------------------------------------------------------
# What the night page shows
# ---------------------------------------------------------------------------


def expense_rows(game_night, user):
    """For each expense: the shares (with pay options for the viewer's own
    unpaid share) and who's still outstanding."""
    note = payment_services.note_for(game_night)
    rows = []
    for expense in game_night.food_expenses:
        shares = []
        for share in sorted(expense.shares, key=lambda s: s.person.first_name.lower()):
            is_buyer = share.person_id == expense.paid_by
            mine = share.person_id == user.id
            shares.append(
                {
                    "share": share,
                    "is_buyer": is_buyer,
                    "mine": mine,
                    "can_toggle": not is_buyer
                    and (user.is_admin_or_owner or user.id in (share.person_id, expense.paid_by)),
                    "pay_options": payment_services.options_for(
                        expense.payer, share.amount_cents, note
                    )
                    if mine and not share.paid and not is_buyer
                    else [],
                }
            )
        outstanding = sum(
            s.amount_cents for s in expense.shares if not s.paid and s.person_id != expense.paid_by
        )
        rows.append({"expense": expense, "shares": shares, "outstanding": outstanding})
    return rows


def my_food_summary(game_night, user):
    """[(share, expense)] the viewer still owes on this night."""
    return [
        (s, e)
        for e in game_night.food_expenses
        for s in e.shares
        if s.person_id == user.id and not s.paid and s.person_id != e.paid_by
    ]


def owed_to(game_night, user):
    """Unpaid shares other people owe this user (as the buyer) on this night."""
    return [
        s
        for e in game_night.food_expenses
        if e.paid_by == user.id
        for s in e.shares
        if not s.paid and s.person_id != user.id
    ]


def reminder_lines(game_night):
    """Plain lines for the reminder email."""
    lines = []
    if game_night.food_mode == "provided":
        who = game_night.food_provider.first_name if game_night.food_provider else "Someone"
        lines.append(
            f"{who} is providing food{': ' + game_night.food_note if game_night.food_note else ''}."
        )
    elif game_night.food_mode != "none" and game_night.food_note:
        lines.append(game_night.food_note)
    if game_night.food_signup:
        for item in game_night.food_items:
            who = item.claimer.first_name if item.claimer else "nobody yet — can you bring it?"
            lines.append(f"{item.name}: {who}")
    if game_night.food_split:
        lines.append("Food costs are split; log what you buy on the game night page.")
    return lines
