from app.models import Person, db


def get_all_people():
    """Fetch all people from the database."""
    return Person.query.order_by(Person.last_name).all()


def toggle_admin_status(user_id):
    """Toggle the admin status of a user."""
    user = Person.query.get(user_id)
    if not user:
        return False, "User not found."

    user.admin = not user.admin
    action = "promoted to" if user.admin else "demoted from"
    db.session.commit()

    return True, f"{user.first_name} {user.last_name} has been {action} admin."


def remove_user(user_id, current_user_id):
    """Remove a user from the system if they are not the current user."""
    user = Person.query.get(user_id)
    if not user:
        return False, "User not found."

    if user.id == current_user_id:
        return False, "You cannot remove yourself."

    db.session.delete(user)
    db.session.commit()

    return True, f"{user.first_name} {user.last_name} has been removed."


def add_person(first_name, last_name):
    """Add a new person to the system."""
    if not first_name or not last_name:
        return False, "Both first name and last name are required."

    person = Person(first_name=first_name, last_name=last_name)
    db.session.add(person)
    db.session.commit()

    return True, "Person added successfully."
