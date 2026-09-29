import datetime as dt

from app.extensions import db as _db
from app.models import Badge, Game, GameNightGame, Player, Result
from app.services.badge_services import evaluate_badges_for_night
from tests.conftest import login


def _night_with_win(make_night, winner, loser, date):
    gn = make_night(winner, loser, date=date)
    game = Game(name=f"Stat game {date}", image_url="https://example.invalid/x.png")
    _db.session.add(game)
    _db.session.flush()
    gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
    _db.session.add(gng)
    _db.session.flush()
    pw = Player.query.filter_by(game_night_id=gn.id, people_id=winner.id).one()
    pl = Player.query.filter_by(game_night_id=gn.id, people_id=loser.id).one()
    _db.session.add_all(
        [
            Result(game_night_game_id=gng.id, player_id=pw.id, position=1),
            Result(game_night_game_id=gng.id, player_id=pl.id, position=2),
        ]
    )
    gn.final = True
    _db.session.commit()
    return gn, game


def test_stats_use_night_date_and_show_win_pct(client, make_person, make_night):
    ann, bo = make_person("Ann"), make_person("Bo")
    gn, game = _night_with_win(make_night, ann, bo, dt.date(2031, 6, 6))
    login(client, ann)
    page = " ".join(client.get("/user_stats?end_date=2031-12-31").get_data(as_text=True).split())
    assert game.name in page and "100%" in page
    # the night's date filters, not when results were typed in
    page = client.get("/user_stats?start_date=2031-07-01&end_date=2031-12-31").get_data(
        as_text=True
    )
    assert "No games match these filters" in page
    _db.session.delete(gn)
    _db.session.delete(game)
    _db.session.commit()


def test_badges_link_back_to_the_night(client, make_person, make_night):
    ann, bo = make_person("Ann"), make_person("Bo")
    gn, game = _night_with_win(make_night, ann, bo, dt.date(2031, 6, 13))
    evaluate_badges_for_night(gn.id)
    first_blood = Badge.query.filter_by(key="first_blood").one()

    login(client, ann)
    stats = client.get("/user_stats").get_data(as_text=True)
    assert f'data-badge-name="{first_blood.name}"' in stats
    assert f"/game_night/{gn.id}#badges" in stats and "June 13, 2031" in stats

    catalog = client.get("/badges").get_data(as_text=True)
    assert first_blood.description in catalog and "Earned Jun 13, 2031" in catalog

    night = client.get(f"/game_night/{gn.id}").get_data(as_text=True)
    assert "Badges earned this night" in night and first_blood.description in night

    from app.models import PersonBadge

    PersonBadge.query.filter_by(game_night_id=gn.id).delete()
    _db.session.delete(gn)
    _db.session.delete(game)
    _db.session.commit()


def test_head_to_head_and_chip_filters(client, make_person, make_night):
    ann, bo = make_person("Ann"), make_person("Bo")
    gn, game = _night_with_win(make_night, ann, bo, dt.date(2031, 6, 20))
    from app.services import games_services

    h2h = games_services.get_head_to_head(ann.id)
    assert [(h["person_id"], h["games"], h["ahead"], h["behind"]) for h in h2h] == [
        (bo.id, 1, 1, 0)
    ]
    assert games_services.get_head_to_head(bo.id)[0]["behind"] == 1
    assert games_services.get_head_to_head(ann.id, start_date="2031-07-01") == []

    login(client, ann)
    page = " ".join(client.get("/user_stats").get_data(as_text=True).split())
    # opponents and games are tappable chips, no typing needed
    assert f'name="opponent_ids" value="{bo.id}"' in page
    assert f'name="game_ids" value="{game.id}"' in page
    assert "Head to head" in page and "Bo Test" in page
    page = client.get(f"/user_stats?opponent_ids={bo.id}").get_data(as_text=True)
    assert f'name="opponent_ids" value="{bo.id}" checked' in " ".join(page.split())
    _db.session.delete(gn)
    _db.session.delete(game)
    _db.session.commit()
