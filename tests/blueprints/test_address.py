import datetime as dt

from app.extensions import db as _db
from app.models import GameNight
from tests.conftest import login

ADDRESS = "742 Evergreen Terrace"


def test_address_is_private_and_deleted_on_finalize(admin_client, client, make_person, make_night):
    ann, outsider = make_person("Ann"), make_person("Out")
    gn = make_night(ann, date=dt.date(2031, 12, 5))
    admin_client.post(
        f"/game_night/{gn.id}/edit",
        data={
            "date": "2031-12-05",
            "attendees": [str(ann.id)],
            "food_mode": "none",
            "address": f"  {ADDRESS} ",
        },
    )
    _db.session.refresh(gn)
    assert gn.address == ADDRESS

    login(client, ann)
    page = client.get(f"/game_night/{gn.id}").get_data(as_text=True)
    assert ADDRESS in page and "Open in Maps" in page
    login(client, outsider)
    assert ADDRESS not in client.get(f"/game_night/{gn.id}", follow_redirects=True).get_data(
        as_text=True
    )

    from app.models import Game, GameNightGame, Player, Result
    from app.services.game_night_services import finalize

    gn.date = dt.date(2024, 1, 1)  # the night has happened and a game has results
    game = Game(name="Address test game")
    _db.session.add(game)
    _db.session.flush()
    gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
    _db.session.add(gng)
    _db.session.flush()
    player = Player.query.filter_by(game_night_id=gn.id, people_id=ann.id).one()
    _db.session.add(Result(game_night_game_id=gng.id, player_id=player.id, position=1))
    _db.session.commit()
    finalize(gn.id)
    _db.session.refresh(gn)
    assert gn.final and gn.address is None
    recap = client.get(f"/game_night/{gn.id}/recap").get_data(as_text=True)
    assert ADDRESS not in recap


def test_past_addresses_are_cleared_by_the_daily_job(app, make_person, make_night, monkeypatch):
    import pytz

    from app.services import reminders_services

    ann = make_person("Ann")
    today = dt.datetime.now(pytz.timezone(app.config["APP_TIMEZONE"])).date()
    old = make_night(ann, date=today - dt.timedelta(days=2), address=ADDRESS)
    soon = make_night(ann, date=today + dt.timedelta(days=1), address="1 Soon St")
    sent = {}
    monkeypatch.setattr(reminders_services, "send_email", lambda to, s, b: sent.__setitem__(to, b))
    reminders_services.check_and_send_reminders()
    _db.session.refresh(old)
    _db.session.refresh(soon)
    assert old.address is None and soon.address == "1 Soon St"
    assert "1 Soon St" not in sent[ann.email]  # addresses never go out by email


def test_host_sets_address_when_starting(client, make_person):
    hana = make_person("Hana")
    hana.can_host = True
    _db.session.commit()
    login(client, hana)
    client.post(
        "/game_night/start",
        data={
            "date": "2031-12-12",
            "attendees": [str(hana.id)],
            "food_mode": "none",
            "address": ADDRESS,
        },
    )
    gn = GameNight.query.filter_by(date=dt.date(2031, 12, 12)).order_by(GameNight.id.desc()).first()
    assert gn.address == ADDRESS
    _db.session.delete(gn)
    _db.session.commit()
