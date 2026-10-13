"""Double-submits that race a unique constraint end in a normal outcome, not a 500.

`competing_insert` simulates the race: just before the service's own INSERT
into a table reaches the database, another connection inserts (and commits)
the same row, as a second request would.
"""

import pytest
from sqlalchemy import event, text

from app.extensions import db as _db
from app.models import GameNominations, GameVotes, OwnedBy, Player, Result, Wishlist
from app.services import game_night_services, games_services, tracker_services, voting_services
from app.services.errors import ServiceError
from tests.night_world import World

# The competing insert runs on a second connection, which can't see (and would
# block on) rows still uncommitted in the per-test transaction.
pytestmark = pytest.mark.real_commits


@pytest.fixture()
def w(app, db):
    world = World()
    yield world
    world.cleanup()


@pytest.fixture()
def competing_insert(db):
    listeners = []

    def arm(table, before="INSERT INTO", **values):
        """Insert `values` into `table` just before our next `before` statement
        on that table."""
        fired = []

        def hook(conn, cursor, statement, parameters, context, executemany):
            if fired or not statement.lstrip().startswith(f"{before} {table} "):
                return
            fired.append(statement)
            cols = ", ".join(values)
            params = ", ".join(f":{c}" for c in values)
            with _db.engine.connect() as other:
                other.execute(text(f"INSERT INTO {table} ({cols}) VALUES ({params})"), values)
                other.commit()

        event.listen(_db.engine, "before_cursor_execute", hook)
        listeners.append(hook)
        return fired

    yield arm
    for hook in listeners:
        event.remove(_db.engine, "before_cursor_execute", hook)


def _results(gng):
    return {
        r.player_id: (r.position, r.score)
        for r in Result.query.filter_by(game_night_game_id=gng.id)
    }


def test_log_results_racing_another_save_updates_the_row(w, competing_insert):
    ann = w.person("Ann")
    gn = w.night(ann)
    gng = w.play(gn)
    pa = w.player(gn, ann)
    fired = competing_insert("results", game_night_game_id=gng.id, player_id=pa.id, position=9)

    game_night_services.log_results(
        gn.id, gng.id, {str(pa.id): {"user_id": pa.id, "score": 7, "position": 1}}
    )
    assert fired
    _db.session.expire_all()
    assert _results(gng) == {pa.id: (1, 7)}


def test_tracker_save_racing_another_save_updates_the_row(w, competing_insert):
    ann, bo = w.person("Ann"), w.person("Bo")
    gn = w.night(ann, bo)
    gng = w.play(gn)
    pa, pb = w.player(gn, ann), w.player(gn, bo)
    session = tracker_services.get_or_create_configuring_session(gng.id)
    tracker_services.launch_session(
        session.id, mode="individual", teams_data=[], player_ids=[pa.id, pb.id]
    )
    field = session.fields[0]
    tracker_services.update_value(
        session.id, field.id, entity_type="player", entity_id=pa.id, delta=5
    )
    fired = competing_insert("results", game_night_game_id=gng.id, player_id=pa.id, position=2)

    tracker_services.save_results(session.id)
    assert fired
    _db.session.expire_all()
    assert _results(gng) == {pa.id: (1, 5), pb.id: (2, 0)}


def test_vote_racing_the_same_vote_updates_the_rank(w, competing_insert):
    ann = w.person("Ann")
    gn = w.night(ann)
    game = w.game()
    voting_services.nominate_game(gn.id, ann.id, game.id)
    pa = w.player(gn, ann)
    fired = competing_insert(
        "game_votes", game_night_id=gn.id, player_id=pa.id, game_id=game.id, rank=3
    )

    voting_services.vote_game(gn.id, ann.id, {game.id: 1})
    assert fired
    _db.session.expire_all()
    assert [v.rank for v in GameVotes.query.filter_by(player_id=pa.id)] == [1]


def test_nominating_a_game_someone_else_just_nominated_is_refused(w, competing_insert):
    ann, bo = w.person("Ann"), w.person("Bo")
    gn = w.night(ann, bo)
    game = w.game()
    pb = w.player(gn, bo)
    fired = competing_insert(
        "game_nominations", game_night_id=gn.id, player_id=pb.id, game_id=game.id
    )

    with pytest.raises(ServiceError, match="already been nominated"):
        voting_services.nominate_game(gn.id, ann.id, game.id)
    assert fired
    _db.session.rollback()
    assert [n.player_id for n in GameNominations.query.filter_by(game_night_id=gn.id)] == [pb.id]


def test_double_submitted_nomination_is_already_yours(w, competing_insert):
    ann = w.person("Ann")
    gn = w.night(ann)
    game = w.game()
    pa = w.player(gn, ann)
    fired = competing_insert(
        "game_nominations", game_night_id=gn.id, player_id=pa.id, game_id=game.id
    )

    message = voting_services.nominate_game(gn.id, ann.id, game.id)
    assert fired and "already your nomination" in message
    assert GameNominations.query.filter_by(game_night_id=gn.id).count() == 1


def test_changing_to_a_game_someone_just_nominated_is_refused(w, competing_insert):
    ann, bo = w.person("Ann"), w.person("Bo")
    gn = w.night(ann, bo)
    old, new = w.game(), w.game()
    voting_services.nominate_game(gn.id, ann.id, old.id)
    pb = w.player(gn, bo)
    fired = competing_insert(
        "game_nominations", before="UPDATE", game_night_id=gn.id, player_id=pb.id, game_id=new.id
    )

    with pytest.raises(ServiceError, match="already been nominated"):
        voting_services.nominate_game(gn.id, ann.id, new.id)
    assert fired
    _db.session.rollback()
    mine = GameNominations.query.filter_by(game_night_id=gn.id, game_id=old.id).one()
    assert mine.player.people_id == ann.id


def test_edit_night_racing_the_same_edit_keeps_one_player_row(w, competing_insert):
    ann, bo = w.person("Ann"), w.person("Bo")
    gn = w.night(ann)
    fired = competing_insert("players", game_night_id=gn.id, people_id=bo.id)

    game_night_services.edit_game_night(gn.id, str(gn.date), "", [str(ann.id), str(bo.id)])
    assert fired
    assert Player.query.filter_by(game_night_id=gn.id, people_id=bo.id).count() == 1
    assert Player.query.filter_by(game_night_id=gn.id).count() == 2


def test_wishlist_double_submit_is_already_on_it(w, competing_insert):
    ann, game = w.person("Ann"), w.game()
    fired = competing_insert("wishlist", person_id=ann.id, game_id=game.id)
    try:
        ok, message = games_services.modify_wishlist(ann.id, game.id, add=True)
        assert fired and not ok and "already" in message
        assert Wishlist.query.filter_by(person_id=ann.id, game_id=game.id).count() == 1
    finally:
        Wishlist.query.filter_by(person_id=ann.id).delete()
        _db.session.commit()


def test_add_to_wishlist_double_submit_is_already_on_it(w, competing_insert):
    ann, game = w.person("Ann"), w.game()
    fired = competing_insert("wishlist", person_id=ann.id, game_id=game.id)
    try:
        ok, message, _ = games_services.add_game_to_wishlist(ann.id, "", game_id=str(game.id))
        assert fired and not ok and "already" in message
    finally:
        Wishlist.query.filter_by(person_id=ann.id).delete()
        _db.session.commit()


def test_claim_game_double_submit_is_already_owned(w, competing_insert):
    ann, game = w.person("Ann"), w.game()
    fired = competing_insert("ownedby", person_id=ann.id, game_id=game.id)
    try:
        ok, message = games_services.modify_ownership(ann.id, game.id, add=True)
        assert fired and not ok and "already own" in message
        assert OwnedBy.query.filter_by(person_id=ann.id, game_id=game.id).count() == 1
    finally:
        OwnedBy.query.filter_by(person_id=ann.id).delete()
        _db.session.commit()
