"""The reminder scheduler runs in its own process (the compose scheduler
service); the web process skips it when ENABLE_SCHEDULER=false."""

import os
import signal
import subprocess
import sys
import time

import pytest


def test_web_skips_scheduler_when_disabled(app, monkeypatch):
    import app as app_pkg
    from app.services import reminders_services

    started = []
    monkeypatch.setattr(reminders_services, "start_scheduler", lambda a: started.append(a))
    monkeypatch.setenv("ENABLE_SCHEDULER", "false")
    app_pkg.start_schedulers(app)
    assert started == []
    monkeypatch.setenv("ENABLE_SCHEDULER", "true")
    app_pkg.start_schedulers(app)
    assert started == [app]


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="needs the test database")
def test_scheduler_process_starts_the_job_and_stops_on_sigterm():
    env = dict(
        os.environ,
        DATABASE_URL=os.environ["TEST_DATABASE_URL"],
        ENABLE_SCHEDULER="false",  # the entry point turns it on regardless
        FLASK_DEBUG="1",
    )
    proc = subprocess.Popen(
        [sys.executable, "-m", "app.scheduler"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        assert proc.stdout is not None
        lines = []
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            line = proc.stdout.readline()
            if not line:
                break
            lines.append(line)
            if "Scheduler running: daily_game_night_reminder" in line:
                break
        assert any("daily_game_night_reminder" in line for line in lines), "".join(lines)
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(timeout=10) == 0
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
