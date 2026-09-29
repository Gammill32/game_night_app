from app.models import (
    FoodExpense,
    Person,
    Player,
    Poll,
    PollResponse,
    db,
)


def get_all_people():
    """Active people, by last name — for pickers and the admin list."""
    return Person.query.filter_by(active=True).order_by(Person.last_name, Person.first_name).all()


def get_inactive_people():
    return Person.query.filter_by(active=False).order_by(Person.last_name, Person.first_name).all()


def toggle_admin_status(user_id):
    """Toggle the admin status of a user. Owners cannot be demoted."""
    user = db.session.get(Person, user_id)
    if not user:
        return False, "User not found."

    if user.owner:
        return False, "Owner accounts cannot have admin status changed."
    if not user.active:
        return False, "Restore this person before making them an admin."

    user.admin = not user.admin
    action = "promoted to" if user.admin else "demoted from"
    db.session.commit()

    return True, f"{user.first_name} {user.last_name} has been {action} admin."


def has_history(person):
    """Anything that should outlive the person: attendance (and so results,
    nominations and votes), poll answers or polls, food costs."""
    return any(
        q.first() is not None
        for q in (
            Player.query.filter_by(people_id=person.id),
            PollResponse.query.filter_by(person_id=person.id),
            Poll.query.filter_by(created_by=person.id),
            FoodExpense.query.filter(
                db.or_(FoodExpense.paid_by == person.id, FoodExpense.created_by == person.id)
            ),
        )
    )


def remove_user(user_id, current_user_id):
    """Remove a user. Cannot remove self or owner accounts.

    Someone with history is deactivated: their login is cleared (email,
    password, admin) and they drop out of pickers, but past game nights keep
    them. Someone with no history is deleted outright."""
    user = db.session.get(Person, user_id)
    if not user:
        return False, "User not found."

    if user.id == current_user_id:
        return False, "You cannot remove yourself."

    if user.owner:
        return False, "Owner accounts cannot be removed."

    name = f"{user.first_name} {user.last_name}"
    if has_history(user):
        user.active = False
        user.email = None
        user.password = None
        user.admin = False
        user.temp_pass = False
        user.temp_pass_expires_at = None
        db.session.commit()
        return (
            True,
            f"{name} has been deactivated: they can't log in and won't show up in lists, "
            "but past game nights keep their results.",
        )

    db.session.delete(user)
    db.session.commit()
    return True, f"{name} has been removed."


def restore_user(user_id):
    """Reactivate someone. They sign up again (by name) to set a new login."""
    user = db.session.get(Person, user_id)
    if not user or user.active:
        return False, "User not found."
    user.active = True
    db.session.commit()
    return True, f"{user.first_name} {user.last_name} is back; they can sign up again by name."


def add_person(first_name, last_name):
    """Add a new person to the system."""
    first_name, last_name = (first_name or "").strip(), (last_name or "").strip()
    if not first_name or not last_name:
        return False, "Both first name and last name are required."

    # Signup claims an account by exact name, so names must be unique.
    existing = Person.query.filter(
        db.func.lower(Person.first_name) == first_name.lower(),
        db.func.lower(Person.last_name) == last_name.lower(),
    ).first()
    if existing:
        if not existing.active:
            return False, f"{first_name} {last_name} was deactivated; restore them instead."
        return False, f"{first_name} {last_name} is already in the system."

    person = Person(first_name=first_name, last_name=last_name)
    db.session.add(person)
    db.session.commit()

    return True, f"{first_name} {last_name} added. They can now sign up with that name."
