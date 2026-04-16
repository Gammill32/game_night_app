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
from app.services.admin_services import get_all_people

logger = logging.getLogger(__name__)


def parse_date(date_str):
    """Helper to parse date string into a date object."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def manage_attendees(game_night, attendees_ids):
    """Helper to sync attendees in a game night."""
    current_attendees = {p.people_id for p in game_night.players}
    new_attendees = set(map(int, attendees_ids))

    # Add new attendees
    for person_id in new_attendees - current_attendees:
        db.session.add(Player(game_night_id=game_night.id, people_id=person_id))

    # Remove attendees who are no longer in the list
    Player.query.filter(
        Player.game_night_id == game_night.id, Player.people_id.notin_(new_attendees)
    ).delete()


def start_game_night(date_str, notes, attendees_ids):
    """Create a new game night and add attendees."""
    date = parse_date(date_str)
    if not date:
        return False, "Invalid date format. Please use YYYY-MM-DD."

    game_night = GameNight(date=date, notes=notes)
    db.session.add(game_night)
    db.session.flush()  # get game_night.id without committing

    manage_attendees(game_night, attendees_ids)
    db.session.commit()

    return True, "Game night started successfully."


def get_game_night_details(game_night_id):
    """Retrieve game night details and attendees."""
    game_night = GameNight.query.get_or_404(game_night_id)
    people = get_all_people()
    current_attendees = {p.people_id for p in game_night.players}
    return game_night, people, current_attendees


def edit_game_night(game_night_id, date_str, notes, attendees_ids):
    """Edit an existing game night."""
    game_night = GameNight.query.get_or_404(game_night_id)

    date = parse_date(date_str)
    if not date:
        return False, "Invalid date format. Please use YYYY-MM-DD."

    game_night.date = date
    game_night.notes = notes
    manage_attendees(game_night, attendees_ids)

    db.session.commit()
    return True, "Game night updated successfully."


def delete_game_night(game_night_id):
    game_night = GameNight.query.get(game_night_id)
    if not game_night:
        return False, "Game night not found."

    if game_night.final:
        return False, "You cannot delete a finalized game night."

    db.session.delete(game_night)
    db.session.commit()
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

    closes_availability_poll = field in ("final", "closed") and getattr(game_night, field) is True
    if closes_availability_poll:
        if game_night.availability_poll and not game_night.availability_poll.closed:
            game_night.availability_poll.closed = True
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

    return {
        "game_night": game_night,
        "players": players,
        "game_night_games": game_night_games,
        "nominations": nominations,
        "eligible_games": eligible_games,
        "user_nomination": user_nomination,
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
    }


def get_filtered_games_for_game_night(
    game_night_id, name_filter=None, players_filter=None, playtime_filter=None, current_user_id=None
):
    """Retrieve filtered games based on ownership by game night attendees, including wishlist status."""
    game_night = GameNight.query.get_or_404(game_night_id)
    player_ids = [player.people_id for player in game_night.players]  # Get attendees

    # Get games owned by attendees
    owned_game_ids = (
        db.session.query(OwnedBy.game_id).filter(OwnedBy.person_id.in_(player_ids)).subquery()
    )

    query = Game.query.filter(Game.id.in_(owned_game_ids))

    # Apply filters
    if name_filter:
        query = query.filter(Game.name.ilike(f"%{name_filter}%"))
    if players_filter is not None:
        query = query.filter(Game.min_players <= players_filter, Game.max_players >= players_filter)
    if playtime_filter is not None:
        query = query.filter(Game.playtime <= playtime_filter)

    games = query.order_by(Game.name).all()

    # Get wishlist status
    wishlist_game_ids = set()
    if current_user_id:
        wishlist_game_ids = {
            w.game_id for w in Wishlist.query.filter_by(person_id=current_user_id).all()
        }

    return [{"game": game, "in_wishlist": game.id in wishlist_game_ids} for game in games]


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
