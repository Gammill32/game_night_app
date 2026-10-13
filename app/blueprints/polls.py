from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    has_request_context,
    make_response,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from app.extensions import db
from app.services import date_poll_services, notifications, poll_services
from app.services.poll_services import (
    can_manage,
    can_view,
    create_poll,
    get_detailed_results,
    get_poll_by_token,
    parse_closes_at,
    submit_response,
    update_poll,
    view_context,
)
from app.utils import host_required
from app.utils.errors import is_htmx_fragment

polls_bp = Blueprint("polls", __name__)


@polls_bp.app_context_processor
def inject_active_polls():
    """The number of open polls the current user can see (for the nav badge)."""
    from app.services import poll_services

    # Emails rendered by the scheduler have no request (and so no user), and
    # HTMX fragments (a tracker tap, a poll answer) have no nav to show it in,
    # and the nav only shows it to people who can run polls.
    if (
        not has_request_context()
        or is_htmx_fragment()
        or not current_user.is_authenticated
        or not current_user.can_start_nights
    ):
        return {"active_polls_count": 0}
    try:
        return {"active_polls_count": poll_services.count_open_polls_for(current_user)}
    except Exception:
        # A nav badge isn't worth a broken page, but it is worth a log line.
        current_app.logger.exception("Couldn't count open polls for the nav")
        db.session.rollback()
        return {"active_polls_count": 0}


def _managed_poll(poll_id: int):
    """The poll, if the current user may manage it (else 404)."""
    from app.models import Poll

    poll = db.get_or_404(Poll, poll_id)
    if not can_manage(poll, current_user):
        abort(404)
    return poll


@polls_bp.app_template_global("can_manage_poll")
def _can_manage_poll(poll):
    return can_manage(poll, current_user)


@polls_bp.app_template_filter("local_dt")
def _local_dt(value):
    from app.services.poll_services import to_local

    return to_local(value)


def _form_night_id() -> int | None:
    raw = request.form.get("game_night_id", "")
    return int(raw) if raw.isdigit() else None


NIGHT_NOT_LINKABLE = "Pick one of the game nights in the list (or none)."


def _night_ok(night_id: int | None, nights) -> bool:
    """A poll can only be linked to a night in the form's list: one you run."""
    return night_id is None or any(n.id == night_id for n in nights)


# ── Admin routes ─────────────────────────────────────────────────────────── #


@polls_bp.route("/polls/")
@login_required
@host_required
def poll_list():
    return render_template("poll_list.html", polls=poll_services.polls_managed_by(current_user))


@polls_bp.route("/polls/<int:poll_id>/results")
@login_required
def poll_results(poll_id: int):
    poll = _managed_poll(poll_id)
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
@host_required
def poll_create():
    people = poll_services.invitable_people()
    nights = poll_services.linkable_nights(current_user)
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
            if not _night_ok(_form_night_id(), nights):
                return page(NIGHT_NOT_LINKABLE), 400
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
def poll_edit(poll_id: int):
    poll = _managed_poll(poll_id)
    people = poll_services.invitable_people()
    nights = poll_services.linkable_nights(current_user)
    if poll.game_night and poll.game_night not in nights:
        nights.insert(0, poll.game_night)

    def page(error=None):
        return render_template(
            "poll_edit.html", poll=poll, people=people, nights=nights, error=error
        )

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        description = request.form.get("description", "").strip() or None
        multi_select = request.form.get("multi_select") == "true"
        private = request.form.get("private") == "true"
        invitee_ids = [int(i) for i in request.form.getlist("invitee_ids") if i.isdigit()]

        try:
            closes_at = parse_closes_at(request.form.get("closes_at", ""))
        except ValueError:
            return page("Invalid close date format. Please use the date picker.")

        option_updates: dict[int, str] = {}
        for key, val in request.form.items():
            if key.startswith("option_label_"):
                try:
                    opt_id = int(key.removeprefix("option_label_"))
                    option_updates[opt_id] = val
                except ValueError:
                    pass

        if not title:
            return page("Title is required.")
        if not _night_ok(_form_night_id(), nights):
            return page(NIGHT_NOT_LINKABLE), 400

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

    return page()


@polls_bp.route("/polls/<int:poll_id>/pick/<int:option_id>", methods=["POST"])
@login_required
def poll_pick_date(poll_id: int, option_id: int):
    """Date poll: create the game night on this date."""

    poll = _managed_poll(poll_id)
    success, message, night = date_poll_services.pick_date(poll, option_id, current_user.id)
    flash(message, "success" if success else "error")
    if night is None:
        return redirect(url_for("polls.poll_results", poll_id=poll.id))
    return redirect(url_for("game_night.edit_game_night", game_night_id=night.id))


@polls_bp.route("/polls/<int:poll_id>/close", methods=["POST"])
@login_required
def poll_close(poll_id: int):
    poll_services.close_poll(_managed_poll(poll_id))
    return redirect(url_for("polls.poll_list"))


@polls_bp.route("/polls/<int:poll_id>/delete", methods=["POST"])
@login_required
def poll_delete(poll_id: int):
    poll_services.delete_poll(_managed_poll(poll_id))
    flash("Poll deleted.", "success")
    return redirect(url_for("polls.poll_list"))


@polls_bp.route("/polls/<int:poll_id>/share", methods=["GET", "POST"])
@login_required
def poll_share(poll_id: int):
    poll = _managed_poll(poll_id)
    people, unclaimed = poll_services.share_recipients()
    poll_url = request.host_url.rstrip("/") + url_for("polls.poll_respond", token=poll.token)

    if request.method == "POST":
        selected_ids = request.form.getlist("person_ids")
        if not selected_ids:
            flash("Select at least one person.", "warning")
            return render_template(
                "poll_share.html", poll=poll, people=people, poll_url=poll_url, unclaimed=unclaimed
            )

        recipients = [p for p in people if str(p.id) in selected_ids]
        # The flash names whoever didn't get it so a retry can select just them.
        sent_ids = notifications.send_poll_invites(poll, recipients, poll_url)
        failed = [p for p in recipients if p.id not in sent_ids]
        if sent_ids:
            n = len(sent_ids)
            flash(f"Sent to {n} {'person' if n == 1 else 'people'}.", "success")
        if failed:
            names = ", ".join(f"{p.first_name} {p.last_name}" for p in failed)
            flash(f"Couldn't email {names}. Try again for just them.", "error")
        return redirect(url_for("polls.poll_list"))

    return render_template(
        "poll_share.html", poll=poll, people=people, poll_url=poll_url, unclaimed=unclaimed
    )


@polls_bp.route("/polls/option-row")
@login_required
@host_required
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
    response = make_response(
        render_template("_poll_widget.html", success=success, message=message, **context)
    )
    if success:
        response.headers["HX-Trigger"] = "pollAnswered"  # the home page counts down its "N waiting"
    return response
