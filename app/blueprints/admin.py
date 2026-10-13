from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.services import admin_services, auth_services
from app.utils import admin_required, flash_if_no_action, owner_required
from app.utils.decorators import host_required

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin", methods=["GET"])
@login_required
@admin_required
def admin_page():
    """Displays the admin panel with a list of users."""
    context = {
        "people": admin_services.get_all_people(),
        "inactive_people": admin_services.get_inactive_people(),
        "invite_link": auth_services.invite_link,
    }
    return render_template("admin_page.html", **context)


@admin_bp.route("/invites", methods=["GET"])
@login_required
@host_required
def invites():
    """Invite links for people who haven't signed up yet: admins see everyone,
    hosts see the guests on nights they host."""
    context = {
        "people": auth_services.invitable_people(current_user),
        "invite_link": auth_services.invite_link,
    }
    return render_template("invite_people.html", **context)


@admin_bp.route("/toggle_admin_status/<int:user_id>", methods=["POST"])
@login_required
@owner_required
def toggle_admin_status(user_id):
    """Toggles the admin status of a user."""
    success, message = admin_services.toggle_admin_status(user_id)
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.admin_page"))


@admin_bp.route("/toggle_can_host/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def toggle_can_host(user_id):
    success, message = admin_services.toggle_can_host(user_id)
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.admin_page"))


@admin_bp.route("/remove_user/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def remove_user(user_id):
    """Removes a user from the system (only by an admin)."""
    success, message = admin_services.remove_user(user_id, current_user.id)
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.admin_page"))


@admin_bp.route("/restore_user/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def restore_user(user_id):
    success, message = admin_services.restore_user(user_id)
    flash(message, "success" if success else "error")
    return redirect(url_for("admin.admin_page"))


@admin_bp.route("/add_person", methods=["GET", "POST"])
@login_required
@admin_required
@flash_if_no_action("Both first name and last name are required.", "error")
def add_person():
    """Allows admins to manually add a new person to the system."""
    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()

        success, message, person = admin_services.create_person(first_name, last_name)
        flash(message, "success" if success else "error")
        if success:
            return redirect(url_for("admin.admin_page") + f"#person-{person.id}")
        return redirect(url_for("admin.add_person"))

    context = {}
    return render_template("add_person.html", **context)
