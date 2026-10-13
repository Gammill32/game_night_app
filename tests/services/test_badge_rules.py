"""Badge rules vs. their descriptions: regressions for checks that disagreed with the text.

Nights here are dated in the 1800s so the group-wide checks (first night ever,
most wins, everyone you've played with) only see this file's own data.
"""

import datetime
import uuid

import pytest
from sqlalchemy import text

from app.extensions import db as _db
from app.models import (
    Badge,
    Game,
    GameNight,
    GameNightGame,
    Person,
    PersonBadge,
    Player,
    Result,
)
from app.services import badge_services as bs


class World:
    """Builds people, nights and results, and deletes them all afterwards."""

    def __init__(self):
        self.people, self.nights, self.games = [], [], []

    def person(self, active=True):
        p = Person(
            first_name="P",
            last_name="T",
            email=f"rules_{uuid.uuid4().hex[:8]}@test.invalid",
            active=active,
        )
        _db.session.add(p)
        _db.session.flush()
        self.people.append(p)
        return p

    def game(self):
        g = Game(name=f"Rules {uuid.uuid4().hex[:8]}")
        _db.session.add(g)
        _db.session.flush()
        self.games.append(g)
        return g

    def night(self, day, people, final=True, host=None):
        gn = GameNight(date=day, final=final, host_id=host.id if host else None)
        _db.session.add(gn)
        _db.session.flush()
        self.nights.append(gn)
        gn._players = {}
        for p in people:
            pl = Player(game_night_id=gn.id, people_id=p.id)
            _db.session.add(pl)
            _db.session.flush()
            gn._players[p.id] = pl
        return gn

    def play(self, gn, game, positions, round=1):
        """positions: {person: position}."""
        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=round)
        _db.session.add(gng)
        _db.session.flush()
        for p, pos in positions.items():
            _db.session.add(
                Result(game_night_game_id=gng.id, player_id=gn._players[p.id].id, position=pos)
            )
        _db.session.flush()
        return gng

    def cleanup(self):
        _db.session.rollback()
        ids = [p.id for p in self.people]
        night_ids = [n.id for n in self.nights]
        PersonBadge.query.filter(PersonBadge.person_id.in_(ids)).delete()
        gng_ids = [
            g.id for g in GameNightGame.query.filter(GameNightGame.game_night_id.in_(night_ids))
        ]
        Result.query.filter(Result.game_night_game_id.in_(gng_ids)).delete()
        GameNightGame.query.filter(GameNightGame.id.in_(gng_ids)).delete()
        Player.query.filter(Player.game_night_id.in_(night_ids)).delete()
        GameNight.query.filter(GameNight.id.in_(night_ids)).delete()
        Person.query.filter(Person.id.in_(ids)).delete()
        Game.query.filter(Game.id.in_([g.id for g in self.games])).delete()
        _db.session.commit()


@pytest.fixture()
def w(app, db):
    world = World()
    yield world
    world.cleanup()


def d(year, month=1, day=1):
    return datetime.date(year, month, day)


# --- Gracious Host: judged once the year is over --------------------------


def test_gracious_host_not_awarded_before_year_ends(w):
    a = w.person()
    w.night(d(1850, 1, 1), [a])
    last = w.night(d(1850, 6, 1), [a])
    assert bs._check_gracious_host(a.id, last.id) is False


def test_gracious_host_awarded_at_first_night_of_next_year(w):
    a, b = w.person(), w.person()
    w.night(d(1850, 1, 1), [a, b])
    w.night(d(1850, 6, 1), [a])
    new_year = w.night(d(1851, 1, 5), [a, b])
    assert bs._check_gracious_host(a.id, new_year.id) is True
    assert bs._check_gracious_host(b.id, new_year.id) is False


def test_gracious_host_needs_attendance_last_year(w):
    a, newbie = w.person(), w.person()
    w.night(d(1850, 1, 1), [a])
    new_year = w.night(d(1851, 1, 5), [a, newbie])
    assert bs._check_gracious_host(newbie.id, new_year.id) is False


# --- Nemesis: same opponent, same game ------------------------------------


def test_nemesis_ignores_losses_spread_across_games(w):
    me, bully = w.person(), w.person()
    gn = w.night(d(1850), [me, bully])
    for _ in range(5):
        w.play(gn, w.game(), {bully: 1, me: 2})
    assert bs._check_nemesis(me.id, gn.id) is False


def test_nemesis_counts_losses_in_one_game(w):
    me, bully = w.person(), w.person()
    gn = w.night(d(1850), [me, bully])
    g = w.game()
    for r in range(5):
        w.play(gn, g, {bully: 1, me: 2}, round=r)
    assert bs._check_nemesis(me.id, gn.id) is True


def test_nemesis_ignores_unfinalized_nights(w):
    me, bully = w.person(), w.person()
    draft = w.night(d(1850, 1, 1), [me, bully], final=False)
    g = w.game()
    for r in range(5):
        w.play(draft, g, {bully: 1, me: 2}, round=r)
    tonight = w.night(d(1850, 2, 1), [me, bully])
    assert bs._check_nemesis(me.id, tonight.id) is False


# --- The Diplomat: every game has a shared first place --------------------


def test_diplomat_rejects_game_with_single_result(w):
    a, b = w.person(), w.person()
    gn = w.night(d(1850), [a, b])
    w.play(gn, w.game(), {a: 1})
    assert bs._check_the_diplomat(a.id, gn.id) is False


def test_diplomat_accepts_shared_first_with_others_behind(w):
    a, b, c = w.person(), w.person(), w.person()
    gn = w.night(d(1850), [a, b, c])
    w.play(gn, w.game(), {a: 1, b: 1, c: 3})
    assert bs._check_the_diplomat(a.id, gn.id) is True


# --- Social Butterfly: everyone who actually plays --------------------------


def test_social_butterfly_ignores_inactive_and_never_played(w):
    me, friend = w.person(), w.person()
    w.person(active=False)  # deactivated
    w.person()  # signed up, never played
    gn = w.night(d(1850), [me, friend])
    w.play(gn, w.game(), {me: 1, friend: 2})
    assert bs._check_social_butterfly(me.id, gn.id) is True


def test_social_butterfly_needs_everyone_who_played(w):
    me, friend, stranger = w.person(), w.person(), w.person()
    gn = w.night(d(1850), [me, friend, stranger])
    w.play(gn, w.game(), {me: 1, friend: 2})
    w.play(gn, w.game(), {stranger: 1, friend: 2})
    assert bs._check_social_butterfly(me.id, gn.id) is False


# --- Early Bird: hosted 10 nights -----------------------------------------


def test_early_bird_awarded_for_hosting_ten_nights(w):
    host, guest = w.person(), w.person()
    nights = [w.night(d(1850, 1, i + 1), [guest, host], host=host) for i in range(10)]
    assert bs._check_early_bird(host.id, nights[-1].id) is True
    assert bs._check_early_bird(guest.id, nights[-1].id) is False


def test_early_bird_not_awarded_for_nine(w):
    host = w.person()
    nights = [w.night(d(1850, 1, i + 1), [host], host=host) for i in range(9)]
    assert bs._check_early_bird(host.id, nights[-1].id) is False


# --- Founding Member: among the first 5 people to play, not by row order ---


def _all_play(w, gn, people):
    w.play(gn, w.game(), {p: i + 1 for i, p in enumerate(people)})


def test_founding_member_by_debut_date(w):
    first = [w.person() for _ in range(3)]
    second = [w.person() for _ in range(3)]
    late = w.person()
    _all_play(w, w.night(d(1800, 1, 1), first), first)
    _all_play(w, w.night(d(1800, 1, 2), second + first), second + first)
    n3 = w.night(d(1800, 1, 3), [late] + first)
    _all_play(w, n3, [late] + first)
    for p in first + second:  # only 3 debuted before the second night, so all six are in
        assert bs._check_founding_member(p.id, n3.id) is True
    assert bs._check_founding_member(late.id, n3.id) is False


def test_founding_member_needs_a_game_played_not_just_attendance(w):
    players = [w.person() for _ in range(5)]
    watcher = w.person()
    gn = w.night(d(1800, 1, 1), players + [watcher])
    _all_play(w, gn, players)
    assert bs._check_founding_member(players[0].id, gn.id) is True
    assert bs._check_founding_member(watcher.id, gn.id) is False


# --- Kingslayer: ties for most wins ----------------------------------------


@pytest.mark.parametrize("beaten", ["a", "b"])
def test_kingslayer_counts_any_tied_leader(w, beaten):
    a, b, me = w.person(), w.person(), w.person()
    past = w.night(d(1800, 1, 1), [a, b])
    for r in range(3):
        w.play(past, w.game(), {a: 1, b: 2}, round=r)
        w.play(past, w.game(), {b: 1, a: 2}, round=r)
    tonight = w.night(d(1800, 1, 2), [a, b, me])
    king = a if beaten == "a" else b
    w.play(tonight, w.game(), {me: 1, king: 2})
    assert bs._check_kingslayer(me.id, tonight.id) is True


# --- Dark Horse: a lone result isn't "last place" --------------------------


def test_dark_horse_ignores_single_result_games(w):
    me, other = w.person(), w.person()
    gn = w.night(d(1850), [me, other])
    for r in range(3):
        w.play(gn, w.game(), {me: 1}, round=r)
    w.play(gn, w.game(), {me: 1, other: 2}, round=3)
    assert bs._check_dark_horse(me.id, gn.id) is False


# --- Career badges only count nights up to the one being judged -----------


def test_first_blood_ignores_later_nights(w):
    me, other = w.person(), w.person()
    early = w.night(d(1850, 1, 1), [me, other])
    w.play(early, w.game(), {other: 1, me: 2})
    later = w.night(d(1850, 2, 1), [me, other])
    w.play(later, w.game(), {me: 1, other: 2})
    assert bs._check_first_blood(me.id, early.id) is False


def test_rematch_looks_at_previous_night_not_later(w):
    me = w.person()
    g = w.game()
    first = w.night(d(1850, 1, 1), [me])
    w.play(first, w.game(), {me: 1})
    second = w.night(d(1850, 2, 1), [me])
    w.play(second, g, {me: 1})
    third = w.night(d(1850, 3, 1), [me])
    w.play(third, g, {me: 1})
    # Judging the second night: the night before it is the first, which shares nothing
    # (the third shares a game, but it came after).
    assert bs._check_the_rematch(me.id, second.id) is False


# --- One failing check doesn't wipe out the rest ---------------------------


def test_db_error_in_one_check_keeps_other_awards(w, monkeypatch):
    me, other = w.person(), w.person()
    gn = w.night(d(1850), [me, other])
    for r in range(3):
        w.play(gn, w.game(), {me: 1, other: 2}, round=r)
    _db.session.commit()

    def broken(person_id, game_night_id):
        _db.session.execute(text("SELECT * FROM no_such_table"))

    monkeypatch.setitem(bs._BADGE_REGISTRY, "first_blood", broken)
    bs.evaluate_badges_for_night(gn.id)

    hat_trick = Badge.query.filter_by(key="hat_trick").one()
    assert PersonBadge.query.filter_by(person_id=me.id, badge_id=hat_trick.id).count() == 1


def test_one_failed_award_keeps_the_nights_other_awards(w, monkeypatch):
    me, other = w.person(), w.person()
    gn = w.night(d(1850), [me, other])
    for r in range(3):
        w.play(gn, w.game(), {me: 1, other: 2}, round=r)
    _db.session.commit()
    first_blood = Badge.query.filter_by(key="first_blood").one()
    real_add = bs.add_unless_duplicate

    def flaky(obj, *constraints):
        if obj.badge_id == first_blood.id:
            raise RuntimeError("boom")
        return real_add(obj, *constraints)

    monkeypatch.setattr(bs, "add_unless_duplicate", flaky)
    bs.evaluate_badges_for_night(gn.id)

    hat_trick = Badge.query.filter_by(key="hat_trick").one()
    assert PersonBadge.query.filter_by(person_id=me.id, badge_id=hat_trick.id).count() == 1
