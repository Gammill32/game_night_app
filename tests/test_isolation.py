"""Each test runs in a transaction that's rolled back afterwards (conftest's
_rollback_after_test), so rows a test leaves behind never reach the next one.

Both tests check that no night from 1700 exists, then commit one - finalized,
with a winner and badges - and deliberately don't clean it up. Whichever runs
second fails if the other's night leaked.
"""

import datetime as dt

from sqlalchemy import text

from app.extensions import db as _db
from app.models import GameNight, PersonBadge
from app.services import game_night_services
from tests.night_world import World

LONG_AGO = dt.date(1700, 1, 1)


def _leave_a_finalized_night_behind():
    assert GameNight.query.filter_by(date=LONG_AGO).count() == 0

    w = World()  # no cleanup(), on purpose
    ann, bo = w.person("Ann"), w.person("Bo")
    gn = w.night(ann, bo, date=LONG_AGO)
    w.play(gn, positions={ann: 1, bo: 2})
    changed, _ = game_night_services.finalize(gn.id)

    # Committed as far as the test can tell, badges (awarded in savepoints) included...
    _db.session.expire_all()
    assert changed and _db.session.get(GameNight, gn.id).final
    assert PersonBadge.query.filter_by(game_night_id=gn.id).count() > 0
    # ...but invisible to any other connection until the outer transaction ends.
    with _db.engine.connect() as other:
        sql = text("SELECT count(*) FROM gamenights WHERE date = :d")
        assert other.execute(sql, {"d": LONG_AGO}).scalar() == 0


def test_rows_a_test_leaves_are_gone_in_the_next_test_a():
    _leave_a_finalized_night_behind()


def test_rows_a_test_leaves_are_gone_in_the_next_test_b():
    _leave_a_finalized_night_behind()
