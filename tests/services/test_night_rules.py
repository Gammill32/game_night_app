"""Night rules: a finalized night is locked; closed voting is closed."""

import pytest

from app.extensions import db as _db
from app.models import GameNightGame, GameNominations, GameVotes, Player, Result
from app.services import (
    game_night_services as gns,
)
from app.services import (
    night_policy,
    tracker_services,
    voting_services,
)
from tests.night_world import World


@pytest.fixture()
def w(app, db):
    world = World()
    yield world
    world.cleanup()


def _final_night(w):
    a, b = w.person("Ann"), w.person("Bo")
    gn = w.night(a, b, final=True)
    gng = w.play(gn, positions={a: 1, b: 2})
    return gn, gng, a, b


# --- the policy helpers ----------------------------------------------------


def test_policy_predicates(w):
    host, other = w.person("Host"), w.person("Other")
    gn = w.night(host, host=host)
    assert night_policy.can_manage(gn, host) and not night_policy.can_manage(gn, other)
    assert night_policy.is_editable(gn) and night_policy.voting_open(gn)
    gn.closed = True
    assert night_policy.is_editable(gn) and not night_policy.voting_open(gn)
    gn.closed, gn.final = False, True
    assert not night_policy.is_editable(gn) and not night_policy.voting_open(gn)
    with pytest.raises(night_policy.NightRuleError):
        night_policy.require_editable(gn)
    with pytest.raises(night_policy.NightRuleError):
        night_policy.require_manager(gn, other)
    _db.session.rollback()


# --- finalized nights refuse writes -----------------------------------------


def test_log_results_refused_on_final_night(w):
    gn, gng, a, _ = _final_night(w)
    pa = w.player(gn, a)
    ok, msg = gns.log_results(
        gn.id, gng.id, {str(pa.id): {"user_id": pa.id, "score": 0, "position": 5}}
    )
    assert not ok and "finalized" in msg
    assert Result.query.filter_by(game_night_game_id=gng.id, player_id=pa.id).one().position == 1


def test_add_and_remove_game_refused_on_final_night(w):
    gn, gng, _, _ = _final_night(w)
    ok, msg = gns.manage_game_in_night(gn.id, w.game().id, "add", 2)
    assert not ok and "finalized" in msg
    ok, msg = gns.manage_game_in_night(gn.id, None, "remove", game_night_game_id=gng.id)
    assert not ok and "finalized" in msg
    assert GameNightGame.query.filter_by(game_night_id=gn.id).count() == 1
    assert Result.query.filter_by(game_night_game_id=gng.id).count() == 2


def test_edit_final_night_refuses_date_and_attendee_changes(w):
    gn, _, a, b = _final_night(w)
    c = w.person("Cy")
    ids = [str(a.id), str(b.id)]
    ok, msg = gns.edit_game_night(gn.id, "2031-02-02", "", ids)
    assert not ok and "finalized" in msg
    ok, msg = gns.edit_game_night(gn.id, "2030-01-01", "", ids + [str(c.id)])
    assert not ok and "finalized" in msg
    assert Player.query.filter_by(game_night_id=gn.id).count() == 2
    # Notes can still change.
    ok, _ = gns.edit_game_night(gn.id, "2030-01-01", "Great night", ids)
    assert ok and gn.notes == "Great night"


def _active_tracker(w, gn, people):
    gng = w.play(gn)
    session = tracker_services.get_or_create_configuring_session(gng.id)
    field = session.fields[0]
    tracker_services.launch_session(
        session.id,
        mode="individual",
        teams_data=[],
        player_ids=[w.player(gn, p).id for p in people],
    )
    return session, field


def test_tracker_writes_refused_on_final_night(w):
    a = w.person("Ann")
    gn = w.night(a)
    session, field = _active_tracker(w, gn, [a])
    pa = w.player(gn, a)
    gn.final = True
    _db.session.commit()
    with pytest.raises(night_policy.NightRuleError):
        tracker_services.update_value(
            session.id, field.id, entity_type="player", entity_id=pa.id, delta=3
        )
    _db.session.rollback()
    with pytest.raises(night_policy.NightRuleError):
        tracker_services.save_results(session.id)
    _db.session.rollback()
    assert Result.query.filter_by(game_night_game_id=session.game_night_game_id).count() == 0


def test_launch_tracker_refused_on_final_night(w):
    a = w.person("Ann")
    gn = w.night(a)
    gng = w.play(gn)
    session = tracker_services.get_or_create_configuring_session(gng.id)
    gn.final = True
    _db.session.commit()
    with pytest.raises(night_policy.NightRuleError):
        tracker_services.launch_session(
            session.id, mode="individual", teams_data=[], player_ids=[w.player(gn, a).id]
        )
    _db.session.rollback()


def test_nominate_and_vote_refused_on_final_night(w):
    a = w.person("Ann")
    gn = w.night(a, final=True)
    game = w.game()
    ok, msg = voting_services.nominate_game(gn.id, a.id, game.id)
    assert not ok and "finalized" in msg
    ok, msg = voting_services.vote_game(gn.id, a.id, {game.id: 1})
    assert not ok and "finalized" in msg
    assert GameNominations.query.filter_by(game_night_id=gn.id).count() == 0
    assert GameVotes.query.filter_by(game_night_id=gn.id).count() == 0


# --- closed voting ------------------------------------------------------------


def test_nominate_and_vote_refused_when_voting_closed(w):
    a = w.person("Ann")
    gn = w.night(a, closed=True)
    game = w.game()
    ok, msg = voting_services.nominate_game(gn.id, a.id, game.id)
    assert not ok and "closed" in msg
    ok, msg = voting_services.vote_game(gn.id, a.id, {game.id: 1})
    assert not ok and "closed" in msg
    assert GameNominations.query.filter_by(game_night_id=gn.id).count() == 0
    assert GameVotes.query.filter_by(game_night_id=gn.id).count() == 0


# --- deleting a night takes its RSVP poll with it -----------------------------


def test_deleting_a_night_deletes_its_rsvp_poll_and_closes_linked_polls(w):
    from app.models import Poll
    from app.services import poll_services

    host = w.person("Host")
    gn = w.night(host, host=host)
    poll_services.create_availability_poll(gn.id, host.id)
    rsvp_id = gn.availability_poll.id
    other = poll_services.create_poll(
        "Snacks?", None, ["Chips", "Fruit"], host.id, False, game_night_id=gn.id
    )
    w.polls.append(other.id)

    ok, _ = gns.delete_game_night(gn.id)
    assert ok
    assert _db.session.get(Poll, rsvp_id) is None
    other = _db.session.get(Poll, other.id)
    assert other.closed


# --- picking a date-poll date twice -------------------------------------------


def test_pick_date_rechecks_the_poll_under_a_lock(w):
    """A second pick (double-submit) holding a stale copy of the poll must see
    the first pick and not create another night."""
    import datetime as dt

    from sqlalchemy import text

    from app.models import GameNight
    from app.services import date_poll_services as dps

    host = w.person("Host")
    poll = dps.create_date_poll("When?", None, [dt.date(2032, 3, 5)], host.id)
    w.polls.append(poll.id)
    first = w.night(host)
    option_id = poll.options[0].id
    # The first request picks in another connection; our copy still says unpicked.
    with _db.engine.begin() as conn:
        conn.execute(
            text("UPDATE polls SET picked_game_night_id = :n, closed = true WHERE id = :p"),
            {"n": first.id, "p": poll.id},
        )
    assert poll.picked_game_night_id is None

    nights_before = GameNight.query.count()
    ok, msg, night = dps.pick_date(poll, option_id, host.id)
    if night is not None:
        w.nights.append(night.id)  # cleaned up even if this regresses
    assert not ok and night is None and "already" in msg
    assert GameNight.query.count() == nights_before


# --- removing a player who is in a tracker ------------------------------------


def test_removing_a_tracked_player_is_blocked_with_a_message(w):
    a, b = w.person("Ann"), w.person("Bo")
    gn = w.night(a, b)
    _active_tracker(w, gn, [a, b])
    ok, msg = gns.edit_game_night(gn.id, "2030-01-01", "", [str(a.id)])
    assert not ok and "Bo" in msg and "tracker" in msg
    assert Player.query.filter_by(game_night_id=gn.id).count() == 2


def test_removing_a_player_on_a_tracked_team_is_blocked(w):
    a, b, c = w.person("Ann"), w.person("Bo"), w.person("Cy")
    gn = w.night(a, b, c)
    gng = w.play(gn)
    session = tracker_services.get_or_create_configuring_session(gng.id)
    tracker_services.launch_session(
        session.id,
        mode="teams",
        teams_data=[
            {"name": "Red", "player_ids": [w.player(gn, a).id]},
            {"name": "Blue", "player_ids": [w.player(gn, b).id]},
        ],
        player_ids=[],
    )
    ok, msg = gns.edit_game_night(gn.id, "2030-01-01", "", [str(a.id), str(c.id)])
    assert not ok and "Bo" in msg
    # Cy isn't tracked, so removing only Cy is fine.
    ok, _ = gns.edit_game_night(gn.id, "2030-01-01", "", [str(a.id), str(b.id)])
    assert ok
