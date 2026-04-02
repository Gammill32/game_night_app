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
