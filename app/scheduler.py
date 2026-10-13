"""The reminder scheduler as its own process: `python -m app.scheduler`.

docker-compose.yml runs this as the game_night_scheduler service (the same
image, started with `scheduler` as its command) and sets ENABLE_SCHEDULER=false
on the web container, so the daily job runs exactly once however many gunicorn
workers or threads serve the site.
"""

import logging
import os
import signal
import threading


def main() -> None:
    os.environ["ENABLE_SCHEDULER"] = "true"  # this process exists to run it

    # As PID 1 in a container, SIGTERM is ignored unless we handle it. Set this up
    # first so a stop that arrives while the app is starting still exits cleanly.
    stop = threading.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: stop.set())

    from app import create_app
    from app.extensions import scheduler

    create_app()  # starts the BackgroundScheduler (start_schedulers)
    for job in scheduler.get_jobs():
        logging.info("Scheduler running: %s, next run %s", job.id, job.next_run_time)

    stop.wait()
    logging.info("Scheduler stopping")
    scheduler.shutdown()


if __name__ == "__main__":
    main()
