from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.services import admin_services
from app.utils import admin_required, flash_if_no_action

admin_bp = Blueprint("admin", __name__)


@admin_bp.route("/admin", methods=["GET"])
@login_required
@admin_required
def admin_page():
    """Displays the admin panel with a list of users."""
    people = admin_services.get_all_people()

    context = {"people": people}
    return render_template("admin_page.html", **context)


@admin_bp.route("/toggle_admin_status/<int:user_id>", methods=["POST"])
@login_required
@admin_required
def toggle_admin_status(user_id):
    """Toggles the admin status of a user."""
    success, message = admin_services.toggle_admin_status(user_id)
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


@admin_bp.route("/add_person", methods=["GET", "POST"])
@login_required
@admin_required
@flash_if_no_action("Both first name and last name are required.", "error")
def add_person():
    """Allows admins to manually add a new person to the system."""
    if request.method == "POST":
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()

        success, message = admin_services.add_person(first_name, last_name)
        flash(message, "success" if success else "error")
        return redirect(url_for("admin.add_person"))

    context = {}
    return render_template("add_person.html", **context)
