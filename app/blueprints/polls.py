from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from flask_login import current_user, login_required
from sqlalchemy.orm import selectinload

from app.services.poll_services import (
    create_poll,
    get_poll_by_token,
    get_results,
    poll_is_active,
    submit_response,
    update_poll,
)
from app.utils import admin_required

polls_bp = Blueprint("polls", __name__)


@polls_bp.app_context_processor
def inject_active_polls():
    """Make active poll count and list available in all templates.

    Private polls are only visible to their invitees and to admins/owners.
    """
    from app.models import Poll

    try:
        all_open = Poll.query.filter_by(closed=False).options(selectinload(Poll.invitees)).all()
        active_all = [p for p in all_open if poll_is_active(p)]

        is_admin = current_user.is_authenticated and (current_user.admin or current_user.owner)
        user_id = current_user.id if current_user.is_authenticated else None

        def _visible(poll: Poll) -> bool:
            if not poll.private:
                return True
            if is_admin:
                return True
            if user_id is None:
                return False
            return any(inv.person_id == user_id for inv in poll.invitees)  # type: ignore[attr-defined]

        active = [p for p in active_all if _visible(p)]
        return {"active_polls_count": len(active), "active_polls": active}
    except Exception:
        return {"active_polls_count": 0, "active_polls": []}


# ── Admin routes ─────────────────────────────────────────────────────────── #


@polls_bp.route("/polls/")
@login_required
@admin_required
def poll_list():
    from app.models import Poll

    polls = Poll.query.order_by(Poll.created_at.desc()).all()
    return render_template("poll_list.html", polls=polls)


@polls_bp.route("/polls/create", methods=["GET", "POST"])
@login_required
@admin_required
def poll_create():
    from app.models import Person

    people = Person.query.order_by(Person.first_name).all()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        option_labels = [
            label.strip() for label in request.form.getlist("option_labels") if label.strip()
        ]
        multi_select = request.form.get("multi_select") == "true"
        private = request.form.get("private") == "true"
        invitee_ids = [int(i) for i in request.form.getlist("invitee_ids") if i.isdigit()]

        if not title or len(option_labels) < 2:
            return render_template(
                "poll_create.html",
                people=people,
                error="A title and at least two options are required.",
            )

        create_poll(
            title,
            description,
            option_labels,
            current_user.id,
            multi_select,
            private=private,
            invitee_ids=invitee_ids if private else None,
        )
        return redirect(url_for("polls.poll_list"))

    return render_template("poll_create.html", people=people)


@polls_bp.route("/polls/<int:poll_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def poll_edit(poll_id: int):
    from app.models import Person, Poll

    poll = Poll.query.get_or_404(poll_id)
    people = Person.query.order_by(Person.first_name).all()

    if request.method == "POST":
        from datetime import datetime

        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        multi_select = request.form.get("multi_select") == "true"
        private = request.form.get("private") == "true"
        invitee_ids = [int(i) for i in request.form.getlist("invitee_ids") if i.isdigit()]

        closes_at_str = request.form.get("closes_at", "").strip()
        closes_at = None
        if closes_at_str:
            try:
                closes_at = datetime.fromisoformat(closes_at_str)
            except ValueError:
                return render_template(
                    "poll_edit.html",
                    poll=poll,
                    people=people,
                    error="Invalid close date format. Please use the date picker.",
                )

        option_updates: dict[int, str] = {}
        for key, val in request.form.items():
            if key.startswith("option_label_"):
                try:
                    opt_id = int(key.removeprefix("option_label_"))
                    option_updates[opt_id] = val
                except ValueError:
                    pass

        if not title:
            return render_template(
                "poll_edit.html", poll=poll, people=people, error="Title is required."
            )

        update_poll(
            poll,
            title=title,
            description=description,
            closes_at=closes_at,
            multi_select=multi_select,
            private=private,
            invitee_ids=invitee_ids if private else None,
            option_updates=option_updates,
        )
        flash("Poll updated.", "success")
        return redirect(url_for("polls.poll_list"))

    return render_template("poll_edit.html", poll=poll, people=people)


@polls_bp.route("/polls/<int:poll_id>/close", methods=["POST"])
@login_required
@admin_required
def poll_close(poll_id: int):
    from app.extensions import db
    from app.models import Poll

    poll = Poll.query.get_or_404(poll_id)
    poll.closed = True
    db.session.commit()
    return redirect(url_for("polls.poll_list"))


@polls_bp.route("/polls/<int:poll_id>/delete", methods=["POST"])
@login_required
@admin_required
def poll_delete(poll_id: int):
    from app.extensions import db
    from app.models import Poll

    poll = Poll.query.get_or_404(poll_id)
    db.session.delete(poll)
    db.session.commit()
    flash("Poll deleted.", "success")
    return redirect(url_for("polls.poll_list"))


@polls_bp.route("/polls/<int:poll_id>/share", methods=["GET", "POST"])
@login_required
@admin_required
def poll_share(poll_id: int):
    from flask_mail import Message

    from app.extensions import mail
    from app.models import Person, Poll

    poll = Poll.query.get_or_404(poll_id)
    people = Person.query.filter(Person.email.isnot(None)).order_by(Person.first_name).all()
    poll_url = request.host_url.rstrip("/") + url_for("polls.poll_respond", token=poll.token)

    if request.method == "POST":
        selected_ids = request.form.getlist("person_ids")
        if not selected_ids:
            flash("Select at least one person.", "warning")
            return render_template("poll_share.html", poll=poll, people=people, poll_url=poll_url)

        recipients = [p for p in people if str(p.id) in selected_ids]
        sent = 0
        errors = 0
        for person in recipients:
            try:
                msg = Message(
                    subject=f"Game Night Poll: {poll.title}",
                    recipients=[person.email],
                    body=(
                        f"Hi {person.first_name},\n\n"
                        f"You're invited to respond to a Game Night poll: {poll.title}\n"
                        f"{poll.description + chr(10) if poll.description else ''}\n"
                        f"Vote here: {poll_url}\n\n"
                        f"— Game Night"
                    ),
                )
                mail.send(msg)
                sent += 1
            except Exception:
                errors += 1

        if sent:
            flash(f"Sent to {sent} person{'s' if sent != 1 else ''}.", "success")
        if errors:
            flash(f"{errors} email{'s' if errors != 1 else ''} failed to send.", "danger")
        return redirect(url_for("polls.poll_list"))

    return render_template("poll_share.html", poll=poll, people=people, poll_url=poll_url)


@polls_bp.route("/polls/option-row")
@login_required
@admin_required
def poll_option_row():
    """HTMX fragment: return a new option input row."""
    return render_template("_poll_option_row.html")


# ── Public routes ─────────────────────────────────────────────────────────── #


@polls_bp.route("/poll/<token>", endpoint="poll_respond")
def poll_page(token: str):
    poll = get_poll_by_token(token)
    if poll is None:
        abort(404)

    already_responded = session.get(f"poll_{token}_responded", False)
    results = get_results(poll) if already_responded or not poll_is_active(poll) else None

    return render_template(
        "poll_respond.html",
        poll=poll,
        active=poll_is_active(poll),
        already_responded=already_responded,
        results=results,
    )


@polls_bp.route("/poll/<token>/respond", methods=["POST"], endpoint="poll_submit")
def poll_submit(token: str):
    poll = get_poll_by_token(token)
    if poll is None:
        abort(404)

    person_id = current_user.id if current_user.is_authenticated else None
    respondent_name = request.form.get("respondent_name", "") or None
    option_ids_raw = request.form.getlist("option_ids")

    try:
        option_ids = [int(oid) for oid in option_ids_raw]
    except (ValueError, TypeError):
        return render_template(
            "_poll_thanks.html",
            success=False,
            message="Invalid submission.",
            results=None,
            poll=poll,
        )

    if not option_ids:
        return render_template(
            "_poll_thanks.html",
            success=False,
            message="Please select at least one option.",
            results=None,
            poll=poll,
        )

    if person_id is None and not respondent_name:
        return render_template(
            "_poll_thanks.html",
            success=False,
            message="Please enter your name.",
            results=None,
            poll=poll,
        )

    success, message = submit_response(poll, option_ids, person_id, respondent_name)

    if success:
        session[f"poll_{token}_responded"] = True

    results = get_results(poll)
    return render_template(
        "_poll_thanks.html", success=success, message=message, results=results, poll=poll
    )
