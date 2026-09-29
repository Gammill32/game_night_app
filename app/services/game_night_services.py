import logging
from collections import defaultdict
from datetime import datetime

from flask import abort
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import func

from app.models import (
    Game,
    GameNight,
    GameNightGame,
    GameNightGameResults,
    GameNightNominationsVotes,
    GameNightRankings,
    GameNominations,
    GameRatings,
    GameVotes,
    OwnedBy,
    PersonBadge,
    Player,
    Result,
    Wishlist,
    db,
)
from app.services import food_services, poll_services
from app.services.admin_services import get_all_people

logger = logging.getLogger(__name__)


def parse_date(date_str):
    """Helper to parse date string into a date object."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def manage_attendees(game_night, attendees_ids):
    """Sync a game night's players to the given person ids.

    Returns an error message (and changes nothing) if a player being removed
    already has results logged; their nominations and votes go with them."""
    new_attendees = {int(i) for i in attendees_ids}
    removing = [p for p in game_night.players if p.people_id not in new_attendees]
    with_results = [p for p in removing if p.results]
    if with_results:
        names = ", ".join(p.person.first_name for p in with_results)
        return f"{names} already {'has' if len(with_results) == 1 else 'have'} results logged for this night; remove those results before removing them."

    for player in removing:
        db.session.delete(player)  # ORM cascade removes their nominations and votes

    current_attendees = {p.people_id for p in game_night.players}
    for person_id in new_attendees - current_attendees:
        db.session.add(Player(game_night_id=game_night.id, people_id=person_id))
    return None


def start_game_night(date_str, notes, attendees_ids, food=("none", None, None)):
    """Create a new game night and add attendees. Returns (success, message, game_night)."""
    date = parse_date(date_str)
    if not date:
        return False, "Invalid date format. Please use YYYY-MM-DD.", None

    game_night = GameNight(date=date, notes=notes)
    food_services.apply_food_settings(game_night, *food)
    db.session.add(game_night)
    db.session.flush()  # get game_night.id without committing

    manage_attendees(game_night, attendees_ids)
    db.session.commit()

    return True, "Game night started.", game_night


def get_game_night_details(game_night_id):
    """Retrieve game night details and attendees."""
    game_night = GameNight.query.get_or_404(game_night_id)
    current_attendees = {p.people_id for p in game_night.players}
    people = get_all_people()
    listed = {p.id for p in people}
    # Keep deactivated attendees visible so saving doesn't silently drop them.
    people += [p.person for p in game_night.players if p.people_id not in listed]
    return game_night, people, current_attendees


def edit_game_night(game_night_id, date_str, notes, attendees_ids, food=None):
    """Edit an existing game night."""
    game_night = GameNight.query.get_or_404(game_night_id)

    date = parse_date(date_str)
    if not date:
        return False, "Invalid date format. Please use YYYY-MM-DD."

    game_night.date = date
    game_night.notes = notes
    if game_night.availability_poll is not None:
        game_night.availability_poll.title = poll_services.availability_title(date)
    if food is not None:
        food_services.apply_food_settings(game_night, *food)
    error = manage_attendees(game_night, attendees_ids)
    if error:
        db.session.rollback()
        return False, error

    db.session.commit()
    return True, "Game night updated successfully."


def delete_game_night(game_night_id):
    game_night = GameNight.query.get(game_night_id)
    if not game_night:
        return False, "Game night not found."

    if game_night.final:
        return False, "You cannot delete a finalized game night."

    from app.services import media_services, photo_services

    files = photo_services.files_for_night(game_night) + food_services.files_for_night(game_night)
    db.session.delete(game_night)
    db.session.commit()
    media_services.delete(*files)
    return True, "Game night deleted successfully."


def manage_game_in_night(
    game_night_id, game_id, action="add", round_number=None, game_night_game_id=None
):
    """Add or remove a game from a game night."""
    if action == "add":
        if not game_id or not round_number:
            return False, "Please select a game and round number."

        game_night_game = GameNightGame(
            game_night_id=game_night_id, game_id=game_id, round=int(round_number)
        )
        db.session.add(game_night_game)

    elif action == "remove":
        if not game_night_game_id:
            return False, "Game reference missing."

        game_night_game = GameNightGame.query.filter_by(
            id=game_night_game_id, game_night_id=game_night_id
        ).first()
        if not game_night_game:
            return False, "Game not found in this game night."
        db.session.delete(game_night_game)

    db.session.commit()
    return True, f"Game {'added' if action == 'add' else 'removed'} successfully."


def log_results(game_night_id, game_night_game_id, scores_positions):
    """Log results for a game night game."""
    GameNightGame.query.filter_by(game_night_id=game_night_id, id=game_night_game_id).first_or_404()

    for player_id, data in scores_positions.items():
        user_id = int(data["user_id"])
        score = data["score"]
        position = data["position"]

        # Fetch or create a result entry for this player
        result = Result.query.filter_by(
            game_night_game_id=game_night_game_id, player_id=user_id
        ).first()
        if not result:
            result = Result(game_night_game_id=game_night_game_id, player_id=user_id)
            db.session.add(result)

        # Update score and position
        result.score = score
        result.position = position

    db.session.commit()
    return True, "Results logged successfully."


def get_all_games():
    """Retrieve all available games."""
    return Game.query.order_by(Game.name).all()


def get_log_results_data(game_night_game_id):
    """Retrieve data for logging game results."""
    game_night_game = GameNightGame.query.get_or_404(game_night_game_id)
    players = game_night_game.game_night.players
    existing_results = {r.player_id: r for r in game_night_game.results}
    return game_night_game, players, existing_results


_TOGGLEABLE_FIELDS = {"final", "closed"}


def toggle_game_night_field(game_night_id, field):
    """Toggle boolean fields in a game night (e.g., final results, voting)."""
    if field not in _TOGGLEABLE_FIELDS:
        return False, "Invalid field."

    game_night = GameNight.query.get_or_404(game_night_id)
    setattr(game_night, field, not getattr(game_night, field))

    if field == "final" and getattr(game_night, field) is False:
        # Clear night-triggered badges so re-finalization starts clean
        PersonBadge.query.filter_by(game_night_id=game_night_id).delete()

    db.session.commit()

    # Closing voting or finalizing closes the night's linked polls too.
    if field in ("final", "closed") and getattr(game_night, field) is True:
        open_polls = [p for p in game_night.polls if not p.closed]
        for poll in open_polls:
            poll.closed = True
        if open_polls:
            db.session.commit()

    if field == "final" and getattr(game_night, field) is True:
        try:
            from app.services.badge_services import evaluate_badges_for_night

            evaluate_badges_for_night(game_night_id)
        except Exception:
            logger.exception("Badge evaluation failed for game night %s", game_night_id)

    return (
        True,
        f"{field.replace('_', ' ').capitalize()} has been {'enabled' if getattr(game_night, field) else 'disabled'}.",
    )


def determine_top_places(game_night_id):
    """Fetch precomputed rankings for a game night from the database."""
    results = (
        db.session.query(GameNightRankings.rank, GameNightRankings.player_id)
        .filter(GameNightRankings.game_night_id == game_night_id)
        .order_by(GameNightRankings.rank)
        .all()
    )

    if not results:
        return []

    places = defaultdict(list)
    for rank, player_id in results:
        places[rank].append(player_id)

    return sorted(places.items())  # Return as list of tuples (rank, [player_ids])


def get_game_night_by_id(game_night_id):
    """Retrieve a game night by ID or return 404 if not found."""
    return GameNight.query.get_or_404(game_night_id)


def get_view_game_night_details(game_night_id, current_user_id):
    """Fetch all necessary data for viewing a game night using optimized SQL views."""

    # Fetch Game Night
    game_night = GameNight.query.get_or_404(game_night_id)

    # Fetch and sort players alphabetically
    players = sorted(
        Player.query.filter_by(game_night_id=game_night.id)
        .options(joinedload(Player.person))
        .all(),
        key=lambda p: (p.person.last_name, p.person.first_name),
    )

    # Fetch Game Results using SQL View
    game_night_games = GameNightGameResults.query.filter_by(game_night_id=game_night_id).all()

    # Check if results are logged for any games
    results_logged = bool(game_night_games)

    # Fetch the current user's player record for this game night
    current_player = Player.query.filter_by(
        game_night_id=game_night_id, people_id=current_user_id
    ).first()

    # Fetch the user's game nomination
    user_nomination = None
    if current_player:
        user_nomination = GameNominations.query.filter_by(
            game_night_id=game_night_id, player_id=current_player.id
        ).first()

    # Fetch the user's votes
    user_votes = {}
    if current_player:
        user_votes_query = GameVotes.query.filter_by(
            game_night_id=game_night_id, player_id=current_player.id
        ).all()
        user_votes = {vote.game_id: vote.rank for vote in user_votes_query}

    # Fetch nominations and vote scores using the SQL View
    nominations = [
        {
            "game_id": nomination.game_id,
            "game_name": nomination.game_name,
            "image_url": nomination.image_url,  # ✅ Added image_url
            "total_nominations": nomination.total_nominations,
            "vote_score": nomination.vote_score,
            "user_vote": user_votes.get(nomination.game_id, None),  # ✅ Added user_vote
        }
        for nomination in GameNightNominationsVotes.query.filter_by(game_night_id=game_night_id)
        .order_by(
            GameNightNominationsVotes.vote_score.desc(),
            GameNightNominationsVotes.total_nominations.desc(),
            GameNightNominationsVotes.game_name,
        )
        .all()
    ]

    nominators = {
        n.game_id: n.player.person.first_name
        for n in GameNominations.query.filter_by(game_night_id=game_night_id)
    }
    max_score = max((n["vote_score"] or 0 for n in nominations), default=0)
    for nomination in nominations:
        nomination["nominated_by"] = nominators.get(nomination["game_id"])
        nomination["vote_pct"] = (
            round((nomination["vote_score"] or 0) * 100 / max_score) if max_score else 0
        )

    # Get eligible games for nomination (exclude already nominated games)
    nominated_game_ids = {n["game_id"] for n in nominations}
    eligible_games = (
        db.session.query(Game)
        .join(OwnedBy, Game.id == OwnedBy.game_id)
        .filter(
            db.or_(
                OwnedBy.person_id == current_user_id,
                OwnedBy.person_id.in_([player.people_id for player in players]),
            ),
            ~Game.id.in_(nominated_game_ids),
        )
        .order_by(Game.name)
        .all()
    )

    # Get the games on the user's wishlist
    wishlist_game_ids = {
        w.game_id for w in Wishlist.query.filter_by(person_id=current_user_id).all()
    }

    owned_game_ids = {ob.game_id for ob in OwnedBy.query.filter_by(person_id=current_user_id).all()}

    user_ratings_query = GameRatings.query.filter_by(person_id=current_user_id).all()
    user_ratings_by_game_id = {rating.game_id: rating.ranking for rating in user_ratings_query}

    # Get player IDs in the game night
    player_people_ids = [player.people_id for player in players]

    # Fetch average ratings for nominated games, only by players attending
    avg_ratings_query = (
        db.session.query(GameRatings.game_id, func.avg(GameRatings.ranking).label("avg_rating"))
        .filter(
            GameRatings.person_id.in_(player_people_ids),
            GameRatings.game_id.in_(nominated_game_ids),
        )
        .group_by(GameRatings.game_id)
        .all()
    )

    avg_ratings_by_game_id = {
        game_id: round(avg_rating, 1) for game_id, avg_rating in avg_ratings_query
    }

    # Add avg_rating to each nomination
    for nomination in nominations:
        nomination["avg_rating"] = avg_ratings_by_game_id.get(nomination["game_id"])

    rsvps = poll_services.rsvps_for_night(game_night)

    return {
        "game_night": game_night,
        "players": players,
        "game_night_games": game_night_games,
        "nominations": nominations,
        "eligible_games": eligible_games,
        "user_nomination": user_nomination,
        "current_player_id": current_player.id if current_player else None,
        "user_votes": user_votes,
        "top_places": None
        if not results_logged
        else [
            (rank, player_ids)
            for rank, player_ids in determine_top_places(game_night_id)
            if rank in {1, 2, 3}
        ],
        "wishlist_game_ids": wishlist_game_ids,
        "owned_game_ids": owned_game_ids,
        "user_ratings_by_game_id": user_ratings_by_game_id,
        "availability_poll": game_night.availability_poll,
        "night_badges": night_badges(game_night_id) if game_night.final else [],
        "rsvps": rsvps,
        "rsvp_in_count": sum(1 for p in players if rsvps.get(p.people_id) == "Can Make It"),
    }


def night_badges(game_night_id):
    """Badges awarded when this night was finalized, grouped by person."""
    awards = (
        PersonBadge.query.filter_by(game_night_id=game_night_id)
        .options(joinedload(PersonBadge.person), joinedload(PersonBadge.badge))
        .all()
    )
    return sorted(awards, key=lambda a: (a.person.first_name.lower(), a.badge.name))


def get_recap_details(game_night_id):
    """Fetch data for the public game night recap page."""
    game_night = GameNight.query.get_or_404(game_night_id)

    if not game_night.final:
        abort(404)

    players = sorted(
        Player.query.filter_by(game_night_id=game_night.id)
        .options(joinedload(Player.person))
        .all(),
        key=lambda p: (p.person.last_name, p.person.first_name),
    )

    game_night_games = GameNightGameResults.query.filter_by(game_night_id=game_night_id).all()

    top_places = None
    if game_night_games:
        top_places = [
            (rank, player_ids)
            for rank, player_ids in determine_top_places(game_night_id)
            if rank in {1, 2, 3}
        ]

    raw_badges = (
        PersonBadge.query.filter_by(game_night_id=game_night_id)
        .options(
            joinedload(PersonBadge.person),
            joinedload(PersonBadge.badge),
        )
        .all()
    )
    badges_earned = [
        {
            "person_name": f"{pb.person.first_name} {pb.person.last_name}",
            "badge_name": pb.badge.name,
            "badge_icon": pb.badge.icon,
            "badge_rule": pb.badge.description,
        }
        for pb in raw_badges
    ]

    return {
        "game_night": game_night,
        "players": players,
        "game_night_games": game_night_games,
        "top_places": top_places,
        "badges_earned": badges_earned,
    }
