import uuid

import pytest

from app.extensions import db as _db
from app.models import Game, OwnedBy, Person
from app.services.games_services import get_group_collection, get_my_collection


@pytest.fixture()
def collection_user(app, db):
    person = Person(
        first_name="Collector",
        last_name="One",
        email=f"collector_{uuid.uuid4().hex[:8]}@test.invalid",
    )
    _db.session.add(person)
    _db.session.commit()
    yield person
    # Teardown: delete ownership rows first, then person
    OwnedBy.query.filter_by(person_id=person.id).delete()
    _db.session.delete(person)
    _db.session.commit()


@pytest.fixture()
def collection_game(app, db, collection_user):
    game = Game(name="Settlers of Catan", bgg_id=13)
    _db.session.add(game)
    _db.session.flush()
    _db.session.add(OwnedBy(game_id=game.id, person_id=collection_user.id))
    _db.session.commit()
    yield game
    # Teardown: delete ownership rows, then game
    OwnedBy.query.filter_by(game_id=game.id).delete()
    _db.session.delete(game)
    _db.session.commit()


def test_get_group_collection_returns_owned_games(app, db, collection_game, collection_user):
    """Group collection includes games with owners and their names."""
    results = get_group_collection()
    game_entry = next((r for r in results if r["game"].id == collection_game.id), None)
    assert game_entry is not None
    assert "Collector One" in game_entry["owner_names"]


def test_get_my_collection_returns_only_my_games(app, db, collection_game, collection_user):
    """My collection returns only games owned by the specified user."""
    results = get_my_collection(collection_user.id)
    assert any(g.id == collection_game.id for g in results)


def test_get_my_collection_excludes_others_games(app, db, collection_game):
    """My collection does not include games owned by other users."""
    other = Person(
        first_name="Other",
        last_name="User",
        email=f"other_{uuid.uuid4().hex[:8]}@test.invalid",
    )
    _db.session.add(other)
    _db.session.commit()
    try:
        results = get_my_collection(other.id)
        assert not any(g.id == collection_game.id for g in results)
    finally:
        _db.session.delete(other)
        _db.session.commit()
