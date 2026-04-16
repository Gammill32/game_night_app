import datetime as dt
from datetime import datetime

from sqlalchemy import case, distinct, func

from app.models import (
    Game,
    GameNight,
    GameNightGame,
    GameNominations,
    GameRatings,
    GamesIndex,
    OwnedBy,
    Person,
    Player,
    Result,
    Wishlist,
    WishlistVote,
    db,
)
from app.services.bgg_service import BGGService


def get_or_create_game(game_name, bgg_id=None):
    """Retrieve a game from the database by name or BGG ID, or create it if not found."""

    bgg_details = {}

    if bgg_id:
        try:
            bgg_id = int(bgg_id)
        except ValueError:
            return None, "Invalid BGG ID format."

        # Check if game already exists by BGG ID first
        existing_by_bgg = Game.query.filter_by(bgg_id=bgg_id).first()
        if existing_by_bgg:
            # If the existing record is missing data, update it now
            if not existing_by_bgg.name or not existing_by_bgg.description:
                bgg_details = BGGService.fetch_details(bgg_id)
                if bgg_details:
                    val = bgg_details.get("name")
                    existing_by_bgg.name = val if val is not None else existing_by_bgg.name
                    val = bgg_details.get("description")
                    existing_by_bgg.description = (
                        val if val is not None else existing_by_bgg.description
                    )
                    val = bgg_details.get("min_players")
                    existing_by_bgg.min_players = (
                        val if val is not None else existing_by_bgg.min_players
                    )
                    val = bgg_details.get("max_players")
                    existing_by_bgg.max_players = (
                        val if val is not None else existing_by_bgg.max_players
                    )
                    val = bgg_details.get("playtime")
                    existing_by_bgg.playtime = val if val is not None else existing_by_bgg.playtime
                    val = bgg_details.get("image_url")
                    existing_by_bgg.image_url = (
                        val if val is not None else existing_by_bgg.image_url
                    )
                    db.session.commit()
            return existing_by_bgg, None

        bgg_details = BGGService.fetch_details(bgg_id)

    # Use BGG name if no name was provided
    effective_name = game_name or bgg_details.get("name", "")
    if not effective_name:
        return None, "A game name is required."

    # Check by name (case insensitive)
    game = Game.query.filter(func.lower(Game.name) == func.lower(effective_name)).first()

    if not game:
        game = Game(
            name=effective_name,
            bgg_id=bgg_id if bgg_id else None,
            description=bgg_details.get("description"),
            min_players=bgg_details.get("min_players"),
            max_players=bgg_details.get("max_players"),
            playtime=bgg_details.get("playtime"),
            image_url=bgg_details.get("image_url"),
        )
        db.session.add(game)
        db.session.commit()

    return game, None


def get_filtered_games(
    user_id,
    name_filter=None,
    players_filter=None,
    playtime_filter=None,
    min_rating_filter=None,
    scope="all",
):
    user = Person.query.get(user_id)

    # Base query
    query = GamesIndex.query

    # If not admin/owner, limit scope to games owned by the user or a site owner
    if not user.is_admin_or_owner:
        query = query.filter(
            db.or_(
                GamesIndex.owner_ids.contains([user_id]),
                GamesIndex.player_owner.is_(True),
            )
        )

    if scope == "mine":
        query = query.filter(GamesIndex.owner_ids.contains([user_id]))
    elif scope == "group":
        query = query.filter(db.func.cardinality(GamesIndex.owner_ids) > 0)

    # Apply filters
    if name_filter:
        query = query.filter(GamesIndex.game_name.ilike(f"%{name_filter}%"))
    if players_filter is not None:
        query = query.filter(
            GamesIndex.min_players <= players_filter, GamesIndex.max_players >= players_filter
        )
    if playtime_filter is not None:
        query = query.filter(GamesIndex.playtime <= playtime_filter)

    games = query.order_by(GamesIndex.game_name).all()

    # Build lookup for current user's ownership and wishlist
    owned_game_ids = {ob.game_id for ob in OwnedBy.query.filter_by(person_id=user_id).all()}

    wishlist_game_ids = {w.game_id for w in Wishlist.query.filter_by(person_id=user_id).all()}

    ratings_by_game_id = {
        r.game_id: r.ranking for r in GameRatings.query.filter_by(person_id=user_id).all()
    }

    # Build the list
    filtered_games = []
    for game in games:
        user_rating = ratings_by_game_id.get(game.game_id)

        # Apply the rating filter (if set)
        if min_rating_filter is not None:
            if user_rating is None or user_rating < min_rating_filter:
                continue

        filtered_games.append(
            {
                "game": game,
                "user_owns_game": game.game_id in owned_game_ids,
                "in_wishlist": game.game_id in wishlist_game_ids,
                "user_rating": user_rating,
            }
        )

    return filtered_games


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


def modify_ownership(person_id, game_id, add=True, *, actor_is_self=True):
    """Modify ownership of a game for the given person.

    `actor_is_self=False` indicates an admin acting on someone else's behalf,
    which only changes message wording.
    """
    game = Game.query.get_or_404(game_id)
    ownership = OwnedBy.query.filter_by(game_id=game.id, person_id=person_id).first()
    subject = "You" if actor_is_self else "Owner"

    if add:
        if not ownership:
            db.session.add(OwnedBy(game_id=game.id, person_id=person_id))
            modify_wishlist(person_id, game.id, remove=True)
            db.session.commit()
            return True, f'{subject} now own "{game.name}".'
        return False, f'{subject} already own "{game.name}".'

    if ownership:
        db.session.delete(ownership)
        db.session.commit()
        return True, "Ownership removed."

    return False, f"{subject} do not own this game."


def get_game_details(game_id, user_id):
    """Retrieve details of a game, including leaderboard, game nights, and user's rating."""
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

    game_nights = (
        GameNight.query.join(GameNightGame)
        .filter(GameNightGame.game_id == game_id)
        .order_by(GameNight.date.desc())
        .all()
    )

    user_rating_obj = GameRatings.query.filter_by(game_id=game_id, person_id=user_id).first()
    user_rating = user_rating_obj.ranking if user_rating_obj else None

    return game, leaderboard, game_nights, user_rating


def get_wishlist(user_id):
    """Displays the user's wishlist."""
    return Game.query.join(Wishlist).filter(Wishlist.person_id == user_id).order_by(Game.name).all()


def get_play_stats():
    """Returns play counts and last-played dates per game, counting only finalized nights."""
    rows = (
        db.session.query(
            GameNightGame.game_id,
            func.count(GameNightGame.id).label("play_count"),
            func.max(GameNight.date).label("last_played"),
        )
        .join(GameNight, GameNightGame.game_night_id == GameNight.id)
        .filter(GameNight.final.is_(True))
        .group_by(GameNightGame.game_id)
        .all()
    )
    return {
        row.game_id: {"play_count": row.play_count, "last_played": row.last_played} for row in rows
    }


def get_recently_played_games(days=30):
    """Returns games played within the last N days (final nights only), with play stats."""
    cutoff = dt.date.today() - dt.timedelta(days=days)
    rows = (
        db.session.query(
            Game,
            func.count(GameNightGame.id).label("play_count"),
            func.max(GameNight.date).label("last_played"),
        )
        .join(GameNightGame, Game.id == GameNightGame.game_id)
        .join(GameNight, GameNightGame.game_night_id == GameNight.id)
        .filter(GameNight.final.is_(True), GameNight.date >= cutoff)
        .group_by(Game.id)
        .order_by(func.max(GameNight.date).desc())
        .all()
    )
    result = []
    for game, play_count, last_played in rows:
        game.play_count = play_count
        game.last_played = last_played
        result.append(game)
    return result


def get_bridesmaid_games():
    """Returns games nominated but never played, annotated with nomination_count."""
    played_ids = db.session.query(distinct(GameNightGame.game_id)).scalar_subquery()
    rows = (
        db.session.query(Game, func.count(GameNominations.id).label("nomination_count"))
        .join(GameNominations, Game.id == GameNominations.game_id)
        .filter(~Game.id.in_(played_ids))
        .group_by(Game.id)
        .order_by(func.count(GameNominations.id).desc())
        .all()
    )
    result = []
    for game, count in rows:
        game.nomination_count = count
        result.append(game)
    return result


def get_group_wishlist(user_id):
    """Returns all wishlisted/voted games with total want count, sorted descending."""
    wishlist_counts = (
        db.session.query(Wishlist.game_id, func.count(Wishlist.id).label("wl_count"))
        .group_by(Wishlist.game_id)
        .subquery()
    )
    vote_counts = (
        db.session.query(WishlistVote.game_id, func.count(WishlistVote.id).label("vote_count"))
        .group_by(WishlistVote.game_id)
        .subquery()
    )

    rows = (
        db.session.query(
            Game,
            func.coalesce(wishlist_counts.c.wl_count, 0).label("wl_count"),
            func.coalesce(vote_counts.c.vote_count, 0).label("vote_count"),
        )
        .outerjoin(wishlist_counts, Game.id == wishlist_counts.c.game_id)
        .outerjoin(vote_counts, Game.id == vote_counts.c.game_id)
        .filter((wishlist_counts.c.wl_count > 0) | (vote_counts.c.vote_count > 0))
        .order_by(
            (
                func.coalesce(wishlist_counts.c.wl_count, 0)
                + func.coalesce(vote_counts.c.vote_count, 0)
            ).desc()
        )
        .all()
    )

    user_wishlisted = {w.game_id for w in Wishlist.query.filter_by(person_id=user_id).all()}
    user_voted = {v.game_id for v in WishlistVote.query.filter_by(person_id=user_id).all()}

    return [
        {
            "game": game,
            "total_want": wl_count + vote_count,
            "user_wishlisted": game.id in user_wishlisted,
            "user_voted": game.id in user_voted,
        }
        for game, wl_count, vote_count in rows
    ]


def toggle_wishlist_vote(user_id, game_id):
    """Add or remove a wishlist vote. Blocked if the game is already on the user's wishlist."""
    if Wishlist.query.filter_by(person_id=user_id, game_id=game_id).first():
        return False, "This game is already on your wishlist."

    existing = WishlistVote.query.filter_by(person_id=user_id, game_id=game_id).first()
    if existing:
        db.session.delete(existing)
        db.session.commit()
        return True, "Vote removed."

    db.session.add(WishlistVote(person_id=user_id, game_id=game_id))
    db.session.commit()
    return True, "Vote added."


def update_game_rating(game_id, user_id, ranking):
    """Update or create a game rating for a user."""
    if ranking is None or not (0 <= ranking <= 10):
        return False, "Invalid rating. Must be between 0 and 10."

    rating = GameRatings.query.filter_by(game_id=game_id, person_id=user_id).first()

    if rating:
        rating.ranking = ranking  # Update existing
    else:
        rating = GameRatings(game_id=game_id, person_id=user_id, ranking=ranking)
        db.session.add(rating)

    db.session.commit()

    return True, "Rating saved successfully."


def update_tutorial_url(game_id, tutorial_url):
    game = Game.query.get_or_404(game_id)

    game.tutorial_url = tutorial_url.strip() or None
    db.session.commit()
    return game


def get_user_stats(
    user_id,
    game_ids=None,
    opponent_ids=None,
    start_date=None,
    end_date=None,
    sort_by="wins",
    sort_order="desc",
):
    # Base query to fetch user's game results
    query = (
        db.session.query(
            GameNightGame.game_id,
            Game.name.label("game_name"),
            func.count(Result.id).label("games_played"),
            func.sum(case((Result.position == 1, 1), else_=0)).label("wins"),
            func.avg(Result.position).label("average_position"),
            func.max(GameNightGame.created_at).label("last_played"),
        )
        .join(Result, GameNightGame.id == Result.game_night_game_id)
        .join(Player, Result.player_id == Player.id)
        .join(Game, GameNightGame.game_id == Game.id)
        .filter(Player.people_id == user_id)
    )

    # Apply game filter
    if game_ids:
        query = query.filter(GameNightGame.game_id.in_(game_ids))

    # Apply date filters
    if start_date:
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            query = query.filter(GameNightGame.created_at >= start)
        except ValueError:
            pass  # Invalid date format; ignore filter

    if end_date:
        try:
            end = datetime.strptime(end_date, "%Y-%m-%d")
            query = query.filter(GameNightGame.created_at <= end)
        except ValueError:
            pass  # Invalid date format; ignore filter

    # Apply opponent filter
    if opponent_ids:
        subquery = (
            db.session.query(Result.game_night_game_id)
            .join(Player, Result.player_id == Player.id)
            .filter(Player.people_id.in_(opponent_ids))
            .group_by(Result.game_night_game_id)
            .having(func.count(distinct(Player.people_id)) == len(opponent_ids))
            .subquery()
        )

        query = query.filter(GameNightGame.id.in_(subquery))

    # Group by game
    query = query.group_by(GameNightGame.game_id, Game.name)

    # Apply sorting
    sort_column = {
        "wins": func.sum(case((Result.position == 1, 1), else_=0)).label("wins"),
        "games_played": func.count(Result.id),
        "average_position": func.avg(Result.position),
        "last_played": func.max(GameNightGame.created_at),
        "game_name": Game.name,
    }.get(sort_by, func.sum(case((Result.position == 1, 1), else_=0)).label("wins"))

    if sort_order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    return query.all()


def get_selected_games(game_ids):
    if not game_ids:
        return []
    return db.session.query(Game.id, Game.name).filter(Game.id.in_(game_ids)).all()


def get_selected_opponents(opponent_ids):
    if not opponent_ids:
        return []
    return (
        db.session.query(Person.id, Person.first_name, Person.last_name)
        .filter(Person.id.in_(opponent_ids))
        .all()
    )
