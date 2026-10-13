"""Database-level rules: foreign key cascades and one-row-per-thing constraints."""

import datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db as _db
from app.models import (
    GameNightRankings,
    GameNominations,
    GameVotes,
    Player,
    Result,
    TrackerSession,
    TrackerTeam,
    TrackerValue,
    Wishlist,
    tracker_team_players,
)
from app.services import tracker_services
from tests.services.test_badge_rules import World


@pytest.fixture()
def w(app, db):
    world = World()
    yield world
    _db.session.rollback()
    night_ids = [n.id for n in world.nights]
    from app.models import GameNightGame

    gng_ids = [g.id for g in GameNightGame.query.filter(GameNightGame.game_night_id.in_(night_ids))]
    TrackerSession.query.filter(TrackerSession.game_night_game_id.in_(gng_ids)).delete()
    _db.session.commit()
    world.cleanup()


def _tracked_night(w, mode):
    a, b = w.person(), w.person()
    gn = w.night(datetime.date(1840, 1, 1), [a, b], final=False)
    gng = w.play(gn, w.game(), {})
    _db.session.commit()
    session = tracker_services.get_or_create_configuring_session(gng.id)
    tracker_services.add_field(
        session.id, type="counter", label="VP", starting_value=0, is_score_field=True
    )
    pl_a, pl_b = gn._players[a.id].id, gn._players[b.id].id
    tracker_services.launch_session(
        session.id,
        mode=mode,
        teams_data=[{"name": "Reds", "player_ids": [pl_a, pl_b]}],
        player_ids=[pl_a, pl_b],
    )
    return gn, a, b, session.id, pl_b


def test_deleting_a_player_deletes_their_tracker_values(w):
    gn, a, b, sid, pl_b = _tracked_night(w, "individual")
    assert TrackerValue.query.filter_by(player_id=pl_b).count() == 1

    # The app refuses to remove someone mid-tracker; the FK still cleans up when a
    # player row goes (e.g. deleting a night), so delete the row directly.
    Player.query.filter_by(id=pl_b).delete()
    _db.session.commit()

    assert TrackerValue.query.filter_by(player_id=pl_b).count() == 0
    assert TrackerValue.query.filter_by(tracker_session_id=sid).count() == 1


def test_deleting_a_player_drops_them_from_their_tracker_team(w):
    gn, a, b, sid, pl_b = _tracked_night(w, "teams")
    team = TrackerTeam.query.filter_by(tracker_session_id=sid).one()

    # The app refuses to remove someone mid-tracker; the FK still cleans up when a
    # player row goes (e.g. deleting a night), so delete the row directly.
    Player.query.filter_by(id=pl_b).delete()
    _db.session.commit()

    members = _db.session.execute(
        tracker_team_players.select().where(tracker_team_players.c.team_id == team.id)
    ).all()
    assert [m.player_id for m in members] == [gn._players[a.id].id]


def _rejected(*rows):
    """Adding these rows (after flushing the first) violates a unique constraint."""
    _db.session.add(rows[0])
    _db.session.flush()
    _db.session.add(rows[1])
    with pytest.raises(IntegrityError):
        _db.session.flush()
    _db.session.rollback()


def test_a_person_is_on_a_night_once(w):
    a = w.person()
    gn = w.night(datetime.date(1840, 1, 1), [])
    _rejected(
        Player(game_night_id=gn.id, people_id=a.id), Player(game_night_id=gn.id, people_id=a.id)
    )


def test_a_player_has_one_result_per_game(w):
    a = w.person()
    gn = w.night(datetime.date(1840, 1, 1), [a])
    gng = w.play(gn, w.game(), {})
    pl = gn._players[a.id].id
    _rejected(
        Result(game_night_game_id=gng.id, player_id=pl, position=1),
        Result(game_night_game_id=gng.id, player_id=pl, position=2),
    )


def test_a_player_ranks_a_game_once(w):
    a = w.person()
    gn = w.night(datetime.date(1840, 1, 1), [a])
    game, pl = w.game(), gn._players[a.id].id
    _rejected(
        GameVotes(game_night_id=gn.id, player_id=pl, game_id=game.id, rank=1),
        GameVotes(game_night_id=gn.id, player_id=pl, game_id=game.id, rank=2),
    )


def test_a_game_is_on_a_wishlist_once(w):
    a, game = w.person(), w.game()
    _rejected(Wishlist(person_id=a.id, game_id=game.id), Wishlist(person_id=a.id, game_id=game.id))


def test_a_game_is_nominated_once_per_night(w):
    a, b = w.person(), w.person()
    gn = w.night(datetime.date(1840, 1, 1), [a, b])
    game = w.game()
    _rejected(
        GameNominations(game_night_id=gn.id, player_id=gn._players[a.id].id, game_id=game.id),
        GameNominations(game_night_id=gn.id, player_id=gn._players[b.id].id, game_id=game.id),
    )


def test_night_rankings_tell_apart_places_below_fourth(w):
    people = [w.person() for _ in range(6)]
    gn = w.night(datetime.date(1840, 1, 1), people)
    w.play(gn, w.game(), {p: i + 1 for i, p in enumerate(people)})
    _db.session.commit()

    ranks = {r.player_id: r.rank for r in GameNightRankings.query.filter_by(game_night_id=gn.id)}
    assert [ranks[gn._players[p.id].id] for p in people] == [1, 2, 3, 4, 5, 6]


def test_night_rankings_unchanged_when_everyone_places_in_top_four(w):
    a, b, c = w.person(), w.person(), w.person()
    gn = w.night(datetime.date(1840, 1, 1), [a, b, c])
    w.play(gn, w.game(), {a: 1, b: 2, c: 3})
    w.play(gn, w.game(), {a: 3, b: 1, c: 2}, round=2)
    _db.session.commit()

    rows = GameNightRankings.query.filter_by(game_night_id=gn.id).all()
    by_player = {r.player_id: (r.rank, r.position_counts) for r in rows}
    # Most firsts, then most seconds, and so on.
    assert by_player[gn._players[b.id].id] == (1, [1, 1, 0, 0])
    assert by_player[gn._players[a.id].id] == (2, [1, 0, 1, 0])
    assert by_player[gn._players[c.id].id] == (3, [0, 1, 1, 0])
