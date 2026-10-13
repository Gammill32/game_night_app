import logging
from collections import defaultdict
from datetime import datetime

from flask import abort
from sqlalchemy import select
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
    Person,
    PersonBadge,
    Player,
    Result,
    TrackerValue,
    Wishlist,
    db,
    tracker_team_players,
)
from app.services import food_services, night_policy, poll_services
from app.services.admin_services import get_all_people

logger = logging.getLogger(__name__)


def parse_date(date_str):
    """Helper to parse date string into a date object."""
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return None


def _person_ids(raw_ids):
    """Person ids from a form list, or None if any isn't a real person."""
    try:
        ids = {int(i) for i in raw_ids}
    except (TypeError, ValueError):
        return None
    if ids and Person.query.filter(Person.id.in_(ids)).count() != len(ids):
        return None
    return ids


BAD_PLAYERS_MESSAGE = "Pick players from the list."


def manage_attendees(game_night, attendees_ids):
    """Sync a game night's players to the given person ids.

    Returns an error message (and changes nothing) if an id isn't a person,
    or a player being removed already has results logged or is in a tracker;
    their nominations and votes go with them."""
    new_attendees = _person_ids(attendees_ids)
    if new_attendees is None:
        return BAD_PLAYERS_MESSAGE
    removing = [p for p in game_night.players if p.people_id not in new_attendees]
    with_results = [p for p in removing if p.results]
    if with_results:
        names = ", ".join(p.person.first_name for p in with_results)
        return f"{names} already {'has' if len(with_results) == 1 else 'have'} results logged for this night; remove those results before removing them."
    tracked = [p for p in removing if _in_a_tracker(p.id)]
    if tracked:
        names = ", ".join(p.person.first_name for p in tracked)
        return f"{names} {'is' if len(tracked) == 1 else 'are'} in a game tracker for this night; finish or discard that tracker before removing them."

    for player in removing:
        # Their nomination goes with them, so nobody's votes for it count any more.
        for nomination in player.nominations:
            GameVotes.query.filter_by(
                game_night_id=game_night.id, game_id=nomination.game_id
            ).delete()
        db.session.delete(player)  # ORM cascade removes their nominations and votes

    current_attendees = {p.people_id for p in game_night.players}
    for person_id in new_attendees - current_attendees:
        db.session.add(Player(game_night_id=game_night.id, people_id=person_id))
    return None


def _in_a_tracker(player_id):
    """Whether a tracker (any status) holds values or a team seat for this player."""
    return (
        TrackerValue.query.filter_by(player_id=player_id).first() is not None
        or db.session.execute(
            select(tracker_team_players.c.player_id)
            .where(tracker_team_players.c.player_id == player_id)
            .limit(1)
        ).first()
        is not None
    )


def start_game_night(
    date_str, notes, attendees_ids, food=("none", None, None), host_id=None, address=None
):
    """Create a new game night and add attendees. Returns (success, message, game_night)."""
    date = parse_date(date_str)
    if not date:
        return False, "Invalid date format. Please use YYYY-MM-DD.", None

    game_night = GameNight(date=date, notes=notes, host_id=host_id, address=clean_address(address))
    food_services.apply_food_settings(game_night, *food)
    db.session.add(game_night)
    db.session.flush()  # get game_night.id without committing

    error = manage_attendees(game_night, attendees_ids)
    if error:
        db.session.rollback()
        return False, error, None
    db.session.commit()

    return True, "Game night started.", game_night


def get_game_night_details(game_night_id):
    """Retrieve game night details and attendees."""
    game_night = db.get_or_404(GameNight, game_night_id)
    current_attendees = {p.people_id for p in game_night.players}
    people = get_all_people()
    listed = {p.id for p in people}
    # Keep deactivated attendees visible so saving doesn't silently drop them.
    people += [p.person for p in game_night.players if p.people_id not in listed]
    return game_night, people, current_attendees


def edit_game_night(
    game_night_id, date_str, notes, attendees_ids, food=None, host_id=None, address=None
):
    """Edit an existing game night. host_id (admins only) changes the host."""
    game_night = db.get_or_404(GameNight, game_night_id)

    date = parse_date(date_str)
    if not date:
        return False, "Invalid date format. Please use YYYY-MM-DD."
    attendee_ids = _person_ids(attendees_ids)
    if attendee_ids is None:
        return False, BAD_PLAYERS_MESSAGE
    if host_id and db.session.get(Person, host_id) is None:
        return False, "Pick a host from the list."
    if not night_policy.is_editable(game_night) and (
        date != game_night.date or attendee_ids != {p.people_id for p in game_night.players}
    ):
        return False, night_policy.FINAL_MESSAGE + " (Its date and players are locked.)"

    game_night.date = date
    game_night.notes = notes
    if address is not None and not game_night.final:
        game_night.address = clean_address(address)
    if game_night.availability_poll is not None:
        game_night.availability_poll.title = poll_services.availability_title(date)
    if food is not None:
        food_services.apply_food_settings(game_night, *food)
    if host_id is not None:
        game_night.host_id = host_id or None
    error = manage_attendees(game_night, attendee_ids)
    if error:
        db.session.rollback()
        return False, error

    db.session.commit()
    return True, "Game night updated successfully."


def clean_address(raw):
    """Trimmed address, or None when blank."""
    return (raw or "").strip()[:300] or None


def clear_past_addresses(today):
    """Delete addresses of nights that have passed (a day's grace, in case
    nobody finalized them). Returns how many were cleared."""
    from datetime import timedelta

    count = GameNight.query.filter(
        GameNight.address.isnot(None), GameNight.date < today - timedelta(days=1)
    ).update({GameNight.address: None}, synchronize_session=False)
    db.session.commit()
    return count


def delete_game_night(game_night_id):
    game_night = db.session.get(GameNight, game_night_id)
    if not game_night:
        return False, "Game night not found."

    if game_night.final:
        return False, "You cannot delete a finalized game night."

    from app.services import media_services, photo_services

    files = photo_services.files_for_night(game_night) + food_services.files_for_night(game_night)
    # Unlinked polls are visible site-wide, so the night's RSVP poll goes with
    # it and any other poll linked to it is closed (it keeps its answers).
    for poll in list(game_night.polls):
        if poll.availability:
            db.session.delete(poll)
        else:
            poll.closed = True
    db.session.delete(game_night)
    db.session.commit()
    media_services.delete(*files)
    return True, "Game night deleted successfully."


def manage_game_in_night(
    game_night_id, game_id, action="add", round_number=None, game_night_game_id=None
):
    """Add or remove a game from a game night."""
    game_night = db.get_or_404(GameNight, game_night_id)
    try:
        night_policy.require_editable(game_night)
    except night_policy.NightRuleError as e:
        return False, str(e)

    if action == "add":
        if not game_id or not round_number:
            return False, "Please select a game and round number."
        try:
            game_id, round_number = int(game_id), int(round_number)
        except (TypeError, ValueError):
            return False, "Please select a game and round number."
        if round_number < 1 or db.session.get(Game, game_id) is None:
            return False, "Please select a game and round number."

        game_night_game = GameNightGame(
            game_night_id=game_night_id, game_id=game_id, round=round_number
        )
        db.session.add(game_night_game)

    elif action == "remove":
        if not game_night_game_id or not str(game_night_game_id).isdigit():
            return False, "Game reference missing."

        game_night_game = GameNightGame.query.filter_by(
            id=int(game_night_game_id), game_night_id=game_night_id
        ).first()
        if not game_night_game:
            return False, "Game not found in this game night."
        db.session.delete(game_night_game)

    else:
        return False, "Unknown action."

    db.session.commit()
    return True, f"Game {'added' if action == 'add' else 'removed'} successfully."


def _optional_int(value):
    """None/blank stays None; otherwise an int, or ValueError."""
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int | str):
        raise ValueError(value)
    return int(value)


def _parse_results(game_night, scores_positions):
    """{player_id: (score, position)} from the log-results body, or ValueError
    with a message. Every player must be at this night."""
    if not isinstance(scores_positions, dict):
        raise ValueError("Send results as an object keyed by player.")
    night_player_ids = {p.id for p in game_night.players}
    parsed = {}
    for data in scores_positions.values():
        if not isinstance(data, dict):
            raise ValueError("Each result needs user_id, score and position.")
        try:
            player_id = _optional_int(data.get("user_id"))
            score = _optional_int(data.get("score"))
            position = _optional_int(data.get("position"))
        except (TypeError, ValueError):
            raise ValueError("Scores and places must be whole numbers.") from None
        if player_id is None or player_id not in night_player_ids:
            raise ValueError("Results can only be logged for this night's players.")
        parsed[player_id] = (score, position)
    return parsed


def log_results(game_night_id, game_night_game_id, scores_positions):
    """Log results for a game night game. Returns (success, message);
    a malformed body or a player from another night changes nothing."""
    GameNightGame.query.filter_by(game_night_id=game_night_id, id=game_night_game_id).first_or_404()
    game_night = db.get_or_404(GameNight, game_night_id)
    try:
        night_policy.require_editable(game_night)
        parsed = _parse_results(game_night, scores_positions)
    except ValueError as e:
        return False, str(e)

    for player_id, (score, position) in parsed.items():
        # Fetch or create a result entry for this player
        result = Result.query.filter_by(
            game_night_game_id=game_night_game_id, player_id=player_id
        ).first()
        if not result:
            result = Result(game_night_game_id=game_night_game_id, player_id=player_id)
            db.session.add(result)

        # Update score and position
        result.score = score
        result.position = position

    db.session.commit()
    return True, "Results logged successfully."


def get_log_results_data(game_night_id, game_night_game_id):
    """Retrieve data for logging game results (404 unless the game is in this night)."""
    game_night_game = GameNightGame.query.filter_by(
        id=game_night_game_id, game_night_id=game_night_id
    ).first_or_404()
    players = game_night_game.game_night.players
    existing_results = {r.player_id: r for r in game_night_game.results}
    return game_night_game, players, existing_results


_TOGGLEABLE_FIELDS = {"closed"}


def toggle_game_night_field(game_night_id, field):
    """Toggle voting open/closed. (Finalizing has its own finalize/unfinalize.)"""
    if field not in _TOGGLEABLE_FIELDS:
        return False, "Invalid field."

    game_night = db.get_or_404(GameNight, game_night_id)
    setattr(game_night, field, not getattr(game_night, field))
    if game_night.closed:
        # Closing voting closes the night's linked polls too.
        for poll in game_night.polls:
            poll.closed = True

    db.session.commit()
    return (
        True,
        f"{field.replace('_', ' ').capitalize()} has been {'enabled' if getattr(game_night, field) else 'disabled'}.",
    )


def _locked_night(game_night_id):
    """The night, row-locked so two finalize/reopen requests can't interleave."""
    return (
        GameNight.query.filter_by(id=game_night_id)
        .with_for_update()
        .populate_existing()
        .first_or_404()
    )


def finalize(game_night_id):
    """Lock the night's results and award badges. Returns (changed, message);
    finalizing a night that's already final changes nothing."""
    game_night = _locked_night(game_night_id)
    if game_night.final:
        db.session.rollback()
        return False, "This game night is already finalized."
    game_night.final = True
    game_night.address = None  # the night is over: don't keep where it was
    for poll in game_night.polls:
        poll.closed = True
    db.session.commit()

    try:
        from app.services.badge_services import evaluate_badges_for_night

        evaluate_badges_for_night(game_night_id)
    except Exception:
        logger.exception("Badge evaluation failed for game night %s", game_night_id)
    return True, "Game night finalized. Badges are awarded."


def unfinalize(game_night_id):
    """Reopen a finalized night; its badges are removed until it's finalized
    again. Returns (changed, message)."""
    game_night = _locked_night(game_night_id)
    if not game_night.final:
        db.session.rollback()
        return False, "This game night isn't finalized."
    game_night.final = False
    PersonBadge.query.filter_by(game_night_id=game_night_id).delete()
    db.session.commit()
    return True, "Game night reopened. Its badges were removed until it's finalized again."


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
    return db.get_or_404(GameNight, game_night_id)


def get_view_game_night_details(game_night_id, current_user_id):
    """Fetch all necessary data for viewing a game night using optimized SQL views."""

    # Fetch Game Night
    game_night = db.get_or_404(GameNight, game_night_id)

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
        nominated_ids = {
            n.game_id for n in GameNominations.query.filter_by(game_night_id=game_night_id)
        }
        user_votes = {v.game_id: v.rank for v in user_votes_query if v.game_id in nominated_ids}

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
        # Only games that are actually nominated (votes can't outlive a nomination,
        # but the view would list them if any did).
        .filter(GameNightNominationsVotes.total_nominations > 0)
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
        "my_nominated_game_id": user_nomination.game_id if user_nomination else None,
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
    game_night = db.get_or_404(GameNight, game_night_id)

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
            # The recap is public: first name and last initial only.
            "person_name": f"{pb.person.first_name} {pb.person.last_name[:1]}.",
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
