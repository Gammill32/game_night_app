# blueprints/auth.py

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from app.services import auth_services, payment_services
from app.utils import flash_if_no_action

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password")

        success, message, user = auth_services.login(email, password)

        if success:
            login_user(user)
            if user.temp_pass:
                flash("Please update your password.", "warning")
                return redirect(url_for("auth.update_password"))
            next_url = request.args.get("next") or ""
            if next_url and (not next_url.startswith("/") or next_url.startswith("//")):
                next_url = ""
            return redirect(next_url or url_for("main.index"))
        else:
            flash(message, "error")

    context = {}
    return render_template("login.html", **context)


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))


@auth_bp.route("/signup", methods=["GET", "POST"])
@flash_if_no_action("Please provide all required fields to sign up.", "error")
def signup():
    if request.method == "POST":
        first_name = request.form.get("first_name")
        last_name = request.form.get("last_name")
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password")

        success, message = auth_services.signup(first_name, last_name, email, password)
        flash(message, "success" if success else "error")

        if success:
            return redirect(url_for("auth.login"))

    context = {}
    return render_template("signup.html", **context)


@auth_bp.route("/forgot_password", methods=["GET", "POST"])
@flash_if_no_action("Please enter your email address to reset your password.", "error")
def forgot_password():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        success, message = auth_services.forgot_password(email)
        flash(message, "success" if success else "error")

        if success:
            return redirect(url_for("auth.login"))

    context = {}
    return render_template("forgot_password.html", **context)


@auth_bp.route("/reset_password/<token>", methods=["GET", "POST"])
def reset_password(token):
    user = auth_services.user_for_reset_token(token)
    if user is None:
        flash("That reset link has expired or was already used. Ask for a new one.", "error")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        success, message = auth_services.reset_password(
            user, request.form.get("new_password"), request.form.get("confirm_password")
        )
        flash(message, "success" if success else "error")
        if success:
            return redirect(url_for("auth.login"))
    return render_template("reset_password.html", person=user)


@auth_bp.route("/update_password", methods=["GET", "POST"])
@login_required
def update_password():
    if request.method == "POST":
        current_password = request.form.get("current_password")
        new_password = request.form.get("new_password")
        confirm_password = request.form.get("confirm_password")

        success, message = auth_services.update_password(
            current_user, current_password, new_password, confirm_password
        )
        flash(message, "success" if success else "error")

        if success:
            return redirect(url_for("main.index"))

    context = {}
    return render_template("update_password.html", **context)


@auth_bp.route("/manage_user", methods=["GET", "POST"])
@login_required
def manage_user():
    """Profile: account settings and payment methods; POST updates email/password."""
    user = current_user

    if request.method == "POST":
        success, message = auth_services.update_profile(
            user,
            request.form.get("current_password"),
            request.form.get("email"),
            request.form.get("new_password"),
            request.form.get("confirm_password"),
        )
        flash(message, "success" if success else "error")
        return redirect(url_for("auth.manage_user"))

    context = {
        "person": user,
        "payment_labels": payment_services.LABELS,
        "payment_placeholders": payment_services.PLACEHOLDERS,
        "payment_display": payment_services.display,
    }
    return render_template("manage_user.html", **context)


@auth_bp.route("/manage_user/payment", methods=["POST"])
@login_required
def add_payment():
    success, message = payment_services.add_handle(
        current_user,
        request.form.get("kind", ""),
        request.form.get("value", ""),
        preferred=request.form.get("preferred") == "1",
    )
    flash(message, "success" if success else "error")
    return redirect(url_for("auth.manage_user") + "#payment")


@auth_bp.route("/manage_user/payment/<int:handle_id>", methods=["POST"])
@login_required
def edit_payment(handle_id):
    if request.form.get("action") == "delete":
        success, message = payment_services.delete_handle(current_user, handle_id)
    else:
        success, message = payment_services.set_preferred(current_user, handle_id)
    flash(message, "success" if success else "error")
    return redirect(url_for("auth.manage_user") + "#payment")
