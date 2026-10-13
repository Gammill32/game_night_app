"""Badge evaluation service.

Public API:
    evaluate_badges_for_night(game_night_id) -> None
    get_person_badges(person_id) -> list[PersonBadge]
"""

import logging
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import (
    Badge,
    GameNight,
    GameNightGame,
    GameNominations,
    OwnedBy,
    Person,
    PersonBadge,
    Player,
    Result,
)
from app.services.db_utils import add_unless_duplicate

logger = logging.getLogger(__name__)


def _nights_through(game_night_id: int):
    """Finalized nights dated on or before this one: all a badge judged here may count.

    Without the date bound, re-finalizing an old night would count results from
    later nights and date the badge to the old one.
    """
    cutoff = select(GameNight.date).where(GameNight.id == game_night_id).scalar_subquery()
    return select(GameNight.id).where(GameNight.final.is_(True), GameNight.date <= cutoff)


# ---------------------------------------------------------------------------
# Checkers — each returns bool
# ---------------------------------------------------------------------------


def _check_first_blood(person_id: int, game_night_id: int) -> bool:
    return (
        db.session.query(Result)
        .join(Player, Result.player_id == Player.id)
        .filter(
            Player.people_id == person_id,
            Result.position == 1,
            Player.game_night_id.in_(_nights_through(game_night_id)),
        )
        .first()
    ) is not None


def _check_hat_trick(person_id: int, game_night_id: int) -> bool:
    wins = (
        db.session.query(func.count(Result.id))
        .join(Player, Result.player_id == Player.id)
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .filter(
            Player.people_id == person_id,
            GameNightGame.game_night_id == game_night_id,
            Result.position == 1,
        )
        .scalar()
    )
    return (wins or 0) >= 3


def _check_veteran(person_id: int, game_night_id: int) -> bool:
    count = (
        db.session.query(func.count(Player.id))
        .filter(
            Player.people_id == person_id,
            Player.game_night_id.in_(_nights_through(game_night_id)),
        )
        .scalar()
    )
    return (count or 0) >= 25


def _win_counts(game_night_id: int) -> dict[int, int]:
    """person_id -> games won, over nights through this one."""
    return dict(
        db.session.query(Player.people_id, func.count(Result.id))
        .join(Result, Player.id == Result.player_id)
        .filter(
            Result.position == 1,
            Player.game_night_id.in_(_nights_through(game_night_id)),
        )
        .group_by(Player.people_id)
        .all()
    )


def _check_kingslayer(person_id: int, game_night_id: int) -> bool:
    wins = _win_counts(game_night_id)
    if not wins:
        return False
    top = max(wins.values())
    # Everyone tied for the most wins is a king; you can't slay yourself.
    kings = {pid for pid, n in wins.items() if n == top} - {person_id}
    if not kings:
        return False

    me = db.aliased(Player)
    them = db.aliased(Player)
    my_result = db.aliased(Result)
    their_result = db.aliased(Result)
    return (
        db.session.query(my_result.id)
        .join(me, my_result.player_id == me.id)
        .join(their_result, their_result.game_night_game_id == my_result.game_night_game_id)
        .join(them, their_result.player_id == them.id)
        .filter(
            me.people_id == person_id,
            me.game_night_id == game_night_id,
            them.people_id.in_(kings),
            my_result.position < their_result.position,
        )
        .first()
    ) is not None


def _check_collector(person_id: int, game_night_id: int) -> bool:
    return db.session.query(OwnedBy).filter_by(person_id=person_id).count() >= 10


def _check_variety_pack(person_id: int, game_night_id: int) -> bool:
    count = (
        db.session.query(func.count(func.distinct(GameNightGame.game_id)))
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .filter(
            Player.people_id == person_id,
            Player.game_night_id.in_(_nights_through(game_night_id)),
        )
        .scalar()
    )
    return (count or 0) >= 10


def _check_nemesis(person_id: int, game_night_id: int) -> bool:
    person_alias = db.aliased(Player)
    opp_alias = db.aliased(Player)
    person_result = db.aliased(Result)
    opp_result = db.aliased(Result)

    row = (
        db.session.query(func.count().label("beat_count"))
        .select_from(person_result)
        .join(person_alias, person_result.player_id == person_alias.id)
        .join(GameNightGame, person_result.game_night_game_id == GameNightGame.id)
        .join(opp_result, person_result.game_night_game_id == opp_result.game_night_game_id)
        .join(opp_alias, opp_result.player_id == opp_alias.id)
        .filter(
            person_alias.people_id == person_id,
            person_alias.game_night_id.in_(_nights_through(game_night_id)),
            opp_alias.people_id != person_id,
            opp_result.position < person_result.position,
        )
        .group_by(opp_alias.people_id, GameNightGame.game_id)  # same person, same game
        .having(func.count() >= 5)
        .first()
    )
    return row is not None


def _check_redemption_arc(person_id: int, game_night_id: int) -> bool:
    won_tonight = (
        db.session.query(GameNightGame.game_id)
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .filter(
            Player.people_id == person_id,
            GameNightGame.game_night_id == game_night_id,
            Result.position == 1,
        )
        .all()
    )
    for (game_id,) in won_tonight:
        prior_losses = (
            db.session.query(func.count(Result.id))
            .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
            .join(Player, Result.player_id == Player.id)
            .filter(
                Player.people_id == person_id,
                GameNightGame.game_id == game_id,
                Player.game_night_id != game_night_id,
                Player.game_night_id.in_(_nights_through(game_night_id)),
                Result.position != 1,
            )
            .scalar()
        )
        if (prior_losses or 0) >= 3:
            return True
    return False


def _check_night_owl(person_id: int, game_night_id: int) -> bool:
    current = db.session.get(GameNight, game_night_id)
    if not current:
        return False
    year, month = current.date.year, current.date.month
    count = (
        db.session.query(func.count(Player.id))
        .join(GameNight, Player.game_night_id == GameNight.id)
        .filter(
            Player.people_id == person_id,
            GameNight.id.in_(_nights_through(game_night_id)),
            func.extract("year", GameNight.date) == year,
            func.extract("month", GameNight.date) == month,
        )
        .scalar()
    )
    return (count or 0) >= 5


def _check_gracious_host(person_id: int, game_night_id: int) -> bool:
    """Attended every night of some finished calendar year.

    Judged only once a year is over (from a night in a later year): mid-year,
    everyone who came to the year's first night has a perfect record so far.
    """
    current = db.session.get(GameNight, game_night_id)
    if not current:
        return False
    year = func.extract("year", GameNight.date)
    # Nights with at least one player, so an empty finalized night can't block everyone.
    nights_per_year = {
        y: n
        for y, n in db.session.query(year, func.count(func.distinct(GameNight.id)))
        .join(Player, Player.game_night_id == GameNight.id)
        .filter(GameNight.final.is_(True), year < current.date.year)
        .group_by(year)
    }
    attended_per_year = (
        db.session.query(year, func.count(func.distinct(GameNight.id)))
        .join(Player, Player.game_night_id == GameNight.id)
        .filter(
            Player.people_id == person_id,
            GameNight.final.is_(True),
            year < current.date.year,
        )
        .group_by(year)
        .all()
    )
    return any(n == nights_per_year.get(y) for y, n in attended_per_year)


def _check_jack_of_all_trades(person_id: int, game_night_id: int) -> bool:
    person_results = (
        db.session.query(GameNightGame.id.label("gng_id"), Result.position)
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .filter(
            Player.people_id == person_id,
            GameNightGame.game_night_id == game_night_id,
            Result.position.isnot(None),
        )
        .all()
    )
    if not person_results:
        return False
    for row in person_results:
        total = (
            db.session.query(func.count(Result.id))
            .filter(Result.game_night_game_id == row.gng_id, Result.position.isnot(None))
            .scalar()
        )
        if row.position > (total + 1) // 2:
            return False
    return True


def _check_upset_special(person_id: int, game_night_id: int) -> bool:
    tonight_gng_ids = [
        r.id for r in db.session.query(GameNightGame).filter_by(game_night_id=game_night_id).all()
    ]
    if not tonight_gng_ids:
        return False

    person_tonight = {
        r.game_night_game_id: r.position
        for r in (
            db.session.query(Result.game_night_game_id, Result.position)
            .join(Player, Result.player_id == Player.id)
            .filter(
                Player.people_id == person_id,
                Result.game_night_game_id.in_(tonight_gng_ids),
                Result.position.isnot(None),
            )
            .all()
        )
    }

    beaten_opp_ids: set = set()
    for gng_id, person_pos in person_tonight.items():
        for (opp_id,) in (
            db.session.query(Player.people_id)
            .join(Result, Player.id == Result.player_id)
            .filter(
                Result.game_night_game_id == gng_id,
                Player.people_id != person_id,
                Result.position > person_pos,
                Result.position.isnot(None),
            )
            .all()
        ):
            beaten_opp_ids.add(opp_id)

    if not beaten_opp_ids:
        return False

    person_alias = db.aliased(Player)
    opp_alias = db.aliased(Player)
    p_result = db.aliased(Result)
    o_result = db.aliased(Result)

    for opp_id in beaten_opp_ids:
        rows = (
            db.session.query(
                p_result.position.label("p_pos"),
                o_result.position.label("o_pos"),
            )
            .join(person_alias, p_result.player_id == person_alias.id)
            .join(o_result, p_result.game_night_game_id == o_result.game_night_game_id)
            .join(opp_alias, o_result.player_id == opp_alias.id)
            .filter(
                person_alias.people_id == person_id,
                person_alias.game_night_id.in_(_nights_through(game_night_id)),
                opp_alias.people_id == opp_id,
                p_result.game_night_game_id.notin_(tonight_gng_ids),
                p_result.position.isnot(None),
                o_result.position.isnot(None),
            )
            .all()
        )
        if len(rows) < 5:
            continue
        opp_wins = sum(1 for r in rows if r.o_pos < r.p_pos)
        if opp_wins / len(rows) >= 0.8:
            return True
    return False


def _check_bench_warmer(person_id: int, game_night_id: int) -> bool:
    person_results = (
        db.session.query(GameNightGame.id.label("gng_id"), Result.position)
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .filter(
            Player.people_id == person_id,
            GameNightGame.game_night_id == game_night_id,
            Result.position.isnot(None),
        )
        .all()
    )
    if not person_results:
        return False
    for row in person_results:
        max_pos = (
            db.session.query(func.max(Result.position))
            .filter(Result.game_night_game_id == row.gng_id, Result.position.isnot(None))
            .scalar()
        )
        # max_pos <= 1 means only one player had a result — not truly "last place"
        if max_pos is None or max_pos <= 1 or row.position != max_pos:
            return False
    return True


def _check_grudge_match(person_id: int, game_night_id: int) -> bool:
    person_gng_ids = [
        r.game_night_game_id
        for r in (
            db.session.query(Result.game_night_game_id)
            .join(Player, Result.player_id == Player.id)
            .filter(
                Player.people_id == person_id,
                Player.game_night_id.in_(_nights_through(game_night_id)),
            )
            .all()
        )
    ]
    if not person_gng_ids:
        return False

    result = (
        db.session.query(
            GameNightGame.game_id,
            Player.people_id.label("opponent_id"),
            func.count(GameNightGame.id).label("shared"),
        )
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .filter(
            GameNightGame.id.in_(person_gng_ids),
            Player.people_id != person_id,
        )
        .group_by(GameNightGame.game_id, Player.people_id)
        .having(func.count(GameNightGame.id) >= 10)
        .first()
    )
    return result is not None


def _check_the_closer(person_id: int, game_night_id: int) -> bool:
    attended = (
        db.session.query(GameNight.id)
        .join(Player, GameNight.id == Player.game_night_id)
        .filter(
            Player.people_id == person_id,
            GameNight.id.in_(_nights_through(game_night_id)),
        )
        .order_by(GameNight.date, GameNight.id)
        .all()
    )
    if len(attended) < 5:
        return False

    night_ids = [nid for (nid,) in attended]

    last_round_sq = (
        db.session.query(
            GameNightGame.game_night_id,
            func.max(GameNightGame.round).label("max_round"),
        )
        .filter(GameNightGame.game_night_id.in_(night_ids))
        .group_by(GameNightGame.game_night_id)
        .subquery()
    )

    closed_nights = {
        nid
        for (nid,) in (
            db.session.query(GameNightGame.game_night_id)
            .join(
                last_round_sq,
                (GameNightGame.game_night_id == last_round_sq.c.game_night_id)
                & (GameNightGame.round == last_round_sq.c.max_round),
            )
            .join(Result, GameNightGame.id == Result.game_night_game_id)
            .join(Player, Result.player_id == Player.id)
            .filter(Player.people_id == person_id, Result.position == 1)
            .distinct()
            .all()
        )
    }

    streak = 0
    for (nid,) in attended:
        if nid in closed_nights:
            streak += 1
            if streak >= 5:
                return True
        else:
            streak = 0
    return False


def _check_opening_night(person_id: int, game_night_id: int) -> bool:
    first_night = (
        db.session.query(GameNight)
        .filter(GameNight.final.is_(True))
        .order_by(GameNight.date, GameNight.id)
        .first()
    )
    if first_night is None:
        return False
    return (
        db.session.query(Player)
        .filter_by(game_night_id=first_night.id, people_id=person_id)
        .first()
        is not None
    )


def _check_winning_streak(person_id: int, game_night_id: int) -> bool:
    attended = (
        db.session.query(GameNight.id)
        .join(Player, GameNight.id == Player.game_night_id)
        .filter(
            Player.people_id == person_id,
            GameNight.id.in_(_nights_through(game_night_id)),
        )
        .order_by(GameNight.date, GameNight.id)
        .all()
    )
    if len(attended) < 3:
        return False

    win_night_ids = {
        nid
        for (nid,) in (
            db.session.query(GameNight.id)
            .join(GameNightGame, GameNight.id == GameNightGame.game_night_id)
            .join(Result, GameNightGame.id == Result.game_night_game_id)
            .join(Player, Result.player_id == Player.id)
            .filter(
                Player.people_id == person_id,
                Result.position == 1,
                GameNight.final.is_(True),
            )
            .distinct()
            .all()
        )
    }

    streak = 0
    for (nid,) in attended:
        if nid in win_night_ids:
            streak += 1
            if streak >= 3:
                return True
        else:
            streak = 0
    return False


def _check_the_diplomat(person_id: int, game_night_id: int) -> bool:
    if (
        not db.session.query(Player)
        .filter_by(game_night_id=game_night_id, people_id=person_id)
        .first()
    ):
        return False
    firsts_per_game = (
        db.session.query(func.count(Result.id).filter(Result.position == 1))
        .select_from(GameNightGame)
        .outerjoin(Result, Result.game_night_game_id == GameNightGame.id)
        .filter(GameNightGame.game_night_id == game_night_id)
        .group_by(GameNightGame.id)
        .all()
    )
    # A lone winner (or a lone result) isn't a tie.
    return bool(firsts_per_game) and all(n >= 2 for (n,) in firsts_per_game)


def _check_early_bird(person_id: int, game_night_id: int) -> bool:
    """Hosted 10 game nights.

    Was "first to join 10 nights", but join order isn't recorded: players are
    saved from a set, so it went to whoever had the lowest user id.
    """
    hosted = (
        db.session.query(func.count(GameNight.id))
        .filter(
            GameNight.host_id == person_id,
            GameNight.id.in_(_nights_through(game_night_id)),
        )
        .scalar()
    )
    return (hosted or 0) >= 10


def _games_played(person_id: int, game_night_id: int) -> set[int]:
    return {
        game_id
        for (game_id,) in db.session.query(GameNightGame.game_id)
        .join(Result, Result.game_night_game_id == GameNightGame.id)
        .join(Player, Result.player_id == Player.id)
        .filter(Player.people_id == person_id, Player.game_night_id == game_night_id)
    }


def _check_the_rematch(person_id: int, game_night_id: int) -> bool:
    current = db.session.get(GameNight, game_night_id)
    if not current:
        return False
    prev = (
        db.session.query(GameNight.id)
        .join(Player, Player.game_night_id == GameNight.id)
        .filter(
            Player.people_id == person_id,
            GameNight.final.is_(True),
            (GameNight.date < current.date)
            | ((GameNight.date == current.date) & (GameNight.id < game_night_id)),
        )
        .order_by(GameNight.date.desc(), GameNight.id.desc())
        .first()
    )
    if not prev:
        return False
    return bool(_games_played(person_id, game_night_id) & _games_played(person_id, prev.id))


def _check_century_club(person_id: int, game_night_id: int) -> bool:
    count = (
        db.session.query(func.count(Result.id))
        .join(Player, Result.player_id == Player.id)
        .filter(
            Player.people_id == person_id,
            Player.game_night_id.in_(_nights_through(game_night_id)),
        )
        .scalar()
    )
    return (count or 0) >= 100


def _check_dark_horse(person_id: int, game_night_id: int) -> bool:
    results = (
        db.session.query(
            GameNightGame.round,
            Result.position,
            GameNightGame.id.label("gng_id"),
        )
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .filter(
            Player.people_id == person_id,
            GameNightGame.game_night_id == game_night_id,
            Result.position.isnot(None),
        )
        .order_by(GameNightGame.round)
        .all()
    )
    if len(results) < 4:
        return False
    for row in results[:3]:
        max_pos = (
            db.session.query(func.max(Result.position))
            .filter(
                Result.game_night_game_id == row.gng_id,
                Result.position.isnot(None),
            )
            .scalar()
        )
        # max_pos <= 1: you were the only result (or everyone tied first), not last
        if max_pos is None or max_pos <= 1 or row.position != max_pos:
            return False
    return results[-1].position == 1


def _check_social_butterfly(person_id: int, game_night_id: int) -> bool:
    """Shared a game with every active person who has played one."""
    nights = _nights_through(game_night_id)
    everyone = {
        pid
        for (pid,) in db.session.query(Player.people_id)
        .join(Result, Result.player_id == Player.id)
        .join(Person, Person.id == Player.people_id)
        .filter(Player.game_night_id.in_(nights), Person.active.is_(True))
        .distinct()
    }
    my_games = (
        select(Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .where(Player.people_id == person_id, Player.game_night_id.in_(nights))
    )
    partners = {
        pid
        for (pid,) in db.session.query(Player.people_id)
        .join(Result, Result.player_id == Player.id)
        .filter(Result.game_night_game_id.in_(my_games))
        .distinct()
    }
    others = everyone - {person_id}
    return bool(others) and others <= partners


def _check_the_oracle(person_id: int, game_night_id: int) -> bool:
    nom_player = db.aliased(Player)
    win_player = db.aliased(Player)

    oracle_nights = (
        db.session.query(func.count(func.distinct(GameNominations.game_night_id)))
        .join(nom_player, GameNominations.player_id == nom_player.id)
        .join(
            GameNightGame,
            (GameNightGame.game_night_id == GameNominations.game_night_id)
            & (GameNightGame.game_id == GameNominations.game_id),
        )
        .join(Result, Result.game_night_game_id == GameNightGame.id)
        .join(win_player, Result.player_id == win_player.id)
        .join(GameNight, GameNight.id == GameNominations.game_night_id)
        .filter(
            nom_player.people_id == person_id,
            win_player.people_id == person_id,
            Result.position == 1,
            GameNight.id.in_(_nights_through(game_night_id)),
        )
        .scalar()
    )
    return (oracle_nights or 0) >= 5


def _check_founding_member(person_id: int, game_night_id: int) -> bool:
    """Among the first 5 people to play, by the date of the first night they
    played a game (attending without playing doesn't count).

    Everyone debuting on the same night ties, so a big first night can make
    more than five founders; row order (the old tie-break) was arbitrary.
    """
    debut = (
        db.session.query(Player.people_id, func.min(GameNight.date).label("first"))
        .join(GameNight, GameNight.id == Player.game_night_id)
        .join(Result, Result.player_id == Player.id)
        .filter(GameNight.final.is_(True))
        .group_by(Player.people_id)
        .subquery()
    )
    mine = db.session.query(debut.c.first).filter(debut.c.people_id == person_id).scalar()
    if mine is None:
        return False
    earlier = (
        db.session.query(func.count()).select_from(debut).filter(debut.c.first < mine).scalar()
    )
    return earlier < 5


def _check_most_wins(person_id: int, game_night_id: int) -> bool:
    wins = _win_counts(game_night_id)
    return bool(wins) and wins.get(person_id, 0) == max(wins.values())


# ---------------------------------------------------------------------------
# Registry — maps badge key → checker function
# ---------------------------------------------------------------------------

_BADGE_REGISTRY: dict = {
    "first_blood": _check_first_blood,
    "hat_trick": _check_hat_trick,
    "veteran": _check_veteran,
    "kingslayer": _check_kingslayer,
    "collector": _check_collector,
    "variety_pack": _check_variety_pack,
    "nemesis": _check_nemesis,
    "redemption_arc": _check_redemption_arc,
    "night_owl": _check_night_owl,
    "gracious_host": _check_gracious_host,
    "jack_of_all_trades": _check_jack_of_all_trades,
    "upset_special": _check_upset_special,
    "bench_warmer": _check_bench_warmer,
    "grudge_match": _check_grudge_match,
    "the_closer": _check_the_closer,
    "opening_night": _check_opening_night,
    "winning_streak": _check_winning_streak,
    "the_diplomat": _check_the_diplomat,
    "early_bird": _check_early_bird,
    "the_rematch": _check_the_rematch,
    "century_club": _check_century_club,
    "dark_horse": _check_dark_horse,
    "social_butterfly": _check_social_butterfly,
    "the_oracle": _check_the_oracle,
    "founding_member": _check_founding_member,
    "most_wins": _check_most_wins,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def evaluate_badges_for_night(game_night_id: int) -> None:
    """Evaluate all badges for all participants of the given finalized game night.

    Silently logs and returns on any error — must never raise to the caller.
    Relies on the uq_person_badge unique constraint to prevent duplicates;
    does NOT use an application-level pre-check (which would be a race condition).
    """
    try:
        game_night = db.session.get(GameNight, game_night_id)
        if game_night is None or not game_night.final:
            return

        participants = db.session.query(Player).filter_by(game_night_id=game_night_id).all()
        person_ids = [p.people_id for p in participants]

        badges = {b.key: b for b in db.session.query(Badge).all()}

        for badge_key, checker_fn in _BADGE_REGISTRY.items():
            badge = badges.get(badge_key)
            if badge is None:
                continue

            # Always store the triggering night so recap can show all awarded badges
            night_id_to_store = game_night_id

            for person_id in person_ids:
                try:
                    # Savepoint: a failed query aborts the Postgres transaction, which
                    # would otherwise take every later check and award down with it.
                    with db.session.begin_nested():
                        earned = checker_fn(person_id, game_night_id)
                except Exception:
                    logger.exception(
                        "Badge checker %s failed for person %s night %s",
                        badge_key,
                        person_id,
                        game_night_id,
                    )
                    continue

                if not earned:
                    continue
                try:  # already held: the constraint says so, and that's fine
                    add_unless_duplicate(
                        PersonBadge(
                            person_id=person_id, badge_id=badge.id, game_night_id=night_id_to_store
                        ),
                        "uq_person_badge",
                    )
                except Exception:  # one bad award mustn't undo the night's others
                    logger.exception("Awarding %s to person %s failed", badge_key, person_id)

        db.session.commit()

    except Exception:
        db.session.rollback()
        logger.exception("Badge evaluation failed for game night %s", game_night_id)


# Judged on today's data (games owned now, who's active now), not on a night's
# history: re-judging old nights would date them wrongly or take back awards that
# were right when earned. recheck leaves them alone; finalizing still awards them.
_JUDGED_ON_TODAY = {"collector", "social_butterfly"}


def recheck_badges(apply: bool) -> list[dict]:
    """Re-judge every finalized night, oldest first, with the current rules.

    Works out which badges each person should hold and the first night that
    earned each one, then compares with what's stored: awards that no longer
    qualify are removed, missing ones are added (dated to that first night),
    and awards that still qualify are left exactly as they are. Badges with
    no checker, and those in _JUDGED_ON_TODAY, are ignored. Unlike finalizing a night, a checker error is
    raised, so a failing check can never read as "doesn't qualify" and
    remove an award. With apply=False nothing is written.

    Returns one entry per badge with changes, in badge order:
    {"badge": name, "added": [(person name, night date)], "removed": [person name]}.
    """
    keys = set(_BADGE_REGISTRY) - _JUDGED_ON_TODAY
    badges = {b.key: b for b in db.session.query(Badge).filter(Badge.key.in_(keys)).all()}
    nights = (
        db.session.query(GameNight)
        .filter(GameNight.final.is_(True))
        .order_by(GameNight.date, GameNight.id)
        .all()
    )

    should: dict[tuple[int, int], GameNight] = {}  # (person, badge) -> first night
    for night in nights:
        person_ids = [
            pid for (pid,) in db.session.query(Player.people_id).filter_by(game_night_id=night.id)
        ]
        for key, checker in _BADGE_REGISTRY.items():
            badge = badges.get(key)
            if badge is None:
                continue
            for person_id in person_ids:
                if (person_id, badge.id) not in should and checker(person_id, night.id):
                    should[(person_id, badge.id)] = night

    held = {
        (pb.person_id, pb.badge_id): pb
        for pb in db.session.query(PersonBadge)
        .filter(PersonBadge.badge_id.in_([b.id for b in badges.values()]))
        .all()
    }
    to_add = [k for k in should if k not in held]
    to_remove = [pb for k, pb in held.items() if k not in should]

    names = {
        p.id: p.full_name
        for p in db.session.query(Person).filter(
            Person.id.in_({pid for pid, _ in to_add} | {pb.person_id for pb in to_remove})
        )
    }
    changes: dict[int, dict] = {}

    def entry(badge_id):
        return changes.setdefault(badge_id, {"added": [], "removed": []})

    for person_id, badge_id in to_add:
        entry(badge_id)["added"].append((names[person_id], should[(person_id, badge_id)].date))
    for pb in to_remove:
        entry(pb.badge_id)["removed"].append(names[pb.person_id])

    if apply:
        for person_id, badge_id in to_add:
            db.session.add(
                PersonBadge(
                    person_id=person_id,
                    badge_id=badge_id,
                    game_night_id=should[(person_id, badge_id)].id,
                )
            )
        for pb in to_remove:
            db.session.delete(pb)
        db.session.commit()

    by_id = {b.id: b for b in badges.values()}
    return [
        {
            "badge": by_id[badge_id].name,
            "added": sorted(c["added"], key=lambda a: (a[1], a[0])),
            "removed": sorted(c["removed"]),
        }
        for badge_id, c in sorted(changes.items())
    ]


def get_person_badges(person_id: int) -> list:
    """Return all earned badges for a person, newest night first."""
    return (
        db.session.query(PersonBadge)
        .filter_by(person_id=person_id)
        .options(joinedload(PersonBadge.badge), joinedload(PersonBadge.game_night))
        .outerjoin(GameNight, PersonBadge.game_night_id == GameNight.id)
        .order_by(GameNight.date.desc().nullslast(), PersonBadge.earned_at.desc())
        .all()
    )


def newest_awards(person_id: int, limit: int) -> list:
    """A person's most recent awards, newest first, with their badges loaded."""
    return (
        db.session.query(PersonBadge)
        .filter_by(person_id=person_id)
        .options(joinedload(PersonBadge.badge))
        .order_by(PersonBadge.id.desc())
        .limit(limit)
        .all()
    )


def total_badges() -> int:
    return db.session.query(func.count(Badge.id)).scalar() or 0


def earned_on(person_badge) -> date:
    """The date to show: the night that earned it, or when it was recorded."""
    if person_badge.game_night is not None:
        return person_badge.game_night.date
    return person_badge.earned_at.date()


def catalog(viewer_id: int) -> list[dict]:
    """Every badge with who holds it (earliest first) and the viewer's own award."""
    awards = (
        db.session.query(PersonBadge)
        .options(joinedload(PersonBadge.person), joinedload(PersonBadge.game_night))
        .all()
    )
    by_badge: dict[int, list] = {}
    for award in awards:
        by_badge.setdefault(award.badge_id, []).append(award)
    rows = []
    for badge in db.session.query(Badge).order_by(Badge.id).all():
        holders = sorted(by_badge.get(badge.id, []), key=earned_on)
        rows.append(
            {
                "badge": badge,
                "holders": holders,
                "mine": next((a for a in holders if a.person_id == viewer_id), None),
            }
        )
    rows.sort(key=lambda r: (r["mine"] is None, -len(r["holders"])))  # type: ignore[arg-type]
    return rows
