import datetime
import uuid

import pytest

from app.extensions import db as _db
from app.models import Game, GameNight, GameNightGame, Person, Player, Result


@pytest.fixture()
def game_with_plays(app, db):
    """A game played in two finalized game nights, plus one non-final night."""
    game = Game(name=f"Stats Game {uuid.uuid4().hex[:6]}", bgg_id=None)
    _db.session.add(game)
    _db.session.flush()

    person = Person(
        first_name="Test",
        last_name="Player",
        email=f"statsplayer_{uuid.uuid4().hex[:6]}@test.invalid",
    )
    _db.session.add(person)
    _db.session.flush()

    nights = []
    gngs = []
    players = []
    for i, (delta, final) in enumerate([(60, True), (10, True), (5, False)]):
        gn = GameNight(
            date=datetime.date.today() - datetime.timedelta(days=delta),
            final=final,
        )
        _db.session.add(gn)
        _db.session.flush()
        nights.append(gn)

        pl = Player(game_night_id=gn.id, people_id=person.id)
        _db.session.add(pl)
        _db.session.flush()
        players.append(pl)

        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.flush()
        gngs.append(gng)

        _db.session.add(Result(game_night_game_id=gng.id, player_id=pl.id, position=1, score=10))

    _db.session.commit()
    yield {"game": game, "nights": nights, "gngs": gngs, "players": players, "person": person}

    # Teardown
    for gng in gngs:
        Result.query.filter_by(game_night_game_id=gng.id).delete()
        _db.session.delete(gng)
    for pl in players:
        _db.session.delete(pl)
    for gn in nights:
        _db.session.delete(gn)
    Person.query.filter_by(id=person.id).delete()
    _db.session.delete(game)
    _db.session.commit()


def test_get_play_stats_counts_only_final_nights(app, game_with_plays):
    from app.services.games_services import get_play_stats

    with app.app_context():
        stats = get_play_stats()

    game_id = game_with_plays["game"].id
    assert game_id in stats
    # Only 2 of the 3 game nights are final
    assert stats[game_id]["play_count"] == 2


def test_get_play_stats_last_played_is_most_recent_final(app, game_with_plays):
    from app.services.games_services import get_play_stats

    with app.app_context():
        stats = get_play_stats()

    game_id = game_with_plays["game"].id
    expected = datetime.date.today() - datetime.timedelta(days=10)
    assert stats[game_id]["last_played"] == expected


def test_games_index_includes_play_stats(auth_client, game_with_plays):
    resp = auth_client.get("/games/")
    assert resp.status_code == 200
    # Play count should appear somewhere on the page
    assert b"Played:" in resp.data or b"Played" in resp.data


def test_fatigued_game_shows_badge(auth_client, game_with_plays):
    """A game played within 30 days should show the Recently Played badge."""
    resp = auth_client.get("/games/")
    assert resp.status_code == 200
    assert b"Recently Played" in resp.data


def test_view_game_shows_play_history(auth_client, game_with_plays):
    game_id = game_with_plays["game"].id
    resp = auth_client.get(f"/game/{game_id}")
    assert resp.status_code == 200
    assert b"Play History" in resp.data
    assert b"Times Played" in resp.data
    assert b"Last Played" in resp.data


def test_view_game_shows_fatigued_badge(auth_client, game_with_plays):
    game_id = game_with_plays["game"].id
    resp = auth_client.get(f"/game/{game_id}")
    assert resp.status_code == 200
    assert b"Recently Played" in resp.data


# --- Always Bridesmaid ---


@pytest.fixture()
def bridesmaid_setup(app, db):
    """A game nominated twice but never played; another game nominated and played."""
    from app.models import GameNominations, Player

    people = []
    players_map = {}  # game_night_id -> player
    game_nights = []
    nominations = []

    # Two people
    for first, last in [("Alice", "A"), ("Bob", "B")]:
        p = Person(
            first_name=first,
            last_name=last,
            email=f"{first.lower()}_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add(p)
        _db.session.flush()
        people.append(p)

    # The bridesmaid game — nominated in two separate game nights, never played
    bridesmaid = Game(name=f"Bridesmaid {uuid.uuid4().hex[:6]}", bgg_id=None)
    _db.session.add(bridesmaid)
    _db.session.flush()

    # The played game — nominated and also played
    played_game = Game(name=f"PlayedGame {uuid.uuid4().hex[:6]}", bgg_id=None)
    _db.session.add(played_game)
    _db.session.flush()

    for i in range(2):
        gn = GameNight(date=datetime.date(2024, i + 1, 1), final=True)
        _db.session.add(gn)
        _db.session.flush()
        game_nights.append(gn)

        pl = Player(game_night_id=gn.id, people_id=people[0].id)
        _db.session.add(pl)
        _db.session.flush()
        players_map[gn.id] = pl

        nominations.append(
            GameNominations(game_night_id=gn.id, player_id=pl.id, game_id=bridesmaid.id)
        )
        _db.session.add(nominations[-1])

    # Nominate and play played_game in first night — use Bob (people[1]) to avoid
    # violating uq_game_nominations_night_player (one nomination per player per night)
    bob_player = Player(game_night_id=game_nights[0].id, people_id=people[1].id)
    _db.session.add(bob_player)
    _db.session.flush()
    nominations.append(
        GameNominations(
            game_night_id=game_nights[0].id,
            player_id=bob_player.id,
            game_id=played_game.id,
        )
    )
    _db.session.add(nominations[-1])
    gng = GameNightGame(game_night_id=game_nights[0].id, game_id=played_game.id, round=1)
    _db.session.add(gng)
    _db.session.flush()

    _db.session.commit()
    yield {"bridesmaid": bridesmaid, "played_game": played_game, "game_nights": game_nights}

    # Teardown
    GameNominations.query.filter(
        GameNominations.game_id.in_([bridesmaid.id, played_game.id])
    ).delete()
    Result.query.filter_by(game_night_game_id=gng.id).delete()
    _db.session.delete(gng)
    _db.session.delete(bob_player)
    for pl in players_map.values():
        _db.session.delete(pl)
    for gn in game_nights:
        _db.session.delete(gn)
    for p in people:
        Person.query.filter_by(id=p.id).delete()
    _db.session.delete(bridesmaid)
    _db.session.delete(played_game)
    _db.session.commit()


def test_bridesmaid_excludes_played_games(app, bridesmaid_setup):
    from app.services.games_services import get_bridesmaid_games

    with app.app_context():
        results = get_bridesmaid_games()

    ids = [r.id for r in results]
    assert bridesmaid_setup["bridesmaid"].id in ids
    assert bridesmaid_setup["played_game"].id not in ids


def test_bridesmaid_nomination_count(app, bridesmaid_setup):
    from app.services.games_services import get_bridesmaid_games

    with app.app_context():
        results = get_bridesmaid_games()

    match = next(r for r in results if r.id == bridesmaid_setup["bridesmaid"].id)
    assert match.nomination_count == 2


def test_games_index_shows_bridesmaid_section(auth_client, bridesmaid_setup):
    resp = auth_client.get("/games/")
    assert resp.status_code == 200
    assert b"Always Nominated" in resp.data
    assert bridesmaid_setup["bridesmaid"].name.encode() in resp.data
