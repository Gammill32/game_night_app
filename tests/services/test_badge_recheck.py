"""`flask badges recheck`: re-judge every finalized night with the current rules."""

import datetime

import pytest

from app.extensions import db as _db
from app.models import Badge, PersonBadge
from app.services import badge_services as bs
from tests.services.test_badge_rules import World


@pytest.fixture()
def w(app, db):
    world = World()
    yield world
    world.cleanup()


def _badge(key):
    return Badge.query.filter_by(key=key).one()


def _award(person, key, night):
    pb = PersonBadge(person_id=person.id, badge_id=_badge(key).id, game_night_id=night.id)
    _db.session.add(pb)
    _db.session.flush()
    return pb


def _scenario(w):
    """Ann won three games on one night; Bob won none.

    Ann holds First Blood (valid); Bob holds First Blood (invalid); Ann has
    no Hat Trick although she earned it that night (missed)."""
    ann, bob = w.person(), w.person()
    ann.first_name, bob.first_name = "Ann", "Bob"
    gn = w.night(datetime.date(1820, 3, 1), [ann, bob])
    for rnd in (1, 2, 3):
        w.play(gn, w.game(), {ann: 1, bob: 2}, round=rnd)
    kept = _award(ann, "first_blood", gn)
    _award(bob, "first_blood", gn)
    _db.session.commit()
    return ann, bob, gn, kept


def _held(person):
    return {
        pb.badge.key: pb.game_night_id
        for pb in PersonBadge.query.filter_by(person_id=person.id).all()
    }


def test_recheck_removes_invalid_keeps_valid_and_adds_missed(w):
    ann, bob, gn, kept = _scenario(w)
    kept_id, kept_earned = kept.id, kept.earned_at

    bs.recheck_badges(apply=True)

    ann_badges, bob_badges = _held(ann), _held(bob)
    assert "first_blood" not in bob_badges
    assert ann_badges["hat_trick"] == gn.id
    still = _db.session.get(PersonBadge, kept_id)
    assert still is not None and still.earned_at == kept_earned


def test_recheck_dry_run_changes_nothing(w):
    ann, bob, gn, _kept = _scenario(w)
    before = (_held(ann), _held(bob))

    changes = bs.recheck_badges(apply=False)

    assert (_held(ann), _held(bob)) == before
    by_name = {c["badge"]: c for c in changes}
    assert ("Ann T", gn.date) in by_name[_badge("hat_trick").name]["added"]
    assert "Bob T" in by_name[_badge("first_blood").name]["removed"]


def test_recheck_command_prints_names(app, w):
    _scenario(w)
    result = app.test_cli_runner().invoke(args=["badges", "recheck", "--dry-run"])

    assert result.exit_code == 0, result.output
    assert _badge("first_blood").name in result.output
    assert "- Bob T" in result.output
    assert "+ Ann T (1820-03-01)" in result.output
    assert "Dry run" in result.output
