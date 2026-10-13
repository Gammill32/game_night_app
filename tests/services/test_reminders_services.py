"""The daily reminder job: one bad night (or the address cleanup) doesn't stop
the rest, and a late wake-up still runs it."""

import datetime as dt
import logging

import pytest
from apscheduler.schedulers.background import BackgroundScheduler

from app.services import food_services, game_night_services, reminders_services
from app.utils.dates import local_today


@pytest.fixture()
def outbox(monkeypatch):
    sent: dict[str, str] = {}
    monkeypatch.setattr(reminders_services, "send_email", lambda to, s, b: sent.__setitem__(to, b))
    return sent


def test_address_cleanup_failure_does_not_stop_reminders(
    app, make_person, make_night, outbox, monkeypatch, caplog
):
    ann = make_person("Ann")
    make_night(ann, date=local_today())

    def boom(today):
        raise RuntimeError("cleanup broke")

    monkeypatch.setattr(game_night_services, "clear_past_addresses", boom)
    with caplog.at_level(logging.ERROR):
        reminders_services.check_and_send_reminders()
    assert ann.email in outbox
    assert "cleanup broke" in caplog.text


def test_one_bad_night_does_not_stop_the_others(
    app, make_person, make_night, outbox, monkeypatch, caplog
):
    ann, bo = make_person("Ann"), make_person("Bo")
    bad = make_night(ann, date=local_today())
    make_night(bo, date=local_today() + dt.timedelta(days=1))
    real = food_services.reminder_lines

    def lines(game_night):
        if game_night.id == bad.id:
            raise RuntimeError("template data broke")
        return real(game_night)

    monkeypatch.setattr(food_services, "reminder_lines", lines)
    with caplog.at_level(logging.ERROR):
        reminders_services.check_and_send_reminders()
    assert bo.email in outbox and ann.email not in outbox
    assert "template data broke" in caplog.text


def test_job_tolerates_a_late_wakeup(app, monkeypatch):
    """APScheduler's default misfire_grace_time is 1 second: a run that starts
    any later than that (busy process, clock jump) is skipped for the day."""
    sched = BackgroundScheduler()
    monkeypatch.setattr(reminders_services, "scheduler", sched)
    reminders_services.start_scheduler(app)
    try:
        job = sched.get_job("daily_game_night_reminder")
        assert job.misfire_grace_time >= 30 * 60
        assert job.coalesce is True
        assert job.max_instances == 1
    finally:
        sched.shutdown(wait=False)
