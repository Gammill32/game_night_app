from app.models import db, GameNight, Player, GameNightGame, Result, Game
from datetime import datetime
from app.services.auth_services import get_all_people

def start_game_night(date_str, notes, attendees_ids):
    """Create a new game night and add attendees."""
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return False, "Invalid date format. Please use YYYY-MM-DD."
    
    game_night = GameNight(date=date, notes=notes)
    db.session.add(game_night)
    db.session.commit()
    
    for person_id in attendees_ids:
        player = Player(game_night_id=game_night.id, people_id=person_id)
        db.session.add(player)
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
    
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError:
        return False, "Invalid date format. Please use YYYY-MM-DD."
    
    game_night.date = date
    game_night.notes = notes
    db.session.commit()
    
    current_attendees = {p.people_id for p in game_night.players}
    new_attendees = set(map(int, attendees_ids))
    
    for person_id in new_attendees - current_attendees:
        db.session.add(Player(game_night_id=game_night.id, people_id=person_id))
    
    Player.query.filter(Player.game_night_id == game_night.id, Player.people_id.notin_(new_attendees)).delete()
    
    db.session.commit()
    return True, "Game night updated successfully."

def add_game_to_night(game_night_id, game_id, round_number):
    """Add a game to a game night."""
    if not game_id or not round_number:
        return False, "Please select a game and round number."
    
    game_night_game = GameNightGame(game_night_id=game_night_id, game_id=game_id, round=int(round_number))
    db.session.add(game_night_game)
    db.session.commit()
    
    return True, "Game added to game night."

def remove_game_from_night(game_night_id, game_id):
    """Remove a game from a game night."""
    game_night_game = GameNightGame.query.filter_by(game_night_id=game_night_id, game_id=game_id).first()
    
    if game_night_game:
        db.session.delete(game_night_game)
        db.session.commit()
        return True, "Game removed from game night."
    
    return False, "Game not found in this game night."

def log_results(game_night_id, game_night_game_id, scores_positions):
    """Log results for a game night game."""
    game_night_game = GameNightGame.query.get_or_404(game_night_game_id)
    
    for player_id, (score, position) in scores_positions.items():
        result = Result.query.filter_by(game_night_game_id=game_night_game_id, player_id=player_id).first()
        if not result:
            result = Result(game_night_game_id=game_night_game_id, player_id=player_id)
            db.session.add(result)
        
        result.score = int(score) if score else None
        result.position = int(position) if position else None
    
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

def toggle_results(game_night_id):
    """Toggle the finalization of game night results."""
    game_night = GameNight.query.get_or_404(game_night_id)
    game_night.final = not game_night.final
    db.session.commit()
    return True, "Results have been finalized." if game_night.final else "Results have been reopened."

def toggle_voting(game_night_id):
    """Toggle voting status for game night."""
    game_night = GameNight.query.get_or_404(game_night_id)
    game_night.closed = not game_night.closed
    db.session.commit()
    return True, "Voting has been closed." if game_night.closed else "Voting has been reopened."
