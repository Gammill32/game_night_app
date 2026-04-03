import uuid

import pytest

from app.extensions import db as _db
from app.models import Game, Person, Wishlist, WishlistVote


@pytest.fixture()
def wishlist_setup(app, db):
    """Two users, two games: game_a on both wishlists, game_b only on user_b's."""
    users = []
    for first, last in [("Voter", "One"), ("Voter", "Two")]:
        p = Person(
            first_name=first,
            last_name=last,
            email=f"{first.lower()}_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add(p)
        _db.session.flush()
        users.append(p)

    game_a = Game(name=f"GameA {uuid.uuid4().hex[:6]}", bgg_id=None)
    game_b = Game(name=f"GameB {uuid.uuid4().hex[:6]}", bgg_id=None)
    _db.session.add_all([game_a, game_b])
    _db.session.flush()

    # Both users want game_a
    _db.session.add(Wishlist(person_id=users[0].id, game_id=game_a.id))
    _db.session.add(Wishlist(person_id=users[1].id, game_id=game_a.id))
    # Only user_b wants game_b
    _db.session.add(Wishlist(person_id=users[1].id, game_id=game_b.id))
    _db.session.commit()

    yield {"users": users, "game_a": game_a, "game_b": game_b}

    WishlistVote.query.filter(WishlistVote.game_id.in_([game_a.id, game_b.id])).delete()
    Wishlist.query.filter(Wishlist.game_id.in_([game_a.id, game_b.id])).delete()
    for u in users:
        Person.query.filter_by(id=u.id).delete()
    _db.session.delete(game_a)
    _db.session.delete(game_b)
    _db.session.commit()


def test_group_wishlist_want_counts(app, wishlist_setup):
    from app.services.games_services import get_group_wishlist

    user_a = wishlist_setup["users"][0]
    with app.app_context():
        items = get_group_wishlist(user_a.id)

    by_id = {item["game"].id: item for item in items}
    # game_a: 2 wishlist entries
    assert by_id[wishlist_setup["game_a"].id]["total_want"] == 2
    # game_b: 1 wishlist entry
    assert by_id[wishlist_setup["game_b"].id]["total_want"] == 1


def test_group_wishlist_sorted_by_want(app, wishlist_setup):
    from app.services.games_services import get_group_wishlist

    with app.app_context():
        items = get_group_wishlist(wishlist_setup["users"][0].id)

    assert items[0]["game"].id == wishlist_setup["game_a"].id


def test_toggle_vote_adds_and_removes(app, wishlist_setup):
    from app.services.games_services import toggle_wishlist_vote

    user_a = wishlist_setup["users"][0]
    game_b_id = wishlist_setup["game_b"].id  # user_a hasn't wishlisted this

    with app.app_context():
        ok, _ = toggle_wishlist_vote(user_a.id, game_b_id)
        assert ok
        assert WishlistVote.query.filter_by(person_id=user_a.id, game_id=game_b_id).count() == 1

        ok, _ = toggle_wishlist_vote(user_a.id, game_b_id)
        assert ok
        assert WishlistVote.query.filter_by(person_id=user_a.id, game_id=game_b_id).count() == 0


def test_toggle_vote_blocked_if_wishlisted(app, wishlist_setup):
    from app.services.games_services import toggle_wishlist_vote

    user_a = wishlist_setup["users"][0]
    game_a_id = wishlist_setup["game_a"].id  # user_a already wishlisted this

    with app.app_context():
        ok, msg = toggle_wishlist_vote(user_a.id, game_a_id)
        assert not ok
        assert "wishlist" in msg.lower()


def test_vote_count_includes_votes(app, wishlist_setup):
    from app.services.games_services import get_group_wishlist, toggle_wishlist_vote

    user_a = wishlist_setup["users"][0]
    game_b_id = wishlist_setup["game_b"].id

    with app.app_context():
        toggle_wishlist_vote(user_a.id, game_b_id)
        items = get_group_wishlist(user_a.id)

    by_id = {item["game"].id: item for item in items}
    # game_b: 1 wishlist + 1 vote = 2
    assert by_id[game_b_id]["total_want"] == 2


def test_group_wishlist_page_loads(auth_client, wishlist_setup):
    resp = auth_client.get("/wishlist")
    assert resp.status_code == 200
    assert b"Group Wishlist" in resp.data
    assert wishlist_setup["game_a"].name.encode() in resp.data


def test_my_wishlist_page_loads(auth_client):
    resp = auth_client.get("/wishlist/mine")
    assert resp.status_code == 200
    assert b"My Wishlist" in resp.data
