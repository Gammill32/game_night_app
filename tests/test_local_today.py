"""Pages that say "today" use APP_TIMEZONE's date, not the container's (UTC)."""

import datetime as dt

import pytest
import pytz
from flask import template_rendered

from app.utils.dates import local_today
from tests.conftest import login

# UTC+14 and UTC-12: these two are never on the same date, so at least one of
# them differs from the container's date.today() whenever the test runs.
ZONES = ["Etc/GMT-14", "Etc/GMT+12"]


@pytest.fixture()
def rendered(app):
    seen = []

    def record(sender, template, context, **extra):
        seen.append((template.name, context))

    template_rendered.connect(record, app)
    yield seen
    template_rendered.disconnect(record, app)


@pytest.fixture(params=ZONES)
def zone(app, request):
    old = app.config["APP_TIMEZONE"]
    app.config["APP_TIMEZONE"] = request.param
    yield dt.datetime.now(pytz.timezone(request.param)).date()
    app.config["APP_TIMEZONE"] = old


def test_local_today_uses_app_timezone(app, zone):
    assert local_today() == zone


@pytest.mark.parametrize("path", ["/games", "/"])
def test_pages_use_local_today(client, make_person, rendered, zone, path):
    login(client, make_person("Ann"))
    assert client.get(path).status_code == 200
    contexts = [c for name, c in rendered if "today" in c]
    assert contexts and all(c["today"] == zone for c in contexts)


def test_view_game_uses_local_today(client, make_person, rendered, zone, seed_data):
    login(client, make_person("Ann"))
    assert client.get(f"/game/{seed_data['game_id']}").status_code == 200
    assert [c["today"] for name, c in rendered if name == "view_game.html"] == [zone]
