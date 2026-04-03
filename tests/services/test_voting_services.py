"""Tests for voting_services — previously 0% covered."""

import datetime
import uuid

import pytest

from app.extensions import db as _db
from app.models import Game, GameNight, GameNominations, GameVotes, OwnedBy, Person, Player


@pytest.fixture()
def voting_night(app, db):
    """A game night with two players and two games they own."""
    from app.extensions import bcrypt

    p1 = Person(
        first_name="Alice",
        last_name=f"V{uuid.uuid4().hex[:4]}",
        email=f"alice_{uuid.uuid4().hex[:6]}@test.com",
        password=bcrypt.generate_password_hash("pw", rounds=4).decode(),
    )
    p2 = Person(
        first_name="Bob",
        last_name=f"V{uuid.uuid4().hex[:4]}",
        email=f"bob_{uuid.uuid4().hex[:6]}@test.com",
        password=bcrypt.generate_password_hash("pw", rounds=4).decode(),
    )
    g1 = Game(name=f"VGame1-{uuid.uuid4().hex[:4]}", bgg_id=None)
    g2 = Game(name=f"VGame2-{uuid.uuid4().hex[:4]}", bgg_id=None)
    gn = GameNight(date=datetime.date.today(), final=False)
    _db.session.add_all([p1, p2, g1, g2, gn])
    _db.session.flush()

    pl1 = Player(game_night_id=gn.id, people_id=p1.id)
    pl2 = Player(game_night_id=gn.id, people_id=p2.id)
    own1 = OwnedBy(game_id=g1.id, person_id=p1.id)
    own2 = OwnedBy(game_id=g2.id, person_id=p2.id)
    _db.session.add_all([pl1, pl2, own1, own2])
    _db.session.commit()

    yield {
        "gn_id": gn.id,
        "p1_id": p1.id,
        "p2_id": p2.id,
        "g1_id": g1.id,
        "g2_id": g2.id,
        "pl1_id": pl1.id,
        "pl2_id": pl2.id,
    }

    _db.session.rollback()
    GameVotes.query.filter_by(game_night_id=gn.id).delete()
    GameNominations.query.filter_by(game_night_id=gn.id).delete()
    Player.query.filter_by(game_night_id=gn.id).delete()
    OwnedBy.query.filter_by(person_id=p1.id).delete()
    OwnedBy.query.filter_by(person_id=p2.id).delete()
    _db.session.delete(gn)
    _db.session.delete(g1)
    _db.session.delete(g2)
    _db.session.delete(p1)
    _db.session.delete(p2)
    _db.session.commit()


# ── nominate_game ──────────────────────────────────────────────────────────────


def test_nominate_game_success(app, voting_night):
    from app.services.voting_services import nominate_game

    with app.app_context():
        success, msg = nominate_game(
            voting_night["gn_id"], voting_night["p1_id"], voting_night["g1_id"]
        )
    assert success is True
    nom = GameNominations.query.filter_by(
        game_night_id=voting_night["gn_id"], player_id=voting_night["pl1_id"]
    ).first()
    assert nom is not None
    assert nom.game_id == voting_night["g1_id"]


def test_nominate_game_not_a_player(app, voting_night):
    """A person not in the game night cannot nominate."""
    from app.services.voting_services import nominate_game

    outsider = Person(
        first_name="Out", last_name="Sider", email=f"out_{uuid.uuid4().hex[:6]}@t.com"
    )
    _db.session.add(outsider)
    _db.session.commit()
    try:
        with app.app_context():
            success, msg = nominate_game(voting_night["gn_id"], outsider.id, voting_night["g1_id"])
        assert success is False
        assert "not a player" in msg.lower()
    finally:
        _db.session.delete(outsider)
        _db.session.commit()


def test_nominate_game_already_nominated_by_other(app, voting_night):
    """Cannot nominate a game that another player already nominated."""
    from app.services.voting_services import nominate_game

    with app.app_context():
        nominate_game(voting_night["gn_id"], voting_night["p1_id"], voting_night["g1_id"])
        success, msg = nominate_game(
            voting_night["gn_id"], voting_night["p2_id"], voting_night["g1_id"]
        )
    assert success is False
    assert "already been nominated" in msg.lower()


def test_nominate_game_updates_own_nomination(app, voting_night):
    """A player changing their own nomination replaces the previous one."""
    from app.services.voting_services import nominate_game

    with app.app_context():
        nominate_game(voting_night["gn_id"], voting_night["p1_id"], voting_night["g1_id"])
        success, msg = nominate_game(
            voting_night["gn_id"], voting_night["p1_id"], voting_night["g2_id"]
        )
    assert success is True
    nom = GameNominations.query.filter_by(
        game_night_id=voting_night["gn_id"], player_id=voting_night["pl1_id"]
    ).first()
    assert nom.game_id == voting_night["g2_id"]


def test_nominate_game_clears_existing_votes(app, voting_night):
    """Re-nominating clears the player's existing votes."""
    from app.services.voting_services import nominate_game, vote_game

    with app.app_context():
        nominate_game(voting_night["gn_id"], voting_night["p1_id"], voting_night["g1_id"])
        vote_game(voting_night["gn_id"], voting_night["p1_id"], {voting_night["g1_id"]: 1})
        nominate_game(voting_night["gn_id"], voting_night["p1_id"], voting_night["g2_id"])

    votes = GameVotes.query.filter_by(
        game_night_id=voting_night["gn_id"], player_id=voting_night["pl1_id"]
    ).all()
    assert votes == []


# ── vote_game ─────────────────────────────────────────────────────────────────


def test_vote_game_success(app, voting_night):
    from app.services.voting_services import nominate_game, vote_game

    with app.app_context():
        nominate_game(voting_night["gn_id"], voting_night["p1_id"], voting_night["g1_id"])
        success, msg = vote_game(
            voting_night["gn_id"], voting_night["p1_id"], {voting_night["g1_id"]: 1}
        )
    assert success is True
    vote = GameVotes.query.filter_by(
        game_night_id=voting_night["gn_id"], player_id=voting_night["pl1_id"]
    ).first()
    assert vote is not None
    assert vote.rank == 1


def test_vote_game_duplicate_rank_rejected(app, voting_night):
    """Two games cannot share the same rank in one submission."""
    from app.services.voting_services import nominate_game, vote_game

    with app.app_context():
        nominate_game(voting_night["gn_id"], voting_night["p1_id"], voting_night["g1_id"])
        nominate_game(voting_night["gn_id"], voting_night["p2_id"], voting_night["g2_id"])
        success, msg = vote_game(
            voting_night["gn_id"],
            voting_night["p1_id"],
            {voting_night["g1_id"]: 1, voting_night["g2_id"]: 1},
        )
    assert success is False
    assert "already used" in msg.lower() or "rank" in msg.lower()


def test_vote_game_not_a_player(app, voting_night):
    """A non-participant cannot vote."""
    from app.services.voting_services import vote_game

    outsider = Person(first_name="X", last_name="Y", email=f"xy_{uuid.uuid4().hex[:6]}@t.com")
    _db.session.add(outsider)
    _db.session.commit()
    try:
        with app.app_context():
            success, msg = vote_game(voting_night["gn_id"], outsider.id, {voting_night["g1_id"]: 1})
        assert success is False
        assert "not a player" in msg.lower()
    finally:
        _db.session.delete(outsider)
        _db.session.commit()


def test_vote_game_null_rank_removes_existing_vote(app, voting_night):
    """Passing rank=None for a game removes the existing vote."""
    from app.services.voting_services import nominate_game, vote_game

    with app.app_context():
        nominate_game(voting_night["gn_id"], voting_night["p1_id"], voting_night["g1_id"])
        vote_game(voting_night["gn_id"], voting_night["p1_id"], {voting_night["g1_id"]: 2})
        vote_game(voting_night["gn_id"], voting_night["p1_id"], {voting_night["g1_id"]: None})

    vote = GameVotes.query.filter_by(
        game_night_id=voting_night["gn_id"],
        player_id=voting_night["pl1_id"],
        game_id=voting_night["g1_id"],
    ).first()
    assert vote is None
