import uuid

import pytest

from app.extensions import db as _db
from app.models import Game, OwnedBy, Person


@pytest.fixture()
def collection_user(app, db):
    person = Person(
        first_name="Collector",
        last_name="One",
        email=f"collector_{uuid.uuid4().hex[:8]}@test.invalid",
    )
    _db.session.add(person)
    _db.session.commit()
    try:
        yield person
    finally:
        _db.session.rollback()
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
    try:
        yield game
    finally:
        _db.session.rollback()
        OwnedBy.query.filter_by(game_id=game.id).delete()
        _db.session.delete(game)
        _db.session.commit()


def test_games_scope_mine_filters_to_user_owned(admin_client, db, collection_game):
    """scope=mine on games index returns only games the current user owns."""
    user = Person.query.filter_by(email="admin@example.com").first()
    other_only = Game(name=f"OtherOnly {uuid.uuid4().hex[:6]}", bgg_id=None)
    _db.session.add(other_only)
    _db.session.flush()
    other_only_id = other_only.id
    _db.session.commit()

    resp = admin_client.get("/games?scope=mine")
    assert resp.status_code == 200
    # Game owned by collection_user (not admin) must NOT appear
    assert b"Settlers of Catan" not in resp.data

    # Now claim it for admin and refetch
    _db.session.add(OwnedBy(game_id=collection_game.id, person_id=user.id))
    _db.session.commit()
    try:
        resp = admin_client.get("/games?scope=mine")
        assert b"Settlers of Catan" in resp.data
    finally:
        OwnedBy.query.filter_by(game_id=collection_game.id, person_id=user.id).delete()
        Game.query.filter_by(id=other_only_id).delete()
        _db.session.commit()


def test_games_scope_group_excludes_unowned(admin_client, db):
    """scope=group on games index excludes games with zero owners."""
    orphan = Game(name=f"Orphan {uuid.uuid4().hex[:6]}", bgg_id=None)
    _db.session.add(orphan)
    _db.session.commit()
    orphan_id, orphan_name = orphan.id, orphan.name
    try:
        resp = admin_client.get("/games?scope=group")
        assert resp.status_code == 200
        assert orphan_name.encode() not in resp.data
    finally:
        Game.query.filter_by(id=orphan_id).delete()
        _db.session.commit()


def test_games_scope_toggle_renders(admin_client, db):
    """Scope toggle UI is present on games index page."""
    resp = admin_client.get("/games")
    assert resp.status_code == 200
    assert b"scope=all" in resp.data
    assert b"scope=mine" in resp.data
    assert b"scope=group" in resp.data


def test_old_collection_routes_removed(client):
    """Legacy /collection and /collection/mine endpoints no longer exist."""
    assert client.get("/collection").status_code == 404
    assert client.get("/collection/mine").status_code == 404


def test_admin_can_assign_ownership_to_other_person(admin_client, app, db):
    """Admin posts a person_id on a game and that person becomes an owner."""
    game = Game(name=f"AssignGame {uuid.uuid4().hex[:6]}", bgg_id=None)
    target = Person(
        first_name="Tar", last_name="Get", email=f"target_{uuid.uuid4().hex[:6]}@test.invalid"
    )
    _db.session.add_all([game, target])
    _db.session.commit()
    game_id, target_id = game.id, target.id

    resp = admin_client.post(
        f"/game/{game_id}/admin_ownership",
        data={"person_id": target_id, "action": "add"},
    )
    assert resp.status_code in (200, 302)
    owns = OwnedBy.query.filter_by(game_id=game_id, person_id=target_id).first()
    assert owns is not None, "Admin add must create OwnedBy row"

    resp = admin_client.post(
        f"/game/{game_id}/admin_ownership",
        data={"person_id": target_id, "action": "remove"},
    )
    assert resp.status_code in (200, 302)
    assert OwnedBy.query.filter_by(game_id=game_id, person_id=target_id).first() is None

    Person.query.filter_by(id=target_id).delete()
    Game.query.filter_by(id=game_id).delete()
    _db.session.commit()


def test_non_admin_cannot_assign_ownership(auth_client, app, db):
    """Non-admin POST to admin endpoint must be rejected."""
    game = Game(name=f"NoAssign {uuid.uuid4().hex[:6]}", bgg_id=None)
    target = Person(
        first_name="N", last_name="A", email=f"noassign_{uuid.uuid4().hex[:6]}@test.invalid"
    )
    _db.session.add_all([game, target])
    _db.session.commit()
    game_id, target_id = game.id, target.id

    resp = auth_client.post(
        f"/game/{game_id}/admin_ownership",
        data={"person_id": target_id, "action": "add"},
    )
    assert resp.status_code in (302, 403)
    assert OwnedBy.query.filter_by(game_id=game_id, person_id=target_id).first() is None

    Person.query.filter_by(id=target_id).delete()
    Game.query.filter_by(id=game_id).delete()
    _db.session.commit()
