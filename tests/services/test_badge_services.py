import datetime
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.extensions import db as _db
from app.models import (
    Badge,
    Game,
    GameNight,
    GameNightGame,
    GameNominations,
    Person,
    PersonBadge,
    Player,
    Result,
)


def test_badge_model_can_be_created(app, db):
    with app.app_context():
        badge = Badge(
            key=f"test_{uuid.uuid4().hex[:6]}", name="Test", description="desc", icon="🎯"
        )
        _db.session.add(badge)
        _db.session.commit()
        assert badge.id is not None
        _db.session.delete(badge)
        _db.session.commit()


def test_person_badge_unique_constraint(app, db):
    with app.app_context():
        badge = Badge(key=f"uniq_{uuid.uuid4().hex[:6]}", name="Uniq", description="d", icon="⭐")
        person = Person(
            first_name="A",
            last_name="B",
            email=f"badge_test_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add_all([badge, person])
        _db.session.flush()

        pb = PersonBadge(person_id=person.id, badge_id=badge.id)
        _db.session.add(pb)
        _db.session.commit()

        pb2 = PersonBadge(person_id=person.id, badge_id=badge.id)
        _db.session.add(pb2)
        with pytest.raises(IntegrityError):
            _db.session.flush()

        _db.session.rollback()
        PersonBadge.query.filter_by(person_id=person.id).delete()
        _db.session.delete(badge)
        _db.session.delete(person)
        _db.session.commit()


@pytest.fixture()
def badge_night(app, db):
    """A finalized game night with two players and one game result."""
    with app.app_context():
        game = Game(name=f"BGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        winner = Person(
            first_name="Winner",
            last_name="One",
            email=f"winner_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        loser = Person(
            first_name="Loser",
            last_name="Two",
            email=f"loser_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add_all([game, winner, loser])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=1), final=True)
        _db.session.add(gn)
        _db.session.flush()

        winner_player = Player(game_night_id=gn.id, people_id=winner.id)
        loser_player = Player(game_night_id=gn.id, people_id=loser.id)
        _db.session.add_all([winner_player, loser_player])
        _db.session.flush()

        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.flush()

        _db.session.add(
            Result(game_night_game_id=gng.id, player_id=winner_player.id, position=1, score=10)
        )
        _db.session.add(
            Result(game_night_game_id=gng.id, player_id=loser_player.id, position=2, score=5)
        )
        _db.session.commit()

        yield {
            "game_night": gn,
            "game": game,
            "winner": winner,
            "loser": loser,
            "winner_player": winner_player,
            "loser_player": loser_player,
            "gng": gng,
        }

        _db.session.rollback()
        Result.query.filter_by(game_night_game_id=gng.id).delete()
        _db.session.delete(gng)
        _db.session.delete(winner_player)
        _db.session.delete(loser_player)
        PersonBadge.query.filter_by(game_night_id=gn.id).delete()
        _db.session.delete(gn)
        _db.session.delete(winner)
        _db.session.delete(loser)
        _db.session.delete(game)
        _db.session.commit()


def test_evaluate_badges_awards_first_blood(app, db, badge_night):
    from app.services.badge_services import evaluate_badges_for_night

    with app.app_context():
        winner_id = badge_night["winner"].id
        gn_id = badge_night["game_night"].id

        PersonBadge.query.filter_by(person_id=winner_id).delete()
        _db.session.commit()

        evaluate_badges_for_night(gn_id)

        badge = Badge.query.filter_by(key="first_blood").first()
        earned = PersonBadge.query.filter_by(person_id=winner_id, badge_id=badge.id).first()
        assert earned is not None


def test_evaluate_badges_does_not_duplicate(app, db, badge_night):
    from app.services.badge_services import evaluate_badges_for_night

    with app.app_context():
        winner_id = badge_night["winner"].id
        gn_id = badge_night["game_night"].id

        PersonBadge.query.filter_by(person_id=winner_id).delete()
        _db.session.commit()

        evaluate_badges_for_night(gn_id)
        evaluate_badges_for_night(gn_id)  # second call should not duplicate

        badge = Badge.query.filter_by(key="first_blood").first()
        count = PersonBadge.query.filter_by(person_id=winner_id, badge_id=badge.id).count()
        assert count == 1


def test_evaluate_badges_does_not_raise_on_bad_night(app, db):
    from app.services.badge_services import evaluate_badges_for_night

    with app.app_context():
        evaluate_badges_for_night(999999)
        # Must not write any PersonBadge rows for the nonexistent night
        count = PersonBadge.query.filter_by(game_night_id=999999).count()
        assert count == 0


def test_evaluate_badges_skips_unfinalized_night(app, db, badge_night):
    """evaluate_badges_for_night must do nothing on an unfinalized night."""
    from app.services.badge_services import evaluate_badges_for_night

    with app.app_context():
        gn_id = badge_night["game_night"].id
        winner_id = badge_night["winner"].id

        # Un-finalize the night
        from app.models import GameNight as GN

        gn = GN.query.get(gn_id)
        gn.final = False
        _db.session.commit()

        PersonBadge.query.filter_by(person_id=winner_id).delete()
        _db.session.commit()

        evaluate_badges_for_night(gn_id)

        count = PersonBadge.query.filter_by(person_id=winner_id).count()
        assert count == 0, "No badges should be awarded for an unfinalized night"

        # Restore for fixture teardown
        gn.final = True
        _db.session.commit()


# ---------------------------------------------------------------------------
# Group A: single-night wins/placements
# ---------------------------------------------------------------------------


def test_first_blood_earns_on_first_win(app, db, badge_night):
    from app.services.badge_services import _check_first_blood

    with app.app_context():
        assert _check_first_blood(badge_night["winner"].id, badge_night["game_night"].id) is True


def test_first_blood_does_not_earn_for_loser(app, db, badge_night):
    from app.services.badge_services import _check_first_blood

    with app.app_context():
        assert _check_first_blood(badge_night["loser"].id, badge_night["game_night"].id) is False


@pytest.fixture()
def hat_trick_night(app, db):
    """A game night where one player wins 3 games."""
    with app.app_context():
        game = Game(name=f"HTGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        player_person = Person(
            first_name="HT",
            last_name="Player",
            email=f"ht_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        other = Person(
            first_name="Other",
            last_name="HT",
            email=f"other_ht_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add_all([game, player_person, other])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=2), final=True)
        _db.session.add(gn)
        _db.session.flush()

        p1 = Player(game_night_id=gn.id, people_id=player_person.id)
        p2 = Player(game_night_id=gn.id, people_id=other.id)
        _db.session.add_all([p1, p2])
        _db.session.flush()

        gngs = []
        for i in range(3):
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=i + 1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(
                Result(game_night_game_id=gng.id, player_id=p1.id, position=1, score=10)
            )
            _db.session.add(Result(game_night_game_id=gng.id, player_id=p2.id, position=2, score=5))

        _db.session.commit()
        yield {"gn": gn, "player": player_person, "other": other, "gngs": gngs, "p1": p1, "p2": p2}

        _db.session.rollback()
        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        _db.session.delete(p1)
        _db.session.delete(p2)
        _db.session.delete(gn)
        _db.session.delete(player_person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()


def test_hat_trick_earns_with_3_wins(app, db, hat_trick_night):
    from app.services.badge_services import _check_hat_trick

    with app.app_context():
        assert _check_hat_trick(hat_trick_night["player"].id, hat_trick_night["gn"].id) is True


def test_hat_trick_does_not_earn_with_1_win(app, db, badge_night):
    from app.services.badge_services import _check_hat_trick

    with app.app_context():
        assert _check_hat_trick(badge_night["winner"].id, badge_night["game_night"].id) is False


def test_bench_warmer_earns_when_always_last(app, db, badge_night):
    from app.services.badge_services import _check_bench_warmer

    with app.app_context():
        assert _check_bench_warmer(badge_night["loser"].id, badge_night["game_night"].id) is True


def test_bench_warmer_does_not_earn_for_winner(app, db, badge_night):
    from app.services.badge_services import _check_bench_warmer

    with app.app_context():
        assert _check_bench_warmer(badge_night["winner"].id, badge_night["game_night"].id) is False


def test_bench_warmer_does_not_earn_in_solo_game(app, db):
    """bench_warmer must not fire when only one player has a recorded result."""
    from app.services.badge_services import _check_bench_warmer

    with app.app_context():
        game = Game(name=f"Solo {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(
            first_name="Solo", last_name="Player", email=f"solo_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all([game, person])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=2), final=True)
        _db.session.add(gn)
        _db.session.flush()

        player = Player(game_night_id=gn.id, people_id=person.id)
        _db.session.add(player)
        _db.session.flush()

        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.flush()

        _db.session.add(Result(game_night_game_id=gng.id, player_id=player.id, position=1))
        _db.session.commit()

        assert _check_bench_warmer(person.id, gn.id) is False

        Result.query.filter_by(game_night_game_id=gng.id).delete()
        _db.session.delete(gng)
        _db.session.delete(player)
        PersonBadge.query.filter_by(game_night_id=gn.id).delete()
        _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(game)
        _db.session.commit()


def test_jack_of_all_trades_earns_when_top_half(app, db, badge_night):
    # badge_night: 2 players, winner is position 1 (top half of 2 = 1)
    from app.services.badge_services import _check_jack_of_all_trades

    with app.app_context():
        assert (
            _check_jack_of_all_trades(badge_night["winner"].id, badge_night["game_night"].id)
            is True
        )


def test_jack_of_all_trades_does_not_earn_when_last(app, db, badge_night):
    from app.services.badge_services import _check_jack_of_all_trades

    with app.app_context():
        assert (
            _check_jack_of_all_trades(badge_night["loser"].id, badge_night["game_night"].id)
            is False
        )


def test_jack_of_all_trades_earns_for_middle_player_in_3_player_game(app, db):
    # 3 players: top half = positions 1 and 2 (floor((3+1)/2) = 2); position 3 does not earn.
    from app.services.badge_services import _check_jack_of_all_trades

    with app.app_context():
        game = Game(name=f"Jack3Game {uuid.uuid4().hex[:6]}", bgg_id=None)
        p1 = Person(
            first_name="J3P1", last_name="X", email=f"j3p1_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        p2 = Person(
            first_name="J3P2", last_name="X", email=f"j3p2_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        p3 = Person(
            first_name="J3P3", last_name="X", email=f"j3p3_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all([game, p1, p2, p3])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=2), final=True)
        _db.session.add(gn)
        _db.session.flush()

        pl1 = Player(game_night_id=gn.id, people_id=p1.id)
        pl2 = Player(game_night_id=gn.id, people_id=p2.id)
        pl3 = Player(game_night_id=gn.id, people_id=p3.id)
        _db.session.add_all([pl1, pl2, pl3])
        _db.session.flush()

        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.flush()

        _db.session.add(Result(game_night_game_id=gng.id, player_id=pl1.id, position=1, score=30))
        _db.session.add(Result(game_night_game_id=gng.id, player_id=pl2.id, position=2, score=20))
        _db.session.add(Result(game_night_game_id=gng.id, player_id=pl3.id, position=3, score=10))
        _db.session.commit()

        assert _check_jack_of_all_trades(p1.id, gn.id) is True
        assert _check_jack_of_all_trades(p2.id, gn.id) is True
        assert _check_jack_of_all_trades(p3.id, gn.id) is False

        Result.query.filter_by(game_night_game_id=gng.id).delete()
        _db.session.delete(gng)
        _db.session.delete(pl1)
        _db.session.delete(pl2)
        _db.session.delete(pl3)
        PersonBadge.query.filter_by(game_night_id=gn.id).delete()
        _db.session.delete(gn)
        _db.session.delete(p1)
        _db.session.delete(p2)
        _db.session.delete(p3)
        _db.session.delete(game)
        _db.session.commit()


@pytest.fixture()
def diplomat_night(app, db):
    """A game night where all players tied at position 1."""
    with app.app_context():
        game = Game(name=f"DipGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        p1 = Person(
            first_name="D1", last_name="P", email=f"dip1_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        p2 = Person(
            first_name="D2", last_name="P", email=f"dip2_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all([game, p1, p2])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=3), final=True)
        _db.session.add(gn)
        _db.session.flush()

        pl1 = Player(game_night_id=gn.id, people_id=p1.id)
        pl2 = Player(game_night_id=gn.id, people_id=p2.id)
        _db.session.add_all([pl1, pl2])
        _db.session.flush()

        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.flush()
        _db.session.add(Result(game_night_game_id=gng.id, player_id=pl1.id, position=1, score=10))
        _db.session.add(Result(game_night_game_id=gng.id, player_id=pl2.id, position=1, score=10))
        _db.session.commit()

        yield {"gn": gn, "game": game, "p1": p1, "p2": p2, "pl1": pl1, "pl2": pl2, "gng": gng}

        _db.session.rollback()
        Result.query.filter_by(game_night_game_id=gng.id).delete()
        _db.session.delete(gng)
        _db.session.delete(pl1)
        _db.session.delete(pl2)
        _db.session.delete(gn)
        _db.session.delete(p1)
        _db.session.delete(p2)
        _db.session.delete(game)
        _db.session.commit()


def test_the_diplomat_earns_when_all_tied(app, db, diplomat_night):
    from app.services.badge_services import _check_the_diplomat

    with app.app_context():
        assert _check_the_diplomat(diplomat_night["p1"].id, diplomat_night["gn"].id) is True


def test_the_diplomat_does_not_earn_when_not_all_tied(app, db, badge_night):
    from app.services.badge_services import _check_the_diplomat

    with app.app_context():
        assert _check_the_diplomat(badge_night["winner"].id, badge_night["game_night"].id) is False


def test_the_diplomat_does_not_earn_with_no_results_recorded(app, db):
    """the_diplomat must not award badge when games have no results at all."""
    from app.services.badge_services import _check_the_diplomat

    with app.app_context():
        game = Game(name=f"EmptyGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(
            first_name="Dip",
            last_name="Empty",
            email=f"dipempty_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add_all([game, person])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=3), final=True)
        _db.session.add(gn)
        _db.session.flush()

        player = Player(game_night_id=gn.id, people_id=person.id)
        _db.session.add(player)
        _db.session.flush()

        # Game with NO results
        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.commit()

        assert _check_the_diplomat(person.id, gn.id) is False

        _db.session.delete(gng)
        _db.session.delete(player)
        PersonBadge.query.filter_by(game_night_id=gn.id).delete()
        _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(game)
        _db.session.commit()


def test_opening_night_earns_for_attendee_of_first_night(app, db):
    """opening_night earns for anyone who attended the earliest recorded game night."""
    from app.services.badge_services import _check_opening_night

    with app.app_context():
        # Use a date far in the past to guarantee this is the first night in the DB
        first_date = datetime.date(1900, 1, 1)
        later_date = datetime.date(1900, 1, 2)

        game = Game(name=f"OGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        founder = Person(
            first_name="Founder",
            last_name="One",
            email=f"founder_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        latecomer = Person(
            first_name="Late", last_name="Comer", email=f"late_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all([game, founder, latecomer])
        _db.session.flush()

        first_gn = GameNight(date=first_date, final=True)
        later_gn = GameNight(date=later_date, final=True)
        _db.session.add_all([first_gn, later_gn])
        _db.session.flush()

        founder_player = Player(game_night_id=first_gn.id, people_id=founder.id)
        latecomer_player = Player(game_night_id=later_gn.id, people_id=latecomer.id)
        _db.session.add_all([founder_player, latecomer_player])
        _db.session.commit()

        # Founder attended the first night — earns badge regardless of which night we evaluate
        assert _check_opening_night(founder.id, later_gn.id) is True
        # Latecomer only attended a later night — does not earn
        assert _check_opening_night(latecomer.id, later_gn.id) is False

        _db.session.delete(founder_player)
        _db.session.delete(latecomer_player)
        PersonBadge.query.filter_by(game_night_id=first_gn.id).delete()
        PersonBadge.query.filter_by(game_night_id=later_gn.id).delete()
        _db.session.delete(first_gn)
        _db.session.delete(later_gn)
        _db.session.delete(founder)
        _db.session.delete(latecomer)
        _db.session.delete(game)
        _db.session.commit()


# ---------------------------------------------------------------------------
# Group B: history-aware single-night badges
# ---------------------------------------------------------------------------


@pytest.fixture()
def redemption_setup(app, db):
    """Player lost game X 3 times, then wins it tonight."""
    with app.app_context():
        game = Game(name=f"RGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(
            first_name="Red", last_name="Arc", email=f"red_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        other = Person(
            first_name="Other",
            last_name="Red",
            email=f"other_red_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add_all([game, person, other])
        _db.session.flush()

        nights = []
        players = []
        gngs = []
        for i, (delta, pos) in enumerate([(30, 2), (20, 2), (10, 2), (1, 1)]):
            gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=delta), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)

            pl = Player(game_night_id=gn.id, people_id=person.id)
            op = Player(game_night_id=gn.id, people_id=other.id)
            _db.session.add_all([pl, op])
            _db.session.flush()
            players.append(pl)

            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)

            _db.session.add(
                Result(game_night_game_id=gng.id, player_id=pl.id, position=pos, score=5)
            )
            _db.session.add(
                Result(
                    game_night_game_id=gng.id,
                    player_id=op.id,
                    position=1 if pos != 1 else 2,
                    score=10,
                )
            )

        _db.session.commit()
        tonight = nights[-1]
        yield {
            "person": person,
            "game": game,
            "tonight": tonight,
            "nights": nights,
            "gngs": gngs,
            "players": players,
            "other": other,
        }

        _db.session.rollback()
        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in players:
            _db.session.delete(pl)
        for gn in nights:
            # also delete the op Players for each night before deleting the night
            Player.query.filter_by(game_night_id=gn.id).delete()
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        PersonBadge.query.filter_by(person_id=person.id).delete()
        _db.session.delete(person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()


def test_redemption_arc_earns_after_3_losses(app, db, redemption_setup):
    from app.services.badge_services import _check_redemption_arc

    with app.app_context():
        assert (
            _check_redemption_arc(redemption_setup["person"].id, redemption_setup["tonight"].id)
            is True
        )


def test_redemption_arc_does_not_earn_without_enough_losses(app, db, badge_night):
    from app.services.badge_services import _check_redemption_arc

    with app.app_context():
        assert (
            _check_redemption_arc(badge_night["winner"].id, badge_night["game_night"].id) is False
        )


@pytest.fixture()
def rematch_setup(app, db):
    """Player attended two consecutive nights, both including same game."""
    with app.app_context():
        game = Game(name=f"RM {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(
            first_name="Re", last_name="Match", email=f"rm_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        other = Person(
            first_name="Oth", last_name="RM", email=f"othrm_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all([game, person, other])
        _db.session.flush()

        nights = []
        players = []
        gngs = []
        for delta in [5, 1]:
            gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=delta), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)

            pl = Player(game_night_id=gn.id, people_id=person.id)
            op = Player(game_night_id=gn.id, people_id=other.id)
            _db.session.add_all([pl, op])
            _db.session.flush()
            players.append((pl, op))

            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(
                Result(game_night_game_id=gng.id, player_id=pl.id, position=1, score=10)
            )
            _db.session.add(Result(game_night_game_id=gng.id, player_id=op.id, position=2, score=5))

        _db.session.commit()
        yield {
            "person": person,
            "tonight": nights[-1],
            "nights": nights,
            "gngs": gngs,
            "players": players,
        }

        _db.session.rollback()
        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl_pair in players:
            for pl in pl_pair:
                _db.session.delete(pl)
        for gn in nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        PersonBadge.query.filter_by(person_id=person.id).delete()
        _db.session.delete(person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()


def test_the_rematch_earns_when_same_game_back_to_back(app, db, rematch_setup):
    from app.services.badge_services import _check_the_rematch

    with app.app_context():
        assert _check_the_rematch(rematch_setup["person"].id, rematch_setup["tonight"].id) is True


def test_the_rematch_does_not_earn_on_first_night(app, db, badge_night):
    from app.services.badge_services import _check_the_rematch

    with app.app_context():
        # Only one night exists for this person in badge_night
        assert _check_the_rematch(badge_night["winner"].id, badge_night["game_night"].id) is False


@pytest.fixture()
def dark_horse_setup(app, db):
    """Player loses first 3 games in one night, wins the 4th."""
    with app.app_context():
        game = Game(name=f"DH {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(
            first_name="Dark", last_name="Horse", email=f"dh_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        other = Person(
            first_name="Oth", last_name="DH", email=f"othdh_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all([game, person, other])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=1), final=True)
        _db.session.add(gn)
        _db.session.flush()

        pl = Player(game_night_id=gn.id, people_id=person.id)
        op = Player(game_night_id=gn.id, people_id=other.id)
        _db.session.add_all([pl, op])
        _db.session.flush()

        gngs = []
        positions = [2, 2, 2, 1]  # lose 3, win last
        for i, pos in enumerate(positions):
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=i + 1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(
                Result(game_night_game_id=gng.id, player_id=pl.id, position=pos, score=5)
            )
            _db.session.add(
                Result(game_night_game_id=gng.id, player_id=op.id, position=3 - pos, score=5)
            )

        _db.session.commit()
        yield {
            "person": person,
            "gn": gn,
            "gngs": gngs,
            "pl": pl,
            "op": op,
            "other": other,
            "game": game,
        }

        _db.session.rollback()
        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        _db.session.delete(pl)
        _db.session.delete(op)
        PersonBadge.query.filter_by(game_night_id=gn.id).delete()
        _db.session.delete(gn)
        PersonBadge.query.filter_by(person_id=person.id).delete()
        _db.session.delete(person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()


def test_dark_horse_earns_after_3_losses_then_win(app, db, dark_horse_setup):
    from app.services.badge_services import _check_dark_horse

    with app.app_context():
        assert _check_dark_horse(dark_horse_setup["person"].id, dark_horse_setup["gn"].id) is True


def test_dark_horse_does_not_earn_with_only_3_games(app, db, hat_trick_night):
    from app.services.badge_services import _check_dark_horse

    with app.app_context():
        # hat_trick_night has 3 games, not 4
        assert _check_dark_horse(hat_trick_night["other"].id, hat_trick_night["gn"].id) is False


# ---------------------------------------------------------------------------
# Group C: attendance / cumulative count
# ---------------------------------------------------------------------------


@pytest.fixture()
def multi_night_person(app, db):
    """A person who has attended several finalized game nights."""
    with app.app_context():
        game = Game(name=f"MNG {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(
            first_name="Multi",
            last_name="Night",
            email=f"multi_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        other = Person(
            first_name="Other",
            last_name="Multi",
            email=f"othermulti_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add_all([game, person, other])
        _db.session.flush()

        nights = []
        players = []
        gngs = []
        # 25 nights, all in the same month/year for night_owl testing on subset
        base = datetime.date(
            2010, 6, 1
        )  # Fixed: June 2010 — 25 consecutive days stay in same month
        for i in range(25):
            gn = GameNight(date=base + datetime.timedelta(days=i), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)

            pl = Player(game_night_id=gn.id, people_id=person.id)
            op = Player(game_night_id=gn.id, people_id=other.id)
            _db.session.add_all([pl, op])
            _db.session.flush()
            players.append((pl, op))

            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(
                Result(game_night_game_id=gng.id, player_id=pl.id, position=1, score=10)
            )
            _db.session.add(Result(game_night_game_id=gng.id, player_id=op.id, position=2, score=5))

        _db.session.commit()
        last_night = nights[-1]
        yield {
            "person": person,
            "other": other,
            "game": game,
            "nights": nights,
            "gngs": gngs,
            "players": players,
            "last_night": last_night,
        }

        _db.session.rollback()
        PersonBadge.query.filter_by(person_id=person.id).delete()
        PersonBadge.query.filter_by(person_id=other.id).delete()
        _db.session.commit()
        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl_pair in players:
            for pl in pl_pair:
                _db.session.delete(pl)
        for gn in nights:
            _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()


def test_veteran_earns_at_25_nights(app, db, multi_night_person):
    from app.services.badge_services import _check_veteran

    with app.app_context():
        assert (
            _check_veteran(multi_night_person["person"].id, multi_night_person["last_night"].id)
            is True
        )


def test_veteran_does_not_earn_before_25(app, db, badge_night):
    from app.services.badge_services import _check_veteran

    with app.app_context():
        assert _check_veteran(badge_night["winner"].id, badge_night["game_night"].id) is False


def test_century_club_does_not_earn_with_25_games(app, db, multi_night_person):
    from app.services.badge_services import _check_century_club

    # 25 nights * 1 game each = 25 games — not enough for 100
    with app.app_context():
        assert (
            _check_century_club(
                multi_night_person["person"].id, multi_night_person["last_night"].id
            )
            is False
        )


def test_century_club_earns_at_100_games(app, db):
    """century_club earns when a person has played 100+ games across finalized nights."""
    from app.services.badge_services import _check_century_club

    with app.app_context():
        game = Game(name=f"CGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(
            first_name="Century",
            last_name="Player",
            email=f"century_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        other = Person(
            first_name="Oth", last_name="C", email=f"othc_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all([game, person, other])
        _db.session.flush()

        nights, players, gngs = [], [], []
        for i in range(100):
            gn = GameNight(date=datetime.date(2000, 1, 1) + datetime.timedelta(days=i), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)
            pl = Player(game_night_id=gn.id, people_id=person.id)
            op = Player(game_night_id=gn.id, people_id=other.id)
            _db.session.add_all([pl, op])
            _db.session.flush()
            players.extend([pl, op])
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=pl.id, position=1))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=op.id, position=2))
        _db.session.commit()

        assert _check_century_club(person.id, nights[-1].id) is True

        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in players:
            _db.session.delete(pl)
        for gn in nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()


def test_variety_pack_does_not_earn_with_1_unique_game(app, db, multi_night_person):
    from app.services.badge_services import _check_variety_pack

    with app.app_context():
        # multi_night_person uses same game every night, so only 1 unique game
        assert (
            _check_variety_pack(
                multi_night_person["person"].id, multi_night_person["last_night"].id
            )
            is False
        )


def test_variety_pack_earns_with_10_different_games(app, db):
    """variety_pack earns when a person has played 10+ distinct games."""
    from app.services.badge_services import _check_variety_pack

    with app.app_context():
        games = [Game(name=f"VGame{i}_{uuid.uuid4().hex[:4]}", bgg_id=None) for i in range(10)]
        person = Person(
            first_name="Var", last_name="Pack", email=f"varpack_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        other = Person(
            first_name="Oth", last_name="Var", email=f"othvar_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all(games + [person, other])
        _db.session.flush()

        nights, players, gngs = [], [], []
        for i, game in enumerate(games):
            gn = GameNight(date=datetime.date(2001, 1, 1) + datetime.timedelta(days=i), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)
            pl = Player(game_night_id=gn.id, people_id=person.id)
            op = Player(game_night_id=gn.id, people_id=other.id)
            _db.session.add_all([pl, op])
            _db.session.flush()
            players.extend([pl, op])
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=pl.id, position=1))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=op.id, position=2))
        _db.session.commit()

        assert _check_variety_pack(person.id, nights[-1].id) is True

        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in players:
            _db.session.delete(pl)
        for gn in nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(other)
        for g in games:
            _db.session.delete(g)
        _db.session.commit()


def test_night_owl_earns_with_5_in_same_month(app, db, multi_night_person):
    from app.services.badge_services import _check_night_owl

    with app.app_context():
        # All 25 nights are in same base month window — at least 5 will be same month
        first_night = multi_night_person["nights"][4]  # 5th night
        assert _check_night_owl(multi_night_person["person"].id, first_night.id) is True


def test_night_owl_does_not_earn_with_fewer_than_5(app, db, badge_night):
    from app.services.badge_services import _check_night_owl

    with app.app_context():
        assert _check_night_owl(badge_night["winner"].id, badge_night["game_night"].id) is False


def test_gracious_host_earns_with_perfect_attendance(app, db, multi_night_person):
    from app.services.badge_services import _check_gracious_host

    with app.app_context():
        assert (
            _check_gracious_host(
                multi_night_person["person"].id, multi_night_person["last_night"].id
            )
            is True
        )


def test_gracious_host_does_not_earn_when_missed_a_night(app, db, multi_night_person):
    from app.services.badge_services import _check_gracious_host

    with app.app_context():
        nights = multi_night_person["nights"]
        last_night = multi_night_person["last_night"]
        # Create a person who attended all nights except the last one (24 of 25)
        almost = Person(
            first_name="Almost",
            last_name="There",
            email=f"almost_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add(almost)
        _db.session.flush()
        players = []
        for night in nights[:-1]:  # all except last_night (index 24)
            pl = Player(game_night_id=night.id, people_id=almost.id)
            _db.session.add(pl)
            players.append(pl)
        _db.session.commit()
        assert _check_gracious_host(almost.id, last_night.id) is False
        for pl in players:
            _db.session.delete(pl)
        _db.session.delete(almost)
        _db.session.commit()


def test_collector_earns_with_10_owned_games(app, db):
    from app.models import OwnedBy
    from app.services.badge_services import _check_collector

    with app.app_context():
        person = Person(
            first_name="Col", last_name="Lect", email=f"col_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add(person)
        _db.session.flush()

        games = []
        ownerships = []
        for _ in range(10):
            g = Game(name=f"CG {uuid.uuid4().hex[:6]}", bgg_id=None)
            _db.session.add(g)
            _db.session.flush()
            games.append(g)
            ob = OwnedBy(game_id=g.id, person_id=person.id)
            _db.session.add(ob)
            ownerships.append(ob)

        _db.session.commit()
        assert _check_collector(person.id, 0) is True

        for ob in ownerships:
            _db.session.delete(ob)
        for g in games:
            _db.session.delete(g)
        _db.session.delete(person)
        _db.session.commit()


def test_founding_member_earns_for_attendees_of_first_night(app, db):
    """founding_member earns for the first 5 attendees of the earliest game night."""
    from app.services.badge_services import _check_founding_member

    with app.app_context():
        first_date = datetime.date(1901, 1, 1)
        later_date = datetime.date(1901, 1, 2)

        founders = [
            Person(
                first_name=f"F{i}",
                last_name="Founder",
                email=f"founding_{i}_{uuid.uuid4().hex[:6]}@test.invalid",
            )
            for i in range(3)
        ]
        outsider = Person(
            first_name="Out",
            last_name="Sider",
            email=f"outsider_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add_all(founders + [outsider])
        _db.session.flush()

        first_gn = GameNight(date=first_date, final=True)
        later_gn = GameNight(date=later_date, final=True)
        _db.session.add_all([first_gn, later_gn])
        _db.session.flush()

        founder_players = [Player(game_night_id=first_gn.id, people_id=f.id) for f in founders]
        outsider_player = Player(game_night_id=later_gn.id, people_id=outsider.id)
        _db.session.add_all(founder_players + [outsider_player])
        _db.session.commit()

        for f in founders:
            assert _check_founding_member(f.id, later_gn.id) is True
        assert _check_founding_member(outsider.id, later_gn.id) is False

        for p in founder_players:
            _db.session.delete(p)
        _db.session.delete(outsider_player)
        for f in founders:
            PersonBadge.query.filter_by(person_id=f.id).delete()
        PersonBadge.query.filter_by(person_id=outsider.id).delete()
        _db.session.delete(first_gn)
        _db.session.delete(later_gn)
        for f in founders:
            _db.session.delete(f)
        _db.session.delete(outsider)
        _db.session.commit()


# ---------------------------------------------------------------------------
# Group D: consecutive streaks
# ---------------------------------------------------------------------------


@pytest.fixture()
def streak_setup(app, db):
    """3 consecutive attended nights, all with a win."""
    with app.app_context():
        game = Game(name=f"Streak {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(
            first_name="Str", last_name="Eak", email=f"streak_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        other = Person(
            first_name="Oth", last_name="Stk", email=f"othstk_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all([game, person, other])
        _db.session.flush()

        nights, players, gngs = [], [], []
        for delta in [10, 5, 1]:
            gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=delta), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)

            pl = Player(game_night_id=gn.id, people_id=person.id)
            op = Player(game_night_id=gn.id, people_id=other.id)
            _db.session.add_all([pl, op])
            _db.session.flush()
            players.append((pl, op))

            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(
                Result(game_night_game_id=gng.id, player_id=pl.id, position=1, score=10)
            )
            _db.session.add(Result(game_night_game_id=gng.id, player_id=op.id, position=2, score=5))

        _db.session.commit()
        yield {
            "person": person,
            "nights": nights,
            "gngs": gngs,
            "players": players,
            "last_night": nights[-1],
            "game": game,
            "other": other,
        }

        _db.session.rollback()
        PersonBadge.query.filter_by(person_id=person.id).delete()
        _db.session.commit()
        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl_pair in players:
            for pl in pl_pair:
                _db.session.delete(pl)
        for gn in nights:
            _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()


def test_winning_streak_earns_with_3_consecutive_wins(app, db, streak_setup):
    from app.services.badge_services import _check_winning_streak

    with app.app_context():
        assert (
            _check_winning_streak(streak_setup["person"].id, streak_setup["last_night"].id) is True
        )


def test_winning_streak_does_not_earn_with_only_1_night(app, db, badge_night):
    from app.services.badge_services import _check_winning_streak

    with app.app_context():
        assert (
            _check_winning_streak(badge_night["winner"].id, badge_night["game_night"].id) is False
        )


@pytest.fixture()
def closer_setup(app, db):
    """5 consecutive nights where person wins the last game each time."""
    with app.app_context():
        game = Game(name=f"Closer {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(
            first_name="The",
            last_name="Closer",
            email=f"closer_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        other = Person(
            first_name="Oth", last_name="Cls", email=f"othcls_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all([game, person, other])
        _db.session.flush()

        nights, players, gngs = [], [], []
        for delta in [25, 20, 15, 10, 1]:
            gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=delta), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)

            pl = Player(game_night_id=gn.id, people_id=person.id)
            op = Player(game_night_id=gn.id, people_id=other.id)
            _db.session.add_all([pl, op])
            _db.session.flush()
            players.append((pl, op))

            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(
                Result(game_night_game_id=gng.id, player_id=pl.id, position=1, score=10)
            )
            _db.session.add(Result(game_night_game_id=gng.id, player_id=op.id, position=2, score=5))

        _db.session.commit()
        yield {
            "person": person,
            "nights": nights,
            "gngs": gngs,
            "players": players,
            "last_night": nights[-1],
            "game": game,
            "other": other,
        }

        _db.session.rollback()
        PersonBadge.query.filter_by(person_id=person.id).delete()
        _db.session.commit()
        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl_pair in players:
            for pl in pl_pair:
                _db.session.delete(pl)
        for gn in nights:
            _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()


def test_the_closer_earns_with_5_consecutive_last_game_wins(app, db, closer_setup):
    from app.services.badge_services import _check_the_closer

    with app.app_context():
        assert _check_the_closer(closer_setup["person"].id, closer_setup["last_night"].id) is True


def test_the_closer_does_not_earn_with_only_3_nights(app, db, streak_setup):
    from app.services.badge_services import _check_the_closer

    with app.app_context():
        assert _check_the_closer(streak_setup["person"].id, streak_setup["last_night"].id) is False


# ---------------------------------------------------------------------------
# Group E: cross-player
# ---------------------------------------------------------------------------


@pytest.fixture()
def nemesis_setup(app, db):
    """Opponent beats person in same game 5 times."""
    with app.app_context():
        game = Game(name=f"Nem {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(
            first_name="Nem", last_name="Victim", email=f"nem_v_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        bully = Person(
            first_name="Nem", last_name="Bully", email=f"nem_b_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all([game, person, bully])
        _db.session.flush()

        nights, players, gngs = [], [], []
        for i in range(5):
            gn = GameNight(
                date=datetime.date.today() - datetime.timedelta(days=10 * (i + 1)), final=True
            )
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)

            vp = Player(game_night_id=gn.id, people_id=person.id)
            bp = Player(game_night_id=gn.id, people_id=bully.id)
            _db.session.add_all([vp, bp])
            _db.session.flush()
            players.append((vp, bp))

            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(
                Result(game_night_game_id=gng.id, player_id=bp.id, position=1, score=10)
            )
            _db.session.add(Result(game_night_game_id=gng.id, player_id=vp.id, position=2, score=5))

        _db.session.commit()
        yield {
            "person": person,
            "bully": bully,
            "game": game,
            "nights": nights,
            "gngs": gngs,
            "players": players,
            "last_night": nights[-1],
        }

        _db.session.rollback()
        PersonBadge.query.filter_by(person_id=person.id).delete()
        PersonBadge.query.filter_by(person_id=bully.id).delete()
        _db.session.commit()
        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for vp, bp in players:
            _db.session.delete(vp)
            _db.session.delete(bp)
        for gn in nights:
            _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(bully)
        _db.session.delete(game)
        _db.session.commit()


def test_nemesis_earns_after_5_losses_to_same_person(app, db, nemesis_setup):
    from app.services.badge_services import _check_nemesis

    with app.app_context():
        assert _check_nemesis(nemesis_setup["person"].id, nemesis_setup["last_night"].id) is True


def test_nemesis_does_not_earn_for_bully(app, db, nemesis_setup):
    from app.services.badge_services import _check_nemesis

    with app.app_context():
        assert _check_nemesis(nemesis_setup["bully"].id, nemesis_setup["last_night"].id) is False


def test_kingslayer_earns_when_beating_top_winner(app, db, badge_night):
    from app.services.badge_services import _check_kingslayer

    with app.app_context():
        assert _check_kingslayer(badge_night["loser"].id, badge_night["game_night"].id) is False
        assert _check_kingslayer(badge_night["winner"].id, badge_night["game_night"].id) is False


def test_kingslayer_earns_when_underdog_beats_all_time_leader(app, db):
    """kingslayer earns when you beat the person with the most all-time wins tonight."""
    from app.services.badge_services import _check_kingslayer

    with app.app_context():
        game = Game(name=f"KSGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        champion = Person(
            first_name="Champ", last_name="KS", email=f"champ_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        underdog = Person(
            first_name="Under",
            last_name="Dog",
            email=f"underdog_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add_all([game, champion, underdog])
        _db.session.flush()

        # Champion wins 5 prior nights
        prior_nights, prior_players, prior_gngs = [], [], []
        for i in range(5):
            gn = GameNight(date=datetime.date(2002, 1, i + 1), final=True)
            _db.session.add(gn)
            _db.session.flush()
            prior_nights.append(gn)
            champ_pl = Player(game_night_id=gn.id, people_id=champion.id)
            und_pl = Player(game_night_id=gn.id, people_id=underdog.id)
            _db.session.add_all([champ_pl, und_pl])
            _db.session.flush()
            prior_players.extend([champ_pl, und_pl])
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            prior_gngs.append(gng)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=champ_pl.id, position=1))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=und_pl.id, position=2))

        # Tonight: underdog wins, champion loses
        tonight = GameNight(date=datetime.date(2002, 1, 10), final=True)
        _db.session.add(tonight)
        _db.session.flush()
        t_champ = Player(game_night_id=tonight.id, people_id=champion.id)
        t_under = Player(game_night_id=tonight.id, people_id=underdog.id)
        _db.session.add_all([t_champ, t_under])
        _db.session.flush()
        t_gng = GameNightGame(game_night_id=tonight.id, game_id=game.id, round=1)
        _db.session.add(t_gng)
        _db.session.flush()
        _db.session.add(Result(game_night_game_id=t_gng.id, player_id=t_under.id, position=1))
        _db.session.add(Result(game_night_game_id=t_gng.id, player_id=t_champ.id, position=2))
        _db.session.commit()

        assert _check_kingslayer(underdog.id, tonight.id) is True
        assert _check_kingslayer(champion.id, tonight.id) is False

        Result.query.filter_by(game_night_game_id=t_gng.id).delete()
        _db.session.delete(t_gng)
        _db.session.delete(t_champ)
        _db.session.delete(t_under)
        PersonBadge.query.filter_by(game_night_id=tonight.id).delete()
        _db.session.delete(tonight)
        for gng in prior_gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in prior_players:
            _db.session.delete(pl)
        for gn in prior_nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        _db.session.delete(champion)
        _db.session.delete(underdog)
        _db.session.delete(game)
        _db.session.commit()


def test_grudge_match_does_not_earn_before_10_shared_games(app, db, badge_night):
    from app.services.badge_services import _check_grudge_match

    with app.app_context():
        assert _check_grudge_match(badge_night["winner"].id, badge_night["game_night"].id) is False


def test_grudge_match_earns_after_10_shared_games_of_same_type(app, db):
    """grudge_match earns when person has played the same game vs same opponent 10+ times."""
    from app.services.badge_services import _check_grudge_match

    with app.app_context():
        game = Game(name=f"GrudgeGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(
            first_name="Grudge",
            last_name="One",
            email=f"grudge1_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        rival = Person(
            first_name="Grudge",
            last_name="Two",
            email=f"grudge2_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add_all([game, person, rival])
        _db.session.flush()

        nights, players, gngs = [], [], []
        for i in range(10):
            gn = GameNight(date=datetime.date(2003, 1, i + 1), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)
            pl = Player(game_night_id=gn.id, people_id=person.id)
            rv = Player(game_night_id=gn.id, people_id=rival.id)
            _db.session.add_all([pl, rv])
            _db.session.flush()
            players.extend([pl, rv])
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=pl.id, position=1))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=rv.id, position=2))
        _db.session.commit()

        assert _check_grudge_match(person.id, nights[-1].id) is True
        assert _check_grudge_match(rival.id, nights[-1].id) is True

        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in players:
            _db.session.delete(pl)
        for gn in nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(rival)
        _db.session.delete(game)
        _db.session.commit()


def test_most_wins_earns_for_top_winner(app, db, badge_night):
    from app.services.badge_services import _check_most_wins

    with app.app_context():
        assert _check_most_wins(badge_night["winner"].id, badge_night["game_night"].id) is True
        assert _check_most_wins(badge_night["loser"].id, badge_night["game_night"].id) is False


# ---------------------------------------------------------------------------
# Group F: social / nominations
# ---------------------------------------------------------------------------


def test_social_butterfly_does_not_earn_without_universal_play(app, db):
    """social_butterfly does not earn when person has not played with everyone."""
    from app.services.badge_services import _check_social_butterfly

    with app.app_context():
        game = Game(name=f"SBGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        p1 = Person(
            first_name="SB1", last_name="T", email=f"sb1_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        p2 = Person(
            first_name="SB2", last_name="T", email=f"sb2_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        # stranger has never played with p1
        stranger = Person(
            first_name="SBStr", last_name="T", email=f"sbstr_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all([game, p1, p2, stranger])
        _db.session.flush()

        gn = GameNight(date=datetime.date.today() - datetime.timedelta(days=5), final=True)
        _db.session.add(gn)
        _db.session.flush()

        pl1 = Player(game_night_id=gn.id, people_id=p1.id)
        pl2 = Player(game_night_id=gn.id, people_id=p2.id)
        _db.session.add_all([pl1, pl2])
        _db.session.flush()

        gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
        _db.session.add(gng)
        _db.session.flush()

        _db.session.add(Result(game_night_game_id=gng.id, player_id=pl1.id, position=1))
        _db.session.add(Result(game_night_game_id=gng.id, player_id=pl2.id, position=2))
        _db.session.commit()

        # p1 played with p2 but not stranger — should not earn
        assert _check_social_butterfly(p1.id, gn.id) is False

        Result.query.filter_by(game_night_game_id=gng.id).delete()
        _db.session.delete(gng)
        _db.session.delete(pl1)
        _db.session.delete(pl2)
        PersonBadge.query.filter_by(game_night_id=gn.id).delete()
        _db.session.delete(gn)
        _db.session.delete(p1)
        _db.session.delete(p2)
        _db.session.delete(stranger)
        _db.session.delete(game)
        _db.session.commit()


@pytest.fixture()
def oracle_setup(app, db):
    """Person nominated game X, it was played, they won — 5 times."""
    with app.app_context():
        game = Game(name=f"Oracle {uuid.uuid4().hex[:6]}", bgg_id=None)
        person = Person(
            first_name="The",
            last_name="Oracle",
            email=f"oracle_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        other = Person(
            first_name="Oth", last_name="Or", email=f"othor_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all([game, person, other])
        _db.session.flush()

        nights, players, gngs, noms = [], [], [], []
        for i in range(5):
            gn = GameNight(
                date=datetime.date.today() - datetime.timedelta(days=10 * (i + 1)), final=True
            )
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)

            pl = Player(game_night_id=gn.id, people_id=person.id)
            op = Player(game_night_id=gn.id, people_id=other.id)
            _db.session.add_all([pl, op])
            _db.session.flush()
            players.append((pl, op))

            nom = GameNominations(game_night_id=gn.id, player_id=pl.id, game_id=game.id)
            _db.session.add(nom)
            noms.append(nom)
            _db.session.flush()

            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(
                Result(game_night_game_id=gng.id, player_id=pl.id, position=1, score=10)
            )
            _db.session.add(Result(game_night_game_id=gng.id, player_id=op.id, position=2, score=5))

        _db.session.commit()
        yield {
            "person": person,
            "game": game,
            "nights": nights,
            "gngs": gngs,
            "players": players,
            "noms": noms,
            "last_night": nights[-1],
            "other": other,
        }

        _db.session.rollback()
        PersonBadge.query.filter_by(person_id=person.id).delete()
        _db.session.commit()
        for nom in noms:
            _db.session.delete(nom)
        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl, op in players:
            _db.session.delete(pl)
            _db.session.delete(op)
        for gn in nights:
            _db.session.delete(gn)
        _db.session.delete(person)
        _db.session.delete(other)
        _db.session.delete(game)
        _db.session.commit()


def test_the_oracle_earns_after_5_nominate_play_win(app, db, oracle_setup):
    from app.services.badge_services import _check_the_oracle

    with app.app_context():
        assert _check_the_oracle(oracle_setup["person"].id, oracle_setup["last_night"].id) is True


def test_the_oracle_does_not_earn_with_fewer_than_5(app, db, badge_night):
    from app.services.badge_services import _check_the_oracle

    with app.app_context():
        assert _check_the_oracle(badge_night["winner"].id, badge_night["game_night"].id) is False


# ---------------------------------------------------------------------------
# Group G: upset_special / early_bird positive-path
# ---------------------------------------------------------------------------


def test_upset_special_earns_when_beating_dominant_opponent(app, db):
    """upset_special earns when you beat an opponent who had 80%+ win rate against you (min 5 games)."""
    from app.services.badge_services import _check_upset_special

    with app.app_context():
        game = Game(name=f"UpsetGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        underdog = Person(
            first_name="Upset",
            last_name="Hero",
            email=f"upset_hero_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        dominant = Person(
            first_name="Upset",
            last_name="Dominant",
            email=f"upset_dom_{uuid.uuid4().hex[:6]}@test.invalid",
        )
        _db.session.add_all([game, underdog, dominant])
        _db.session.flush()

        # 5 prior games: dominant wins all 5
        prior_nights, prior_players, prior_gngs = [], [], []
        for i in range(5):
            gn = GameNight(date=datetime.date(2004, 1, i + 1), final=True)
            _db.session.add(gn)
            _db.session.flush()
            prior_nights.append(gn)
            und_pl = Player(game_night_id=gn.id, people_id=underdog.id)
            dom_pl = Player(game_night_id=gn.id, people_id=dominant.id)
            _db.session.add_all([und_pl, dom_pl])
            _db.session.flush()
            prior_players.extend([und_pl, dom_pl])
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            prior_gngs.append(gng)
            # Dominant wins (lower position = better)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=dom_pl.id, position=1))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=und_pl.id, position=2))

        # Tonight: underdog wins
        tonight = GameNight(date=datetime.date(2004, 1, 10), final=True)
        _db.session.add(tonight)
        _db.session.flush()
        t_und = Player(game_night_id=tonight.id, people_id=underdog.id)
        t_dom = Player(game_night_id=tonight.id, people_id=dominant.id)
        _db.session.add_all([t_und, t_dom])
        _db.session.flush()
        t_gng = GameNightGame(game_night_id=tonight.id, game_id=game.id, round=1)
        _db.session.add(t_gng)
        _db.session.flush()
        _db.session.add(Result(game_night_game_id=t_gng.id, player_id=t_und.id, position=1))
        _db.session.add(Result(game_night_game_id=t_gng.id, player_id=t_dom.id, position=2))
        _db.session.commit()

        assert _check_upset_special(underdog.id, tonight.id) is True
        assert _check_upset_special(dominant.id, tonight.id) is False

        Result.query.filter_by(game_night_game_id=t_gng.id).delete()
        _db.session.delete(t_gng)
        _db.session.delete(t_und)
        _db.session.delete(t_dom)
        PersonBadge.query.filter_by(game_night_id=tonight.id).delete()
        _db.session.delete(tonight)
        for gng in prior_gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in prior_players:
            _db.session.delete(pl)
        for gn in prior_nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        _db.session.delete(underdog)
        _db.session.delete(dominant)
        _db.session.delete(game)
        _db.session.commit()


def test_early_bird_earns_after_being_first_10_times(app, db):
    """early_bird earns when person was first to register at 10+ finalized game nights."""
    from app.services.badge_services import _check_early_bird

    with app.app_context():
        game = Game(name=f"EBGame {uuid.uuid4().hex[:6]}", bgg_id=None)
        early = Person(
            first_name="Early", last_name="Bird", email=f"early_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        late = Person(
            first_name="Late", last_name="Bird", email=f"late_{uuid.uuid4().hex[:6]}@test.invalid"
        )
        _db.session.add_all([game, early, late])
        _db.session.flush()

        nights, players, gngs = [], [], []
        for i in range(10):
            gn = GameNight(date=datetime.date(2005, 1, i + 1), final=True)
            _db.session.add(gn)
            _db.session.flush()
            nights.append(gn)
            # early registers first (lower Player.id by inserting first)
            early_pl = Player(game_night_id=gn.id, people_id=early.id)
            _db.session.add(early_pl)
            _db.session.flush()
            late_pl = Player(game_night_id=gn.id, people_id=late.id)
            _db.session.add(late_pl)
            _db.session.flush()
            players.extend([early_pl, late_pl])
            gng = GameNightGame(game_night_id=gn.id, game_id=game.id, round=1)
            _db.session.add(gng)
            _db.session.flush()
            gngs.append(gng)
            _db.session.add(Result(game_night_game_id=gng.id, player_id=early_pl.id, position=1))
            _db.session.add(Result(game_night_game_id=gng.id, player_id=late_pl.id, position=2))
        _db.session.commit()

        assert _check_early_bird(early.id, nights[-1].id) is True
        assert _check_early_bird(late.id, nights[-1].id) is False

        for gng in gngs:
            Result.query.filter_by(game_night_game_id=gng.id).delete()
            _db.session.delete(gng)
        for pl in players:
            _db.session.delete(pl)
        for gn in nights:
            PersonBadge.query.filter_by(game_night_id=gn.id).delete()
            _db.session.delete(gn)
        _db.session.delete(early)
        _db.session.delete(late)
        _db.session.delete(game)
        _db.session.commit()
