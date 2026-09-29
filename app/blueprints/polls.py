from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

from app.services import date_poll_services
from app.services.poll_services import (
    can_view,
    create_poll,
    get_detailed_results,
    get_poll_by_token,
    parse_closes_at,
    submit_response,
    update_poll,
    view_context,
)
from app.utils import admin_required

polls_bp = Blueprint("polls", __name__)


@polls_bp.app_context_processor
def inject_active_polls():
    """The number of open polls the current user can see (for the nav badge)."""
    from app.services.poll_services import open_polls_for

    if not current_user.is_authenticated:
        return {"active_polls_count": 0}
    try:
        return {"active_polls_count": len(open_polls_for(current_user))}
    except Exception:
        return {"active_polls_count": 0}


def _linkable_nights():
    """Nights a poll can be linked to: anything not finalized, newest first."""
    from app.models import GameNight

    return GameNight.query.filter_by(final=False).order_by(GameNight.date.desc()).all()


@polls_bp.app_template_filter("local_dt")
def _local_dt(value):
    from app.services.poll_services import to_local

    return to_local(value)


def _form_night_id() -> int | None:
    raw = request.form.get("game_night_id", "")
    return int(raw) if raw.isdigit() else None


# ── Admin routes ─────────────────────────────────────────────────────────── #


@polls_bp.route("/polls/")
@login_required
@admin_required
def poll_list():
    from app.models import Poll

    polls = Poll.query.order_by(Poll.created_at.desc()).all()
    return render_template("poll_list.html", polls=polls)


@polls_bp.route("/polls/<int:poll_id>/results")
@login_required
@admin_required
def poll_results(poll_id: int):
    from app.models import Poll

    poll = Poll.query.get_or_404(poll_id)
    if poll.date_poll:
        return render_template(
            "poll_date_results.html",
            poll=poll,
            rows=date_poll_services.summary(poll),
            respondents=date_poll_services.respondent_count(poll),
        )
    results = get_detailed_results(poll)
    total = sum(r["count"] for r in results)
    return render_template("poll_results_detail.html", poll=poll, results=results, total=total)


@polls_bp.route("/polls/create", methods=["GET", "POST"])
@login_required
@admin_required
def poll_create():
    from app.models import Person

    people = Person.query.filter_by(active=True).order_by(Person.first_name).all()
    nights = _linkable_nights()
    form = request.form

    def page(error=None):
        return render_template(
            "poll_create.html",
            people=people,
            nights=nights,
            weekdays=date_poll_services.WEEKDAYS,
            error=error,
        )

    if request.method == "POST":
        title = form.get("title", "").strip()
        description = form.get("description", "").strip() or None
        private = form.get("private") == "true"
        invitee_ids = [int(i) for i in form.getlist("invitee_ids") if i.isdigit()]
        invitees = invitee_ids if private else None
        try:
            closes_at = parse_closes_at(form.get("closes_at", ""))
        except ValueError:
            return page("Invalid close date format. Please use the date picker.")
        if not title:
            return page("A title is required.")

        if form.get("kind") == "dates":
            dates, error = date_poll_services.parse_form(form)
            if error:
                return page(error)
            date_poll_services.create_date_poll(
                title, description, dates, current_user.id, closes_at, private, invitees
            )
        else:
            option_labels = [
                label.strip() for label in form.getlist("option_labels") if label.strip()
            ]
            if len(option_labels) < 2:
                return page("A poll needs at least two options.")
            create_poll(
                title,
                description,
                option_labels,
                current_user.id,
                form.get("multi_select") == "true",
                closes_at=closes_at,
                private=private,
                invitee_ids=invitees,
                game_night_id=_form_night_id(),
            )
        return redirect(url_for("polls.poll_list"))

    return page()


@polls_bp.route("/polls/<int:poll_id>/edit", methods=["GET", "POST"])
@login_required
@admin_required
def poll_edit(poll_id: int):
    from app.models import Person, Poll

    poll = Poll.query.get_or_404(poll_id)
    people = Person.query.filter_by(active=True).order_by(Person.first_name).all()
    nights = _linkable_nights()
    if poll.game_night and poll.game_night not in nights:
        nights.insert(0, poll.game_night)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        multi_select = request.form.get("multi_select") == "true"
        private = request.form.get("private") == "true"
        invitee_ids = [int(i) for i in request.form.getlist("invitee_ids") if i.isdigit()]

        try:
            closes_at = parse_closes_at(request.form.get("closes_at", ""))
        except ValueError:
            return render_template(
                "poll_edit.html",
                poll=poll,
                people=people,
                nights=nights,
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
                "poll_edit.html",
                poll=poll,
                people=people,
                nights=nights,
                error="Title is required.",
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
            game_night_id=_form_night_id(),
        )
        flash("Poll updated.", "success")
        return redirect(url_for("polls.poll_list"))

    return render_template("poll_edit.html", poll=poll, people=people, nights=nights)


@polls_bp.route("/polls/<int:poll_id>/pick/<int:option_id>", methods=["POST"])
@login_required
@admin_required
def poll_pick_date(poll_id: int, option_id: int):
    """Date poll: create the game night on this date."""
    from app.models import Poll

    poll = Poll.query.get_or_404(poll_id)
    success, message, night = date_poll_services.pick_date(poll, option_id, current_user.id)
    flash(message, "success" if success else "error")
    if night is None:
        return redirect(url_for("polls.poll_results", poll_id=poll.id))
    return redirect(url_for("game_night.edit_game_night", game_night_id=night.id))


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


# ── Member routes ─────────────────────────────────────────────────────────── #
# Polls need a login; a poll linked to a game night is also answered from
# that night's page.


def _viewable_poll(token: str):
    poll = get_poll_by_token(token)
    if poll is None or not can_view(poll, current_user):
        abort(404)
    return poll


@polls_bp.route("/poll/<token>", endpoint="poll_respond")
@login_required
def poll_page(token: str):
    poll = _viewable_poll(token)
    return render_template("poll_respond.html", **view_context(poll, current_user.id))


@polls_bp.route("/poll/<token>/respond", methods=["POST"], endpoint="poll_submit")
@login_required
def poll_submit(token: str):
    """HTMX: record the answer and return the refreshed poll widget."""
    poll = _viewable_poll(token)
    if poll.date_poll:
        success, message = date_poll_services.submit_answers(poll, current_user.id, request.form)
    else:
        try:
            option_ids = [int(oid) for oid in request.form.getlist("option_ids")]
        except (ValueError, TypeError):
            success, message = False, "Invalid submission."
        else:
            success, message = submit_response(poll, option_ids, current_user.id)

    context = view_context(poll, current_user.id)
    return render_template("_poll_widget.html", success=success, message=message, **context)
