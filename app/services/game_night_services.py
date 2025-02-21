from app.models import db, GameNight, Player, GameNightGame, Result, Game, GameNightRankings, GameNominations, GameVotes, OwnedBy
from datetime import datetime
from app.services.admin_services import get_all_people
from collections import defaultdict
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import func, case, and_


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
        Player.game_night_id == game_night.id, 
        Player.people_id.notin_(new_attendees)
    ).delete()

def start_game_night(date_str, notes, attendees_ids):
    """Create a new game night and add attendees."""
    date = parse_date(date_str)
    if not date:
        return False, "Invalid date format. Please use YYYY-MM-DD."

    game_night = GameNight(date=date, notes=notes)
    db.session.add(game_night)
    db.session.commit()
    
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

def manage_game_in_night(game_night_id, game_id, action="add", round_number=None):
    """Add or remove a game from a game night."""
    if action == "add":
        if not game_id or not round_number:
            return False, "Please select a game and round number."
        
        game_night_game = GameNightGame(game_night_id=game_night_id, game_id=game_id, round=int(round_number))
        db.session.add(game_night_game)
    
    elif action == "remove":
        game_night_game = GameNightGame.query.filter_by(game_night_id=game_night_id, game_id=game_id).first()
        if not game_night_game:
            return False, "Game not found in this game night."
        db.session.delete(game_night_game)

    db.session.commit()
    return True, f"Game {'added' if action == 'add' else 'removed'} successfully."


def log_results(game_night_id, game_night_game_id, scores_positions):
    """Log results for a game night game."""
    game_night_game = GameNightGame.query.filter_by(game_night_id=game_night_id, id=game_night_game_id).first_or_404()

    for player_id, data in scores_positions.items():
        user_id = int(data["user_id"])
        score = data["score"]
        position = data["position"]

        # Fetch or create a result entry for this player
        result = Result.query.filter_by(game_night_game_id=game_night_game_id, player_id=user_id).first()
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

def toggle_game_night_field(game_night_id, field):
    """Toggle boolean fields in a game night (e.g., final results, voting)."""
    game_night = GameNight.query.get_or_404(game_night_id)
    
    if hasattr(game_night, field):
        setattr(game_night, field, not getattr(game_night, field))
        db.session.commit()
        return True, f"{field.replace('_', ' ').capitalize()} has been {'enabled' if getattr(game_night, field) else 'disabled'}."
    
    return False, "Invalid field."

def determine_top_places(game_night_id):
    """Fetch precomputed rankings for a game night from the database."""
    results = (
        db.session.query(
            GameNightRankings.rank, 
            GameNightRankings.player_id
        )
        .filter(GameNightRankings.game_night_id == game_night_id)
        .order_by(GameNightRankings.rank)
        .all()
    )

    if not results:
        return None

    places = defaultdict(list)
    for rank, player_id in results:
        places[rank].append(player_id)

    return sorted(places.items())  # Return as list of tuples (rank, [player_ids])

def get_game_night_by_id(game_night_id):
    """Retrieve a game night by ID or return 404 if not found."""
    return GameNight.query.get_or_404(game_night_id)

def get_view_game_night_details(game_night_id, current_user_id):
    """Fetch all necessary data for viewing a game night."""

    game_night = GameNight.query.get_or_404(game_night_id)

    # Fetch and sort players alphabetically
    players = sorted(
        Player.query.filter_by(game_night_id=game_night.id)
        .options(joinedload(Player.person))
        .all(),
        key=lambda p: (p.person.last_name, p.person.first_name)
    )

    # Fetch game night games with results
    game_night_games = (
        GameNightGame.query
        .filter_by(game_night_id=game_night.id)
        .options(joinedload(GameNightGame.results).joinedload(Result.player).joinedload(Player.person))
        .all()
    )

    # Sort results by position and score
    for game_night_game in game_night_games:
        game_night_game.results.sort(key=lambda r: (r.position, -(r.score or 0)))

    # Check if results are logged for any games
    results_logged = db.session.query(Result).filter(
        Result.game_night_game_id.in_([gng.id for gng in game_night.game_night_games])
    ).first() if game_night.game_night_games else None

    # Fetch the current user's player record for this game night
    current_player = Player.query.filter_by(game_night_id=game_night_id, people_id=current_user_id).first()

    # Fetch the user's game nomination
    user_nomination = None
    if current_player:
        user_nomination = GameNominations.query.filter_by(
            game_night_id=game_night_id,
            player_id=current_player.id
        ).first()

    # Fetch the user's votes
    user_votes = {}
    if current_player:
        user_votes_query = GameVotes.query.filter_by(
            game_night_id=game_night_id,
            player_id=current_player.id
        ).all()
        user_votes = {vote.game_id: vote.rank for vote in user_votes_query}

    # Query nominations with vote scores
    nominations_query = db.session.query(
        GameNominations,
        func.sum(
            case(
                (GameVotes.rank == 1, 3),
                (GameVotes.rank == 2, 2),
                (GameVotes.rank == 3, 1),
                else_=0
            )
        ).label('vote_score')
    ).outerjoin(
        GameVotes,
        and_(
            GameNominations.game_id == GameVotes.game_id,
            GameVotes.game_night_id == game_night_id
        )
    ).filter(
        GameNominations.game_night_id == game_night_id
    ).group_by(
        GameNominations.id,
        GameNominations.game_night_id,
        GameNominations.player_id,
        GameNominations.game_id
    ).all()

    # Query games that have votes but no nominations
    games_with_votes_query = db.session.query(
        GameVotes.game_id,
        func.sum(
            case(
                (GameVotes.rank == 1, 3),
                (GameVotes.rank == 2, 2),
                (GameVotes.rank == 3, 1),
                else_=0
            )
        ).label('vote_score')
    ).filter(
        GameVotes.game_night_id == game_night_id
    ).group_by(
        GameVotes.game_id
    ).all()

    # Merge nominations and games with votes, avoiding duplicates
    nominations_dict = {n.game_id: (n, score) for n, score in nominations_query}
    for game_id, vote_score in games_with_votes_query:
        if game_id not in nominations_dict:
            game = db.session.query(Game).filter_by(id=game_id).first()
            dummy_nomination = GameNominations(game_night_id=game_night_id, game=game)
            nominations_dict[game_id] = (dummy_nomination, vote_score)

    # Sort nominations by vote score (descending), then game name (alphabetically)
    nominations = sorted(
        nominations_dict.values(),
        key=lambda x: (-x[1], x[0].game.name)
    )

    # Determine top places if results are logged
    top_places = None
    if results_logged:
        raw_places = determine_top_places(game_night_id)
        top_places = [
            (place, [Player.query.get(player_id) for player_id in players if Player.query.get(player_id) is not None])
            for place, players in raw_places if players
        ][:3]

    # Get eligible games for nomination
    eligible_games = db.session.query(Game).join(
        OwnedBy, Game.id == OwnedBy.game_id
    ).filter(
        db.or_(
            OwnedBy.person_id == current_user_id,
            OwnedBy.person_id.in_([player.people_id for player in players])
        ),
        ~Game.id.in_({nomination.game_id for nomination, _ in nominations})
    ).order_by(Game.name).all()

    return {
        "game_night": game_night,
        "players": players,
        "game_night_games": game_night_games,
        "nominations": nominations,
        "eligible_games": eligible_games,
        "user_nomination": user_nomination,
        "user_votes": user_votes,
        "top_places": top_places
    }

def get_filtered_games_for_game_night(game_night_id, name_filter=None, players_filter=None, playtime_filter=None):
    """Retrieve filtered games based on ownership by game night attendees."""
    game_night = GameNight.query.get_or_404(game_night_id)
    player_ids = [player.people_id for player in game_night.players]  # Get attendees

    # Get game IDs owned by any attendees
    owned_game_ids = db.session.query(OwnedBy.game_id).filter(OwnedBy.person_id.in_(player_ids)).subquery()
    
    # Query games based on owned game IDs
    query = Game.query.filter(Game.id.in_(owned_game_ids))

    # Apply optional filters
    if name_filter:
        query = query.filter(Game.name.ilike(f"%{name_filter}%"))
    if players_filter is not None:
        query = query.filter(Game.min_players <= players_filter, Game.max_players >= players_filter)
    if playtime_filter is not None:
        query = query.filter(Game.playtime <= playtime_filter)

    return query.order_by(Game.name).all()