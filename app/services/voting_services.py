from app.models import (
    Game,
    GameNight,
    GameNominations,
    GameVotes,
    Player,
    db,
)
from app.services import night_policy

VALID_RANKS = {1, 2, 3}


def _voting_error(game_night_id):
    """Why nominating or ranking isn't allowed right now, or None."""
    try:
        night_policy.require_voting_open(db.get_or_404(GameNight, game_night_id))
    except night_policy.NightRuleError as e:
        return str(e)
    return None


def nominate_game(game_night_id, user_id, game_id):
    """Handles nomination of a game for an upcoming game night."""
    error = _voting_error(game_night_id)
    if error:
        return False, error

    current_player = Player.query.filter_by(game_night_id=game_night_id, people_id=user_id).first()

    if not current_player:
        return False, "User is not a player in this game night."

    player_id = current_player.id

    if not game_id:
        return False, "You must select a game to nominate."
    try:
        game_id = int(game_id)
    except (TypeError, ValueError):
        return False, "You must select a game to nominate."
    if db.session.get(Game, game_id) is None:
        return False, "That game isn't in the collection."

    existing_nomination = GameNominations.query.filter_by(
        game_night_id=game_night_id, game_id=game_id
    ).first()
    if existing_nomination and existing_nomination.player_id != player_id:
        return False, "This game has already been nominated by another player."

    nomination = GameNominations.query.filter_by(
        game_night_id=game_night_id, player_id=player_id
    ).first()
    game = db.session.get(Game, int(game_id))
    name = game.name if game else "that game"

    if nomination:
        if nomination.game_id == int(game_id):
            return True, f"{name} is already your nomination."
        # The game you're replacing is no longer nominated, so rankings of
        # it (anyone's) no longer count. Your other rankings stay.
        GameVotes.query.filter_by(game_night_id=game_night_id, game_id=nomination.game_id).delete()
        nomination.game_id = game_id
        message = f"You're now nominating {name}. Rankings of your old pick were removed."
    else:
        db.session.add(
            GameNominations(game_night_id=game_night_id, player_id=player_id, game_id=game_id)
        )
        message = f"You nominated {name}. Next: rank your top 3 games."
    db.session.commit()
    return True, message


def vote_game(game_night_id, user_id, votes_dict):
    """Handles voting for nominated games in a game night."""
    error = _voting_error(game_night_id)
    if error:
        return False, error

    current_player = Player.query.filter_by(game_night_id=game_night_id, people_id=user_id).first()

    if not current_player:
        return False, "User is not a player in this game night."

    player_id = current_player.id

    nominated = {n.game_id for n in GameNominations.query.filter_by(game_night_id=game_night_id)}
    if any(game_id not in nominated for game_id in votes_dict):
        return (
            False,
            "Only nominated games can be ranked. The list may have changed; check it and save again.",
        )
    if any(rank is not None and rank not in VALID_RANKS for rank in votes_dict.values()):
        return False, "Rank games 1st, 2nd or 3rd."

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
    ranked = sum(1 for rank in votes_dict.values() if rank is not None)
    if not ranked:
        return True, "Your ranking is cleared."
    return True, f"Your ranking is saved ({ranked} of 3 picked)."
