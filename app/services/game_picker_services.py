"""The game list behind the nominate and add-a-game pages.

Both pick from the games owned by the night's players. Each item carries what
helps choose: who owns it, how the night's players rate it, whether it's been
nominated and how the vote stands. Filtering (search, player count, length)
happens in the browser.
"""

from sqlalchemy import func

from app.extensions import db
from app.models import (
    Game,
    GameNightNominationsVotes,
    GameNominations,
    GameRatings,
    OwnedBy,
    Person,
    Player,
    Wishlist,
)


def picker_items(game_night, viewer_id):
    player_ids = [p.people_id for p in Player.query.filter_by(game_night_id=game_night.id)]

    owners: dict[int, list[str]] = {}
    for game_id, first_name in (
        db.session.query(OwnedBy.game_id, Person.first_name)
        .join(Person, Person.id == OwnedBy.person_id)
        .filter(OwnedBy.person_id.in_(player_ids))
        .order_by(Person.first_name)
    ):
        owners.setdefault(game_id, []).append(first_name)

    ratings = dict(
        db.session.query(GameRatings.game_id, func.avg(GameRatings.ranking))
        .filter(GameRatings.person_id.in_(player_ids), GameRatings.game_id.in_(owners))
        .group_by(GameRatings.game_id)
        .all()
    )
    votes = {
        v.game_id: v.vote_score or 0
        for v in GameNightNominationsVotes.query.filter_by(game_night_id=game_night.id)
    }
    nominators = {
        n.game_id: n.player.person.first_name
        for n in GameNominations.query.filter_by(game_night_id=game_night.id)
    }
    wishlist = {w.game_id for w in Wishlist.query.filter_by(person_id=viewer_id)}

    items = []
    for game in Game.query.filter(Game.id.in_(owners)).order_by(Game.name):
        rating = ratings.get(game.id)
        items.append(
            {
                "game": game,
                "owners": owners[game.id],
                "avg_rating": round(float(rating), 1) if rating is not None else None,
                "nominated_by": nominators.get(game.id),
                "vote_score": votes.get(game.id, 0),
                "in_wishlist": game.id in wishlist,
            }
        )
    return items, len(player_ids)
