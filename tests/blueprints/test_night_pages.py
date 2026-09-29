import datetime as dt

from app.extensions import db as _db
from app.models import Game, GameNightGame, GameNominations, OwnedBy, Player, Result
from tests.conftest import login


def _games(owner, *names):
    games = [Game(name=n, min_players=2, max_players=4, playtime=45) for n in names]
    _db.session.add_all(games)
    _db.session.flush()
    _db.session.add_all([OwnedBy(game_id=g.id, person_id=owner.id) for g in games])
    _db.session.commit()
    return games


def _cleanup(*objs):
    for o in objs:
        _db.session.delete(o)
    _db.session.commit()


def test_nominate_and_add_game_pickers(client, make_person, make_night):
    adm, ann, bo = make_person("Adm", admin=True), make_person("Ann"), make_person("Bo")
    gn = make_night(adm, ann, bo, date=dt.date(2031, 8, 1))
    azul, catan, dune = _games(ann, "PickAzul", "PickCatan", "PickDune")
    bo_player = Player.query.filter_by(game_night_id=gn.id, people_id=bo.id).one()
    _db.session.add(GameNominations(game_night_id=gn.id, player_id=bo_player.id, game_id=catan.id))
    _db.session.commit()

    login(client, ann)
    page = client.get(f"/game_night/{gn.id}/nominate").get_data(as_text=True)
    assert "PickAzul" in page and "PickDune" in page and "Owned by Ann" in page
    assert f'value="{catan.id}"' not in page  # Bo already nominated it
    assert "Fits 3 players" in page
    client.post(f"/game_night/{gn.id}/nominate", data={"game_id": azul.id})
    page = client.get(f"/game_night/{gn.id}/nominate").get_data(as_text=True)
    assert "You nominated <strong>PickAzul</strong>" in page
    assert f'value="{azul.id}" data-label="PickAzul" checked' in " ".join(page.split())

    night = " ".join(client.get(f"/game_night/{gn.id}").get_data(as_text=True).split())
    assert "What should we play?" in night and f'name="votes[{azul.id}]"' in night
    assert "Bo&#39;s pick" in night or "Bo's pick" in night

    login(client, adm)
    page = client.get(f"/game_night/{gn.id}/add_game").get_data(as_text=True)
    assert page.index("Nominated") < page.index("PickCatan") < page.index("Everything else")
    _db.session.expire_all()
    GameNominations.query.filter_by(game_night_id=gn.id).delete()
    _db.session.commit()
    _cleanup(azul, catan, dune)


def test_finalized_night_and_all_nights_list(client, make_person, make_night):
    ann, bo = make_person("Ann"), make_person("Bo")
    gn = make_night(ann, bo, date=dt.date(2031, 8, 8), final=True, notes="Big night")
    (game,) = _games(ann, "ListGame")
    gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
    _db.session.add(gng)
    _db.session.flush()
    for person, pos in ((ann, 1), (bo, 2)):
        pl = Player.query.filter_by(game_night_id=gn.id, people_id=person.id).one()
        _db.session.add(Result(game_night_game_id=gng.id, player_id=pl.id, position=pos))
    _db.session.commit()

    login(client, ann)
    night = client.get(f"/game_night/{gn.id}").get_data(as_text=True)
    assert "Friday, August 8, 2031" in night and "Finalized" in night and "Share recap" in night
    assert night.index("🥇") < night.index("Games played")
    listing = " ".join(client.get("/game_nights/all").get_data(as_text=True).split())
    assert "🏆 <strong>Ann</strong> won" in listing and "2031 · " in listing
    _db.session.delete(gng)
    _db.session.commit()
    _cleanup(game)
