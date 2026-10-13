"""Dates in the app's timezone (APP_TIMEZONE), not the container's.

The container runs on UTC, so date.today() rolls over to tomorrow at 7pm
Central; anything shown as "today" or compared with a night's date should use
local_today() instead."""

from datetime import date, datetime

import pytz
from flask import current_app


def app_tz():
    return pytz.timezone(current_app.config["APP_TIMEZONE"])


def local_today() -> date:
    return datetime.now(app_tz()).date()
