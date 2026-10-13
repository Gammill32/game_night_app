"""Operations that write several things save them in one commit, so a failure
part-way leaves nothing half-written."""

import datetime as dt

import pytest

from app.extensions import db as _db
from app.models import GameNight, Poll
from app.services import date_poll_services, game_night_services, poll_services
from tests.night_world import World


class Boom(Exception):
    pass


@pytest.fixture()
def w(app, db):
    world = World()
    yield world
    world.cleanup()


@pytest.fixture()
def commits(monkeypatch):
    """Counts db.session.commit() calls (they still happen)."""
    calls = []
    real = type(_db.session).commit

    def counting(self):
        calls.append(1)
        return real(self)

    monkeypatch.setattr(type(_db.session), "commit", counting)
    return calls


def _boom(*args, **kwargs):
    raise Boom()


def _date_poll(w, *answers_by_person):
    adm = w.person("Adm")
    poll = date_poll_services.create_date_poll("When?", None, [dt.date(2032, 5, 7)], adm.id)
    w.polls.append(poll.id)
    option = poll.options[0]
    for person in answers_by_person:
        date_poll_services.submit_answers(poll, person.id, {f"answer_{option.id}": "yes"})
    return adm, poll, option


def test_pick_date_failing_part_way_leaves_the_poll_unpicked(w, monkeypatch):
    ann = w.person("Ann")
    adm, poll, option = _date_poll(w, ann)
    nights_before = GameNight.query.filter_by(date=dt.date(2032, 5, 7)).count()

    # Fails after the night and its players are added, before the RSVP poll.
    monkeypatch.setattr(poll_services, "add_availability_poll", _boom)
    with pytest.raises(Boom):
        date_poll_services.pick_date(poll, option.id, adm.id)
    _db.session.rollback()

    poll = _db.session.get(Poll, poll.id)
    assert not poll.closed and poll.picked_game_night_id is None
    assert GameNight.query.filter_by(date=dt.date(2032, 5, 7)).count() == nights_before


def test_pick_date_commits_once(w, commits):
    ann = w.person("Ann")
    adm, poll, option = _date_poll(w, ann)
    commits.clear()
    ok, _, night = date_poll_services.pick_date(poll, option.id, adm.id)
    w.nights.append(night.id)
    assert ok and len(commits) == 1
    assert poll_services.rsvps_for_night(night) == {ann.id: "Can Make It"}


def test_start_night_with_rsvp_poll_failing_part_way_saves_nothing(w, monkeypatch):
    host = w.person("Host")
    monkeypatch.setattr(poll_services, "add_availability_poll", _boom)
    with pytest.raises(Boom):
        game_night_services.start_game_night(
            "2032-06-01", "atomic-start", [str(host.id)], host_id=host.id, rsvp_poll=True
        )
    _db.session.rollback()
    assert GameNight.query.filter_by(notes="atomic-start").count() == 0


def test_start_night_with_rsvp_poll_commits_once(w, commits):
    host = w.person("Host")
    commits.clear()
    night = game_night_services.start_game_night(
        "2032-06-02", "", [str(host.id)], host_id=host.id, rsvp_poll=True
    )
    w.nights.append(night.id)
    assert len(commits) == 1
    assert night.availability_poll is not None


def test_create_availability_poll_commits_once(w, commits):
    gn, host = w.night(w.person("Ann")), w.person("Host")
    commits.clear()
    poll_services.create_availability_poll(gn.id, host.id)
    assert len(commits) == 1
    poll = gn.availability_poll
    assert poll.availability and [o.label for o in poll.options] == (
        poll_services.AVAILABILITY_OPTIONS
    )


def test_create_date_poll_commits_once_with_its_dates(w, commits):
    adm = w.person("Adm")
    commits.clear()
    days = [dt.date(2032, 7, 1), dt.date(2032, 7, 2)]
    poll = date_poll_services.create_date_poll("When?", None, days, adm.id)
    w.polls.append(poll.id)
    assert len(commits) == 1
    assert poll.date_poll and [o.option_date for o in poll.options] == days


def test_owning_a_wishlisted_game_is_one_commit(w, commits):
    from app.models import OwnedBy, Wishlist
    from app.services import games_services

    ann, game = w.person("Ann"), w.game()
    _db.session.add(Wishlist(person_id=ann.id, game_id=game.id))
    _db.session.commit()
    commits.clear()

    ok, _ = games_services.modify_ownership(ann.id, game.id, add=True)
    assert ok and len(commits) == 1
    assert OwnedBy.query.filter_by(person_id=ann.id, game_id=game.id).count() == 1
    assert Wishlist.query.filter_by(person_id=ann.id, game_id=game.id).count() == 0
    OwnedBy.query.filter_by(person_id=ann.id).delete()
    _db.session.commit()
