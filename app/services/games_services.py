from app.models import db, Game, OwnedBy, Wishlist, Player, Result, GameNight, GameNightGame, GamesIndex
from sqlalchemy import func
from app.utils import fetch_and_parse_bgg_data


def get_or_create_game(game_name, bgg_id=None):
    """Retrieve a game from the database or create it if it does not exist.
    
    If `bgg_id` is provided, fetch data from BGG and update game details.
    """
    game = Game.query.filter(func.lower(Game.name) == func.lower(game_name)).first()

    if not game:
        game_details = {"name": game_name, "description": None, "min_players": None, "max_players": None, "playtime": None, "image_url": None}

        if bgg_id:
            try:
                bgg_id = int(bgg_id)
                game_details.update(fetch_and_parse_bgg_data(bgg_id))
            except ValueError:
                return None, "Invalid BGG ID format."

        game = Game(
            name=game_details["name"],
            bgg_id=bgg_id if bgg_id else None,
            description=game_details.get("description"),
            min_players=game_details.get("min_players"),
            max_players=game_details.get("max_players"),
            playtime=game_details.get("playtime"),
            image_url=game_details.get("image_url"),
        )
        db.session.add(game)
        db.session.commit()

    return game, None


def get_filtered_games(user_id, name_filter=None, players_filter=None, playtime_filter=None):
    """Retrieve filtered games based on user preferences."""
    query = GamesIndex.query.filter(
        db.or_(GamesIndex.owner_id == user_id, GamesIndex.player_owner.is_(True))
    )

    if name_filter:
        query = query.filter(GamesIndex.game_name.ilike(f"%{name_filter}%"))
    if players_filter is not None:
        query = query.filter(GamesIndex.min_players <= players_filter, GamesIndex.max_players >= players_filter)
    if playtime_filter is not None:
        query = query.filter(GamesIndex.playtime <= playtime_filter)

    games = query.order_by(GamesIndex.game_name).all()
    return [{"game": game, "user_owns_game": game.user_owns_game} for game in games]


def add_game(user_id, game_name, bgg_id=None):
    """Add a game manually or fetch details from BoardGameGeek, assigning ownership."""
    game, error = get_or_create_game(game_name, bgg_id)
    if error:
        return False, error

    return modify_ownership(user_id, game.id, add=True)


def add_game_to_wishlist(user_id, game_name, bgg_id=None):
    """Adds a game to the user's wishlist by name and optional BGG ID.
    
    If the game does not exist, it is created first.
    """
    game, error = get_or_create_game(game_name, bgg_id)
    if error:
        return False, error

    wishlist_entry = Wishlist.query.filter_by(game_id=game.id, person_id=user_id).first()
    if wishlist_entry:
        return False, "Game is already in your wishlist."

    db.session.add(Wishlist(game_id=game.id, person_id=user_id))
    db.session.commit()
    return True, f'Game "{game.name}" added to your wishlist.'


def modify_wishlist(user_id, game_id, add=False, remove=False):
    """Adds or removes a game from the user's wishlist.
    
    - If `add=True`, the game is added to the wishlist.
    - If `remove=True`, the game is removed from the wishlist.
    """
    wishlist_entry = Wishlist.query.filter_by(game_id=game_id, person_id=user_id).first()

    if add:
        if wishlist_entry:
            return False, "Game is already in your wishlist."
        db.session.add(Wishlist(game_id=game_id, person_id=user_id))
        db.session.commit()
        return True, "Game added to your wishlist."

    if remove and wishlist_entry:
        db.session.delete(wishlist_entry)
        db.session.commit()
        return True, "Game removed from your wishlist."

    return False, "Game not found in your wishlist."


def modify_ownership(user_id, game_id, add=True):
    """Modify ownership of a game."""
    game = Game.query.get_or_404(game_id)
    ownership = OwnedBy.query.filter_by(game_id=game.id, person_id=user_id).first()

    if add:
        if not ownership:
            db.session.add(OwnedBy(game_id=game.id, person_id=user_id))
            modify_wishlist(user_id, game.id, remove=True)  # Remove from wishlist if it exists
            db.session.commit()
            return True, f'You now own "{game.name}".'
        return False, f'You already own "{game.name}".'
    
    if ownership:
        db.session.delete(ownership)
        db.session.commit()
        return True, "Game ownership removed."
    
    return False, "You do not own this game."


def get_game_details(game_id):
    """Retrieve details of a game, including leaderboard and game nights."""
    game = Game.query.get_or_404(game_id)
    leaderboard = (
        db.session.query(Player, func.count(Result.id).label("wins"))
        .join(Result)
        .join(GameNightGame)
        .filter(GameNightGame.game_id == game_id, Result.position == 1)
        .group_by(Player.id)
        .order_by(func.count(Result.id).desc())
        .limit(3)
        .all()
    )
    game_nights = GameNight.query.join(GameNightGame).filter(GameNightGame.game_id == game_id).order_by(GameNight.date.desc()).all()
    return game, leaderboard, game_nights


def get_wishlist(user_id):
    """Displays the user's wishlist."""
    return Game.query.join(Wishlist).filter(Wishlist.person_id == user_id).order_by(Game.name).all()
