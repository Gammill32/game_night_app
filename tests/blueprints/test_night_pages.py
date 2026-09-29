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


def test_changing_nomination_keeps_other_rankings(client, make_person, make_night):
    from app.models import GameVotes
    from app.services import voting_services

    ann, bo = make_person("Ann"), make_person("Bo")
    gn = make_night(ann, bo, date=dt.date(2031, 8, 15))
    a, b, c = _games(ann, "KeepA", "KeepB", "KeepC")
    ok, msg = voting_services.nominate_game(gn.id, ann.id, a.id)
    assert ok and "Next: rank" in msg
    voting_services.nominate_game(gn.id, bo.id, b.id)
    voting_services.vote_game(gn.id, ann.id, {a.id: 2, b.id: 1})
    voting_services.vote_game(gn.id, bo.id, {a.id: 1})

    ok, msg = voting_services.nominate_game(gn.id, ann.id, c.id)
    assert ok and "KeepC" in msg
    left = {(v.player.people_id, v.game_id) for v in GameVotes.query.filter_by(game_night_id=gn.id)}
    assert left == {(ann.id, b.id)}  # Ann's other ranking kept; everyone's votes for KeepA gone

    login(client, ann)
    page = " ".join(client.get(f"/game_night/{gn.id}").get_data(as_text=True).split())
    assert "You picked <strong>KeepC</strong>" in page and "You've ranked 1 game" in page
    assert "Your pick" in page
    home = client.get("/").get_data(as_text=True)
    assert "Rank your top 3" not in home  # Ann has ranked; nothing to nudge
    GameVotes.query.filter_by(game_night_id=gn.id).delete()
    GameNominations.query.filter_by(game_night_id=gn.id).delete()
    _db.session.commit()
    _cleanup(a, b, c)


def test_votes_never_outlive_a_nomination(admin_client, client, make_person, make_night):
    from app.models import GameVotes
    from app.services import game_night_services, voting_services

    ann, bo, cy = make_person("Ann"), make_person("Bo"), make_person("Cy")
    gn = make_night(ann, bo, cy, date=dt.date(2031, 8, 22))
    a, b, c = _games(ann, "GhostA", "GhostB", "GhostC")
    voting_services.nominate_game(gn.id, ann.id, a.id)
    voting_services.nominate_game(gn.id, bo.id, b.id)
    voting_services.vote_game(gn.id, cy.id, {a.id: 1, b.id: 2})

    # 1. Ann switches from GhostA to GhostC: Cy's vote for GhostA goes.
    voting_services.nominate_game(gn.id, ann.id, c.id)
    assert {v.game_id for v in GameVotes.query.filter_by(game_night_id=gn.id)} == {b.id}

    # 2. Bo is taken off the night: his nomination and everyone's votes for it go.
    ok, _ = game_night_services.edit_game_night(gn.id, str(gn.date), "", [str(ann.id), str(cy.id)])
    assert ok
    assert GameVotes.query.filter_by(game_night_id=gn.id).count() == 0

    # 3. Even a stray vote left in the table isn't shown as a nomination.
    cy_player = Player.query.filter_by(game_night_id=gn.id, people_id=cy.id).one()
    _db.session.add(GameVotes(game_night_id=gn.id, player_id=cy_player.id, game_id=a.id, rank=1))
    _db.session.commit()
    login(client, cy)
    page = client.get(f"/game_night/{gn.id}").get_data(as_text=True)
    assert "GhostC" in page and "GhostA" not in page
    assert "You've ranked" not in page  # the stray vote doesn't count as Cy's ranking

    GameVotes.query.filter_by(game_night_id=gn.id).delete()
    GameNominations.query.filter_by(game_night_id=gn.id).delete()
    _db.session.commit()
    _cleanup(a, b, c)
