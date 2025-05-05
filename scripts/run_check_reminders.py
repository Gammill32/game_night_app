# app/scripts/run_check_reminders.py

import os
import sys

# Fix Python path so app modules work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import create_app
from app.services.reminders_services import check_and_send_reminders

def run_reminders():
    app = create_app()
    with app.app_context():
        check_and_send_reminders()

if __name__ == "__main__":
    run_reminders()
