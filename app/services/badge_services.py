"""Badge evaluation service.

Public API:
    evaluate_badges_for_night(game_night_id) -> None
    get_person_badges(person_id) -> list[PersonBadge]
"""

import logging

from sqlalchemy import func
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

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Badge definitions — single source of truth for key → uses_night_id mapping
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Checker stubs — each returns bool
# ---------------------------------------------------------------------------


def _check_first_blood(person_id: int, game_night_id: int) -> bool:
    return (
        db.session.query(Result)
        .join(Player, Result.player_id == Player.id)
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .join(GameNight, GameNightGame.game_night_id == GameNight.id)
        .filter(
            Player.people_id == person_id,
            Result.position == 1,
            GameNight.final.is_(True),
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
        .join(GameNight, Player.game_night_id == GameNight.id)
        .filter(Player.people_id == person_id, GameNight.final.is_(True))
        .scalar()
    )
    return (count or 0) >= 25


def _check_kingslayer(person_id: int, game_night_id: int) -> bool:
    top = (
        db.session.query(Player.people_id, func.count(Result.id))
        .join(Result, Player.id == Result.player_id)
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .join(GameNight, GameNightGame.game_night_id == GameNight.id)
        .filter(Result.position == 1, GameNight.final.is_(True))
        .group_by(Player.people_id)
        .order_by(func.count(Result.id).desc())
        .first()
    )
    if not top or top.people_id == person_id:
        return False

    top_winner_id = top.people_id
    top_results = {
        r.game_night_game_id: r.position
        for r in (
            db.session.query(Result.game_night_game_id, Result.position)
            .join(Player, Result.player_id == Player.id)
            .filter(Player.people_id == top_winner_id, Result.position.isnot(None))
            .all()
        )
    }
    person_tonight = (
        db.session.query(Result.game_night_game_id, Result.position)
        .join(Player, Result.player_id == Player.id)
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .filter(
            Player.people_id == person_id,
            GameNightGame.game_night_id == game_night_id,
            Result.position.isnot(None),
        )
        .all()
    )
    for gng_id, pos in person_tonight:
        if gng_id in top_results and pos < top_results[gng_id]:
            return True
    return False


def _check_collector(person_id: int, game_night_id: int) -> bool:
    return db.session.query(OwnedBy).filter_by(person_id=person_id).count() >= 10


def _check_variety_pack(person_id: int, game_night_id: int) -> bool:
    count = (
        db.session.query(func.count(func.distinct(GameNightGame.game_id)))
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .join(GameNight, GameNightGame.game_night_id == GameNight.id)
        .filter(Player.people_id == person_id, GameNight.final.is_(True))
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
        .join(opp_result, person_result.game_night_game_id == opp_result.game_night_game_id)
        .join(opp_alias, opp_result.player_id == opp_alias.id)
        .filter(
            person_alias.people_id == person_id,
            opp_alias.people_id != person_id,
            opp_result.position < person_result.position,
            person_result.position.isnot(None),
            opp_result.position.isnot(None),
        )
        .group_by(opp_alias.people_id)
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
            .join(GameNight, GameNightGame.game_night_id == GameNight.id)
            .filter(
                Player.people_id == person_id,
                GameNightGame.game_id == game_id,
                GameNightGame.game_night_id != game_night_id,
                Result.position != 1,
                GameNight.final.is_(True),
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
            GameNight.final.is_(True),
            func.extract("year", GameNight.date) == year,
            func.extract("month", GameNight.date) == month,
        )
        .scalar()
    )
    return (count or 0) >= 5


def _check_gracious_host(person_id: int, game_night_id: int) -> bool:
    current = db.session.get(GameNight, game_night_id)
    if not current:
        return False
    year = current.date.year
    # Count only finalized nights that had at least one player (active nights).
    # This avoids phantom finalized nights with no participants skewing the
    # denominator and causing false negatives in perfect-attendance checks.
    active_nights_in_year = (
        db.session.query(func.count(func.distinct(GameNight.id)))
        .join(Player, Player.game_night_id == GameNight.id)
        .filter(GameNight.final.is_(True), func.extract("year", GameNight.date) == year)
        .scalar()
    )
    if not active_nights_in_year:
        return False
    attended_in_year = (
        db.session.query(func.count(func.distinct(GameNight.id)))
        .join(Player, Player.game_night_id == GameNight.id)
        .filter(
            Player.people_id == person_id,
            GameNight.final.is_(True),
            func.extract("year", GameNight.date) == year,
        )
        .scalar()
    )
    return attended_in_year == active_nights_in_year


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
            .filter(Player.people_id == person_id)
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
        .filter(Player.people_id == person_id, GameNight.final.is_(True))
        .order_by(GameNight.date)
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
        .filter(Player.people_id == person_id, GameNight.final.is_(True))
        .order_by(GameNight.date)
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
    games = db.session.query(GameNightGame).filter_by(game_night_id=game_night_id).all()
    if not games:
        return False
    for gng in games:
        # Must have at least one result recorded — a game with no results doesn't qualify
        has_results = (
            db.session.query(Result)
            .filter(Result.game_night_game_id == gng.id, Result.position.isnot(None))
            .first()
        )
        if not has_results:
            return False
        non_first = (
            db.session.query(Result)
            .filter(
                Result.game_night_game_id == gng.id,
                Result.position != 1,
                Result.position.isnot(None),
            )
            .first()
        )
        if non_first:
            return False
    return True


def _check_early_bird(person_id: int, game_night_id: int) -> bool:
    # First registered player per finalized night (use Player.id as proxy for insertion order)
    first_player_per_night = (
        db.session.query(
            Player.game_night_id,
            func.min(Player.id).label("first_player_id"),
        )
        .join(GameNight, Player.game_night_id == GameNight.id)
        .filter(GameNight.final.is_(True))
        .group_by(Player.game_night_id)
        .subquery()
    )
    first_count = (
        db.session.query(func.count())
        .select_from(Player)
        .join(first_player_per_night, Player.id == first_player_per_night.c.first_player_id)
        .filter(Player.people_id == person_id)
        .scalar()
    )
    return (first_count or 0) >= 10


def _check_the_rematch(person_id: int, game_night_id: int) -> bool:
    prev_player = (
        db.session.query(Player)
        .join(GameNight, Player.game_night_id == GameNight.id)
        .filter(
            Player.people_id == person_id,
            GameNight.id != game_night_id,
            GameNight.final.is_(True),
        )
        .order_by(GameNight.date.desc())
        .first()
    )
    if not prev_player:
        return False

    current_game_ids = {
        r.game_id
        for r in db.session.query(GameNightGame).filter_by(game_night_id=game_night_id).all()
    }
    prev_game_ids = {
        r.game_id
        for r in db.session.query(GameNightGame)
        .filter_by(game_night_id=prev_player.game_night_id)
        .all()
    }
    return bool(current_game_ids & prev_game_ids)


def _check_century_club(person_id: int, game_night_id: int) -> bool:
    count = (
        db.session.query(func.count(Result.id))
        .join(Player, Result.player_id == Player.id)
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .join(GameNight, GameNightGame.game_night_id == GameNight.id)
        .filter(Player.people_id == person_id, GameNight.final.is_(True))
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
        if row.position != max_pos:
            return False
    return results[-1].position == 1


def _check_social_butterfly(person_id: int, game_night_id: int) -> bool:
    all_people_count = db.session.query(Person).count()
    distinct_partners = (
        db.session.query(func.count(func.distinct(Player.people_id)))
        .join(Result, Player.id == Result.player_id)
        .filter(
            Player.people_id != person_id,
            Result.game_night_game_id.in_(
                db.session.query(Result.game_night_game_id)
                .join(Player, Result.player_id == Player.id)
                .filter(Player.people_id == person_id)
            ),
        )
        .scalar()
    )
    return (distinct_partners or 0) >= all_people_count - 1


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
            GameNight.final.is_(True),
        )
        .scalar()
    )
    return (oracle_nights or 0) >= 5


def _check_founding_member(person_id: int, game_night_id: int) -> bool:
    first_night = (
        db.session.query(GameNight)
        .filter(GameNight.final.is_(True))
        .order_by(GameNight.date, GameNight.id)
        .first()
    )
    if first_night is None:
        return False
    first_five = (
        db.session.query(Player.people_id)
        .filter_by(game_night_id=first_night.id)
        .order_by(Player.id)
        .limit(5)
        .all()
    )
    return any(pid == person_id for (pid,) in first_five)


def _check_most_wins(person_id: int, game_night_id: int) -> bool:
    rows = (
        db.session.query(Player.people_id, func.count(Result.id).label("wins"))
        .join(Result, Player.id == Result.player_id)
        .join(GameNightGame, Result.game_night_game_id == GameNightGame.id)
        .join(GameNight, GameNightGame.game_night_id == GameNight.id)
        .filter(Result.position == 1, GameNight.final.is_(True))
        .group_by(Player.people_id)
        .order_by(func.count(Result.id).desc())
        .all()
    )
    if not rows:
        return False
    max_wins = rows[0].wins
    if max_wins == 0:
        return False
    person_wins = next((r.wins for r in rows if r.people_id == person_id), 0)
    return person_wins == max_wins


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
    from sqlalchemy.exc import IntegrityError

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
                    earned = checker_fn(person_id, game_night_id)
                except Exception:
                    logger.exception(
                        "Badge checker %s failed for person %s night %s",
                        badge_key,
                        person_id,
                        game_night_id,
                    )
                    continue

                if earned:
                    try:
                        with db.session.begin_nested():
                            db.session.add(
                                PersonBadge(
                                    person_id=person_id,
                                    badge_id=badge.id,
                                    game_night_id=night_id_to_store,
                                )
                            )
                    except IntegrityError:
                        # Already earned — unique constraint fired, skip silently
                        continue

        db.session.commit()

    except Exception:
        db.session.rollback()
        logger.exception("Badge evaluation failed for game night %s", game_night_id)


def get_person_badges(person_id: int) -> list:
    """Return all earned badges for a person, newest first."""
    return (
        db.session.query(PersonBadge)
        .filter_by(person_id=person_id)
        .options(joinedload(PersonBadge.badge))
        .order_by(PersonBadge.earned_at.desc())
        .all()
    )
