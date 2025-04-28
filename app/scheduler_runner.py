# app/scheduler_runner.py

from app import create_app
from app.services.reminders_services import start_scheduler

app = create_app()

with app.app_context():
    start_scheduler(app)

# Keep this process alive so APScheduler can run
import time
while True:
    time.sleep(60)