"""unique constraints for players, results, votes, wishlists and nominations

Revision ID: u8c2u3n4i5q6
Revises: u8c1a2s3c4d5
Create Date: 2026-10-09

The app only ever means to store one of each of these, but nothing in the
database stopped a double-submit from storing two:

    players           (game_night_id, people_id)   uq_players_night_person
    results           (game_night_game_id, player_id)  uq_results_game_player
    game_votes        (player_id, game_id)          uq_game_votes_player_game
    wishlist          (person_id, game_id)          uq_wishlist_person_game
    game_nominations  (game_night_id, game_id)      uq_game_nominations_night_game

A game can only be nominated once per night: nominate_game refuses a game
someone else has already nominated, and the standings view joins nominations
to votes, so a second nomination of the same game doubled its vote score.

Existing duplicates are resolved first, in this order:

1. Duplicate players (same person twice on a night) are merged into the
   oldest row (lowest id). Their rows elsewhere are moved onto it:
   - results: all moved (step 2 then keeps the newest per game);
   - votes: moved only if the kept row has no votes that night, otherwise
     dropped, so the person keeps one consistent top 3;
   - nomination: moved if the kept row has none that night, otherwise
     dropped (one nomination per player per night already applies);
   - tracker values and team spots: moved unless the kept row already has
     one for that field/team, in which case the duplicate's is dropped.
   The duplicate player rows are then deleted.
2. Duplicate results for one player in one game: the most recent
   (latest created_at, then highest id) is kept, the others deleted.
3. Duplicate votes by one player for one game: the highest id is kept.
4. A game nominated more than once on a night: the earliest nomination
   (lowest id) is kept; the other nominators are left free to nominate
   again. Votes for the game still count, since it is still nominated.
5. Votes for a game that is no longer nominated that night (only possible
   after a nomination was dropped in step 1) are deleted, as in q4r5s6t7u8v9.
6. Duplicate wishlist rows (identical apart from id): the lowest id is kept.

Downgrade drops the constraints; deleted duplicates are not restored.
"""

from alembic import op

revision = "u8c2u3n4i5q6"
down_revision = "u8c1a2s3c4d5"
branch_labels = None
depends_on = None

CONSTRAINTS = (
    ("uq_players_night_person", "players", ["game_night_id", "people_id"]),
    ("uq_results_game_player", "results", ["game_night_game_id", "player_id"]),
    ("uq_game_votes_player_game", "game_votes", ["player_id", "game_id"]),
    ("uq_wishlist_person_game", "wishlist", ["person_id", "game_id"]),
    ("uq_game_nominations_night_game", "game_nominations", ["game_night_id", "game_id"]),
)


def _merge_duplicate_players():
    op.execute(
        """
        CREATE TEMP TABLE player_merge AS
        SELECT id AS dup_id, keep_id
        FROM (
            SELECT id, min(id) OVER (PARTITION BY game_night_id, people_id) AS keep_id
            FROM players
            WHERE game_night_id IS NOT NULL AND people_id IS NOT NULL
        ) p
        WHERE id <> keep_id
        """
    )

    # Results: move them all; duplicates per game are settled afterwards.
    op.execute(
        """
        UPDATE results r SET player_id = m.keep_id
        FROM player_merge m WHERE r.player_id = m.dup_id
        """
    )

    # Votes: the kept player's ranking wins if it has one.
    op.execute(
        """
        DELETE FROM game_votes v USING player_merge m
        WHERE v.player_id = m.dup_id
          AND EXISTS (SELECT 1 FROM game_votes k WHERE k.player_id = m.keep_id)
        """
    )
    # If several duplicates (none of them the kept row) have votes, keep the
    # earliest duplicate's.
    op.execute(
        """
        DELETE FROM game_votes v USING player_merge m
        WHERE v.player_id = m.dup_id
          AND EXISTS (
              SELECT 1 FROM game_votes o JOIN player_merge om ON om.dup_id = o.player_id
              WHERE om.keep_id = m.keep_id AND o.player_id < m.dup_id
          )
        """
    )
    op.execute(
        """
        UPDATE game_votes v SET player_id = m.keep_id
        FROM player_merge m WHERE v.player_id = m.dup_id
        """
    )

    # Nominations: one per player per night (uq_game_nominations_night_player).
    op.execute(
        """
        DELETE FROM game_nominations n USING player_merge m
        WHERE n.player_id = m.dup_id
          AND EXISTS (
              SELECT 1 FROM game_nominations o
              WHERE o.game_night_id = n.game_night_id
                AND (o.player_id = m.keep_id
                     OR (o.player_id < n.player_id
                         AND o.player_id IN (SELECT dup_id FROM player_merge
                                             WHERE keep_id = m.keep_id)))
          )
        """
    )
    op.execute(
        """
        UPDATE game_nominations n SET player_id = m.keep_id
        FROM player_merge m WHERE n.player_id = m.dup_id
        """
    )

    # Tracker values: unique per (field, player, team).
    op.execute(
        """
        DELETE FROM tracker_values v USING player_merge m
        WHERE v.player_id = m.dup_id
          AND EXISTS (
              SELECT 1 FROM tracker_values o
              WHERE o.tracker_field_id = v.tracker_field_id
                AND o.team_id IS NOT DISTINCT FROM v.team_id
                AND (o.player_id = m.keep_id
                     OR (o.player_id < v.player_id
                         AND o.player_id IN (SELECT dup_id FROM player_merge
                                             WHERE keep_id = m.keep_id)))
          )
        """
    )
    op.execute(
        """
        UPDATE tracker_values v SET player_id = m.keep_id
        FROM player_merge m WHERE v.player_id = m.dup_id
        """
    )

    # Team spots: primary key (team_id, player_id).
    op.execute(
        """
        DELETE FROM tracker_team_players t USING player_merge m
        WHERE t.player_id = m.dup_id
          AND EXISTS (
              SELECT 1 FROM tracker_team_players o
              WHERE o.team_id = t.team_id
                AND (o.player_id = m.keep_id
                     OR (o.player_id < t.player_id
                         AND o.player_id IN (SELECT dup_id FROM player_merge
                                             WHERE keep_id = m.keep_id)))
          )
        """
    )
    op.execute(
        """
        UPDATE tracker_team_players t SET player_id = m.keep_id
        FROM player_merge m WHERE t.player_id = m.dup_id
        """
    )

    op.execute("DELETE FROM players p USING player_merge m WHERE p.id = m.dup_id")
    op.execute("DROP TABLE player_merge")


def _keep_first(table, key, order):
    """Delete all but the first row (by `order`) of each group of `key`."""
    cols = ", ".join(key)
    not_null = " AND ".join(f"{c} IS NOT NULL" for c in key)
    op.execute(
        f"""
        DELETE FROM {table} WHERE id IN (
            SELECT id FROM (
                SELECT id, row_number() OVER (PARTITION BY {cols} ORDER BY {order}) AS rn
                FROM {table} WHERE {not_null}
            ) ranked
            WHERE rn > 1
        )
        """
    )


def upgrade():
    _merge_duplicate_players()
    _keep_first(
        "results", ["game_night_game_id", "player_id"], "created_at DESC NULLS LAST, id DESC"
    )
    _keep_first("game_votes", ["player_id", "game_id"], "id DESC")
    _keep_first("game_nominations", ["game_night_id", "game_id"], "id")
    op.execute(
        """
        DELETE FROM game_votes gv
        WHERE NOT EXISTS (
            SELECT 1 FROM game_nominations n
            WHERE n.game_night_id = gv.game_night_id AND n.game_id = gv.game_id
        )
        """
    )
    _keep_first("wishlist", ["person_id", "game_id"], "id")

    for name, table, cols in CONSTRAINTS:
        op.create_unique_constraint(name, table, cols)


def downgrade():
    for name, table, _cols in reversed(CONSTRAINTS):
        op.drop_constraint(name, table, type_="unique")
