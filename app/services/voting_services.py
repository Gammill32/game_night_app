from flask import request
from sqlalchemy import func

from app.models import (
    Game,
    GameNight,
    GameNightNominationsVotes,
    GameNominations,
    GameRatings,
    GameVotes,
    OwnedBy,
    Player,
    Wishlist,
    db,
)


def nominate_game(game_night_id, user_id, game_id):
    """Handles nomination of a game for an upcoming game night."""
    current_player = Player.query.filter_by(game_night_id=game_night_id, people_id=user_id).first()

    if not current_player:
        return False, "User is not a player in this game night."

    player_id = current_player.id

    if not game_id:
        return False, "You must select a game to nominate."

    existing_nomination = GameNominations.query.filter_by(
        game_night_id=game_night_id, game_id=game_id
    ).first()
    if existing_nomination and existing_nomination.player_id != player_id:
        return False, "This game has already been nominated by another player."

    GameVotes.query.filter_by(game_night_id=game_night_id, player_id=player_id).delete()
    nomination = GameNominations.query.filter_by(
        game_night_id=game_night_id, player_id=player_id
    ).first()

    if nomination:
        nomination.game_id = game_id
        message = "Your nomination has been updated, and your votes have been cleared."
    else:
        new_nomination = GameNominations(
            game_night_id=game_night_id, player_id=player_id, game_id=game_id
        )
        db.session.add(new_nomination)
        message = "Your nomination has been submitted, and any previous votes have been cleared."

    db.session.commit()
    return True, message


def vote_game(game_night_id, user_id, votes_dict):
    """Handles voting for nominated games in a game night."""
    current_player = Player.query.filter_by(game_night_id=game_night_id, people_id=user_id).first()

    if not current_player:
        return False, "User is not a player in this game night."

    player_id = current_player.id

    used_ranks = set()
    for game_id, rank in votes_dict.items():
        if rank is not None:
            if rank in used_ranks:
                return (
                    False,
                    f"Rank {rank} is already used for another game. Each rank can only be assigned once.",
                )
            used_ranks.add(rank)

    for game_id, rank in votes_dict.items():
        existing_vote = GameVotes.query.filter_by(
            game_night_id=game_night_id, player_id=player_id, game_id=game_id
        ).first()

        if rank is None:
            if existing_vote:
                db.session.delete(existing_vote)
        else:
            if existing_vote:
                existing_vote.rank = rank
            else:
                new_vote = GameVotes(
                    game_night_id=game_night_id, player_id=player_id, game_id=game_id, rank=rank
                )
                db.session.add(new_vote)

    db.session.commit()
    return True, "Your votes have been updated successfully."


def get_nominate_game_page_context(game_night_id, current_user_id):
    """Fetch all data needed to render the nominate a game page."""
    game_night = GameNight.query.get_or_404(game_night_id)

    # Pull filters from the request
    name_filter = request.args.get("name", "").strip() if request.args.get("name_enabled") else None
    players_filter = (
        request.args.get("players", type=int) if request.args.get("players_enabled") else None
    )
    playtime_filter = (
        request.args.get("playtime", type=int) if request.args.get("playtime_enabled") else None
    )

    # Fetch games based on filters
    raw_games = get_eligible_games_for_nomination(
        game_night_id,
        name_filter=name_filter,
        players_filter=players_filter,
        playtime_filter=playtime_filter,
    )

    wishlist_game_ids = {
        w.game_id for w in Wishlist.query.filter_by(person_id=current_user_id).all()
    }

    owned_game_ids = {o.game_id for o in OwnedBy.query.filter_by(person_id=current_user_id).all()}

    eligible_game_ids = {game.id for game in raw_games}

    # Get player IDs attending the game night
    player_people_ids = [
        player.people_id for player in Player.query.filter_by(game_night_id=game_night_id).all()
    ]

    # Fetch avg ratings for eligible games by players attending
    avg_ratings_query = (
        db.session.query(GameRatings.game_id, func.avg(GameRatings.ranking).label("avg_rating"))
        .filter(
            GameRatings.person_id.in_(player_people_ids), GameRatings.game_id.in_(eligible_game_ids)
        )
        .group_by(GameRatings.game_id)
        .all()
    )

    avg_ratings_by_game_id = {
        game_id: round(avg_rating, 1) for game_id, avg_rating in avg_ratings_query
    }

    # Assemble eligible games list
    eligible_games = [
        {
            "game": game,
            "in_wishlist": game.id in wishlist_game_ids,
            "owned": game.id in owned_game_ids,
            "avg_rating": avg_ratings_by_game_id.get(game.id),
        }
        for game in raw_games
    ]

    # Optional: Sort by avg_rating descending, then name
    eligible_games.sort(
        key=lambda g: (
            -g["avg_rating"] if g["avg_rating"] is not None else float("inf"),
            g["game"].name.lower(),
        )
    )

    # Get current player's nomination (if any)
    current_player = Player.query.filter_by(
        game_night_id=game_night_id, people_id=current_user_id
    ).first()

    user_nomination_id = None
    if current_player:
        nomination = GameNominations.query.filter_by(
            game_night_id=game_night_id, player_id=current_player.id
        ).first()
        if nomination:
            user_nomination_id = nomination.game_id

    return {
        "eligible_games": eligible_games,
        "game_night": game_night,
        "user_nomination_id": user_nomination_id,
        "filters": {
            "name": name_filter,
            "players": players_filter,
            "playtime": playtime_filter,
        },
    }


def get_eligible_games_for_nomination(
    game_night_id, name_filter=None, players_filter=None, playtime_filter=None
):
    """Fetch games user can nominate, applying optional filters."""
    game_night = GameNight.query.get_or_404(game_night_id)
    player_ids = [player.people_id for player in game_night.players]

    nominated_game_ids = {
        n.game_id
        for n in GameNightNominationsVotes.query.filter_by(game_night_id=game_night_id).all()
    }

    owned_game_ids = (
        db.session.query(OwnedBy.game_id).filter(OwnedBy.person_id.in_(player_ids)).subquery()
    )

    query = db.session.query(Game).filter(
        Game.id.in_(owned_game_ids), ~Game.id.in_(nominated_game_ids)
    )

    if name_filter:
        query = query.filter(Game.name.ilike(f"%{name_filter}%"))
    if players_filter is not None:
        query = query.filter(Game.min_players <= players_filter, Game.max_players >= players_filter)
    if playtime_filter is not None:
        query = query.filter(Game.playtime <= playtime_filter)

    return query.order_by(Game.name).all()
