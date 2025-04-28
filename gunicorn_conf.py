# gunicorn_conf.py

def post_fork(server, worker):
    from app.services.reminders_services import start_scheduler

    app = worker.app  # ✅ Get existing app from worker
    with app.app_context():
        start_scheduler(app)