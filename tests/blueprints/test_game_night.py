def test_finalize_route_triggers_badge_evaluation(admin_client, app, db):
    """Finalizing a game night should write at least one PersonBadge."""
    import datetime
    import uuid

    from app.extensions import db as _db
    from app.models import Game, GameNight, GameNightGame, Person, PersonBadge, Player, Result

    game = Game(name=f"TrigGame {uuid.uuid4().hex[:6]}", bgg_id=None)
    person = Person(
        first_name="Trig",
        last_name="Test",
        email=f"trig_{uuid.uuid4().hex[:6]}@test.invalid",
    )
    other = Person(
        first_name="Oth",
        last_name="Trig",
        email=f"othtrig_{uuid.uuid4().hex[:6]}@test.invalid",
    )
    _db.session.add_all([game, person, other])
    _db.session.flush()

    gn = GameNight(date=datetime.date.today(), final=False)
    _db.session.add(gn)
    _db.session.flush()

    pl = Player(game_night_id=gn.id, people_id=person.id)
    op = Player(game_night_id=gn.id, people_id=other.id)
    _db.session.add_all([pl, op])
    _db.session.flush()

    gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
    _db.session.add(gng)
    _db.session.flush()

    _db.session.add(Result(game_night_game_id=gng.id, player_id=pl.id, position=1, score=10))
    _db.session.add(Result(game_night_game_id=gng.id, player_id=op.id, position=2, score=5))
    _db.session.commit()

    person_id = person.id
    other_id = other.id
    gn_id = gn.id
    gng_id = gng.id
    pl_id = pl.id
    op_id = op.id

    resp = admin_client.post(f"/game_night/{gn_id}/toggle/final")
    assert resp.status_code in (200, 302)

    from app.models import Badge

    first_blood = Badge.query.filter_by(key="first_blood").first()
    assert first_blood is not None, "first_blood badge must exist in the catalog"
    winner_earned = PersonBadge.query.filter_by(
        person_id=person_id, badge_id=first_blood.id
    ).first()
    assert winner_earned is not None, "winner should have earned first_blood"
    assert winner_earned.game_night_id == gn_id, "badge should be linked to the finalized night"

    PersonBadge.query.filter(PersonBadge.person_id.in_([person_id, other_id])).delete()
    Result.query.filter_by(game_night_game_id=gng_id).delete()
    Player.query.filter_by(id=pl_id).delete()
    Player.query.filter_by(id=op_id).delete()
    GameNightGame.query.filter_by(id=gng_id).delete()
    GameNight.query.filter_by(id=gn_id).delete()
    Person.query.filter_by(id=person_id).delete()
    Person.query.filter_by(id=other_id).delete()
    Game.query.filter_by(id=game.id).delete()
    _db.session.commit()


def test_finalize_succeeds_even_if_badge_evaluation_raises(admin_client, app, db, monkeypatch):
    """Finalization must not be blocked by badge evaluation errors."""
    import datetime
    import uuid

    from app.extensions import db as _db
    from app.models import Game, GameNight, Person, Player

    game = Game(name=f"SafeGame {uuid.uuid4().hex[:6]}", bgg_id=None)
    person = Person(
        first_name="Safe",
        last_name="Test",
        email=f"safe_{uuid.uuid4().hex[:6]}@test.invalid",
    )
    _db.session.add_all([game, person])
    _db.session.flush()

    gn = GameNight(date=datetime.date.today(), final=False)
    _db.session.add(gn)
    _db.session.flush()

    pl = Player(game_night_id=gn.id, people_id=person.id)
    _db.session.add(pl)
    _db.session.commit()

    gn_id = gn.id
    pl_id = pl.id
    person_id = person.id
    game_id = game.id

    import app.services.badge_services as bs

    monkeypatch.setattr(
        bs,
        "evaluate_badges_for_night",
        lambda _: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    resp = admin_client.post(f"/game_night/{gn_id}/toggle/final")
    assert resp.status_code in (200, 302)

    from app.models import GameNight as GN

    updated = GN.query.get(gn_id)
    assert (
        updated.final is True
    ), "Game night must be marked final even when badge evaluation raises"

    Player.query.filter_by(id=pl_id).delete()
    GameNight.query.filter_by(id=gn_id).delete()
    Person.query.filter_by(id=person_id).delete()
    Game.query.filter_by(id=game_id).delete()
    _db.session.commit()


def test_toggle_invalid_field_is_rejected(admin_client, app, db):
    """toggle_game_night_field must reject fields not in the allowlist."""
    import datetime
    import uuid

    from app.extensions import db as _db
    from app.models import GameNight, Person, Player

    person = Person(
        first_name="T", last_name="T", email=f"toggle_{uuid.uuid4().hex[:6]}@test.invalid"
    )
    _db.session.add(person)
    _db.session.flush()
    gn = GameNight(date=datetime.date.today(), final=False)
    _db.session.add(gn)
    _db.session.flush()
    pl = Player(game_night_id=gn.id, people_id=person.id)
    _db.session.add(pl)
    _db.session.commit()
    gn_id, pl_id, person_id = gn.id, pl.id, person.id

    resp = admin_client.post(f"/game_night/{gn_id}/toggle/id")
    assert resp.status_code in (400, 404, 302)

    # Confirm id was not modified
    from app.models import GameNight as GN

    fresh = GN.query.get(gn_id)
    assert fresh.id == gn_id

    Player.query.filter_by(id=pl_id).delete()
    GameNight.query.filter_by(id=gn_id).delete()
    Person.query.filter_by(id=person_id).delete()
    _db.session.commit()


def test_toggle_closed_auto_closes_availability_poll(admin_client, app, db):
    """Closing voting on a game night should auto-close its availability poll."""
    import datetime
    import uuid

    from app.extensions import db as _db
    from app.models import GameNight, Person
    from app.services.poll_services import create_availability_poll

    person = Person(
        first_name="P", last_name="Q", email=f"avclose_{uuid.uuid4().hex[:6]}@test.invalid"
    )
    _db.session.add(person)
    _db.session.flush()
    gn = GameNight(date=datetime.date.today(), closed=False, final=False)
    _db.session.add(gn)
    _db.session.commit()
    create_availability_poll(gn.id, person.id)
    poll = gn.availability_poll
    gn_id, person_id, poll_id = gn.id, person.id, poll.id
    assert poll.closed is False

    resp = admin_client.post(f"/game_night/{gn_id}/toggle/closed")
    assert resp.status_code in (200, 302)

    from app.models import Poll

    refreshed = Poll.query.get(poll_id)
    assert refreshed.closed is True, "Availability poll must auto-close when voting closes"

    from app.models import PollOption, PollResponse

    PollResponse.query.filter_by(poll_id=poll_id).delete()
    PollOption.query.filter_by(poll_id=poll_id).delete()
    Poll.query.filter_by(id=poll_id).delete()
    GameNight.query.filter_by(id=gn_id).delete()
    Person.query.filter_by(id=person_id).delete()
    _db.session.commit()


def test_night_page_shows_rsvps_and_linked_poll_to_players(auth_client, app, db):
    """Players see the availability poll on the night page and RSVP badges by name."""
    import datetime
    import uuid

    from app.extensions import db as _db
    from app.models import GameNight, Person, Player
    from app.services.poll_services import create_availability_poll, submit_response

    user = Person.query.filter_by(email="test@example.com").first()
    other = Person(
        first_name="Rsvp", last_name="Other", email=f"rsvp_{uuid.uuid4().hex[:6]}@x.invalid"
    )
    _db.session.add(other)
    gn = GameNight(date=datetime.date(2026, 10, 4))
    _db.session.add(gn)
    _db.session.flush()
    _db.session.add_all(
        [
            Player(game_night_id=gn.id, people_id=user.id),
            Player(game_night_id=gn.id, people_id=other.id),
        ]
    )
    _db.session.commit()
    create_availability_poll(gn.id, other.id)
    poll = gn.availability_poll
    submit_response(poll, [poll.options[1].id], other.id)  # Maybe

    body = " ".join(auth_client.get(f"/game_night/{gn.id}").data.decode().split())
    assert poll.title in body
    assert 'name="option_ids"' in body
    assert "Maybe</span>" in body
    assert "no reply" in body
    assert "0 of 2 can make it" in body

    _db.session.delete(poll)
    _db.session.delete(gn)
    _db.session.delete(other)
    _db.session.commit()


def test_edit_removing_player_who_voted_does_not_crash(admin_client, make_person, make_night):
    from app.extensions import db as _db
    from app.models import Game, GameNominations, Player

    ann, bo = make_person("Ann"), make_person("Bo")
    gn = make_night(ann, bo)
    game = Game(name="Nominated")
    _db.session.add(game)
    _db.session.flush()
    bo_player = Player.query.filter_by(game_night_id=gn.id, people_id=bo.id).one()
    _db.session.add(GameNominations(game_night_id=gn.id, player_id=bo_player.id, game_id=game.id))
    _db.session.commit()

    resp = admin_client.post(
        f"/game_night/{gn.id}/edit",
        data={"date": str(gn.date), "notes": "", "attendees": [str(ann.id)], "food_mode": "none"},
    )
    assert resp.status_code == 302
    assert {p.people_id for p in gn.players} == {ann.id}
    assert GameNominations.query.filter_by(game_night_id=gn.id).count() == 0
    _db.session.delete(game)
    _db.session.commit()


def test_edit_refuses_removing_player_with_results(admin_client, make_person, make_night):
    from app.extensions import db as _db
    from app.models import Game, GameNightGame, Player, Result

    ann, bo = make_person("Ann"), make_person("Bo")
    gn = make_night(ann, bo)
    game = Game(name="Played")
    _db.session.add(game)
    _db.session.flush()
    gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
    _db.session.add(gng)
    _db.session.flush()
    bo_player = Player.query.filter_by(game_night_id=gn.id, people_id=bo.id).one()
    _db.session.add(Result(game_night_game_id=gng.id, player_id=bo_player.id, position=1))
    _db.session.commit()

    resp = admin_client.post(
        f"/game_night/{gn.id}/edit",
        data={"date": str(gn.date), "notes": "", "attendees": [str(ann.id)], "food_mode": "none"},
    )
    assert "results logged" in resp.get_data(as_text=True)  # re-rendered with the error
    _db.session.expire_all()
    assert {p.people_id for p in gn.players} == {ann.id, bo.id}
    _db.session.delete(gn)
    _db.session.delete(game)
    _db.session.commit()


def test_start_night_with_rsvp_poll(admin_client, make_person):
    from app.extensions import db as _db
    from app.models import GameNight

    ann = make_person("Ann")
    admin_client.post(
        "/game_night/start",
        data={
            "date": "2031-02-03",
            "attendees": [str(ann.id)],
            "food_mode": "none",
            "rsvp_poll": "1",
        },
    )
    gn = GameNight.query.filter_by(date="2031-02-03").order_by(GameNight.id.desc()).first()
    assert gn.availability_poll is not None
    assert "February 3, 2031" in gn.availability_poll.title

    admin_client.post(
        f"/game_night/{gn.id}/edit",
        data={"date": "2031-02-10", "attendees": [str(ann.id)], "food_mode": "none"},
    )
    assert "February 10, 2031" in gn.availability_poll.title
    _db.session.delete(gn.availability_poll)
    _db.session.delete(gn)
    _db.session.commit()


def test_start_and_edit_pages_render(admin_client, make_person, make_night):
    ann = make_person("O'Brien")
    gn = make_night(ann)
    for url in ("/game_night/start", f"/game_night/{gn.id}/edit"):
        page = admin_client.get(url).get_data(as_text=True)
        assert "attendeesContainer" in page and "Food plan" in page
        assert "O\\u0027Brien" in page or "O'Brien" in page
