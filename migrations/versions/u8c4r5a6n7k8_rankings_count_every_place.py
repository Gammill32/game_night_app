"""night rankings count every place, not just 1st to 4th

Revision ID: u8c4r5a6n7k8
Revises: u8c3v4i5e6w7
Create Date: 2026-10-09

game_night_rankings_view ranks players by how many 1sts they had, then 2nds,
and so on, then by total score. It only counted places 1 to 4 (and only the
scores from those results), so on bigger nights everyone who never placed
in the top four tied, e.g. 5th and 6th both showed as 5th. Places now run to
the lowest place recorded that night (at least 4, so nights where everyone
placed in the top four rank exactly as before). Only the view changes.

The view's id column is row_number() OVER (), which is not stable between
queries; the app only ever selects columns from it, never loads rows by id.
"""

from alembic import op

revision = "u8c4r5a6n7k8"
down_revision = "u8c3v4i5e6w7"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DROP VIEW IF EXISTS public.game_night_rankings_view;")
    op.execute("""
        CREATE VIEW public.game_night_rankings_view AS
        WITH positions AS (
            -- 1 to 4, or further on nights where someone placed lower.
            SELECT gng.game_night_id, generate_series(1, GREATEST(4, max(r.position))) AS position
            FROM public.gamenightgames gng
            JOIN public.results r ON r.game_night_game_id = gng.id
            GROUP BY gng.game_night_id
        ), players_in_games AS (
            SELECT DISTINCT gng.game_night_id, r.player_id
            FROM public.gamenightgames gng
            JOIN public.results r ON r.game_night_game_id = gng.id
        ), ranked_players AS (
            SELECT
                pig.game_night_id,
                pig.player_id,
                pos.position,
                count(r.id) AS count,
                sum(COALESCE(r.score, 0)) AS total_score
            FROM players_in_games pig
            JOIN positions pos ON pos.game_night_id = pig.game_night_id
            LEFT JOIN public.results r ON
                r.player_id = pig.player_id
                AND r.position = pos.position
                AND r.game_night_game_id IN (
                    SELECT id FROM public.gamenightgames
                    WHERE game_night_id = pig.game_night_id
                )
            GROUP BY pig.game_night_id, pig.player_id, pos.position
        ), aggregated_scores AS (
            SELECT
                game_night_id,
                player_id,
                array_agg(count ORDER BY position) AS position_counts,
                sum(total_score) AS overall_score
            FROM ranked_players
            GROUP BY game_night_id, player_id
        ), ranked AS (
            SELECT
                game_night_id,
                player_id,
                position_counts,
                overall_score,
                dense_rank() OVER (
                    PARTITION BY game_night_id
                    ORDER BY position_counts DESC, overall_score DESC
                ) AS rank
            FROM aggregated_scores
        )
        SELECT
            row_number() OVER () AS id,
            game_night_id,
            player_id,
            position_counts,
            overall_score,
            rank
        FROM ranked;
    """)


def downgrade():
    op.execute("DROP VIEW IF EXISTS public.game_night_rankings_view;")
    op.execute("""
        CREATE VIEW public.game_night_rankings_view AS
        WITH positions AS (
            SELECT unnest(ARRAY[1, 2, 3, 4]) AS position
        ), players_in_games AS (
            SELECT DISTINCT gng.game_night_id, r.player_id
            FROM public.gamenightgames gng
            JOIN public.results r ON r.game_night_game_id = gng.id
        ), ranked_players AS (
            SELECT
                pig.game_night_id,
                pig.player_id,
                pos.position,
                count(r.id) AS count,
                sum(COALESCE(r.score, 0)) AS total_score
            FROM players_in_games pig
            CROSS JOIN positions pos
            LEFT JOIN public.results r ON
                r.player_id = pig.player_id
                AND r.position = pos.position
                AND r.game_night_game_id IN (
                    SELECT id FROM public.gamenightgames
                    WHERE game_night_id = pig.game_night_id
                )
            GROUP BY pig.game_night_id, pig.player_id, pos.position
        ), aggregated_scores AS (
            SELECT
                game_night_id,
                player_id,
                array_agg(count ORDER BY position) AS position_counts,
                sum(total_score) AS overall_score
            FROM ranked_players
            GROUP BY game_night_id, player_id
        ), ranked AS (
            SELECT
                game_night_id,
                player_id,
                position_counts,
                overall_score,
                dense_rank() OVER (
                    PARTITION BY game_night_id
                    ORDER BY position_counts DESC, overall_score DESC
                ) AS rank
            FROM aggregated_scores
        )
        SELECT
            row_number() OVER () AS id,
            game_night_id,
            player_id,
            position_counts,
            overall_score,
            rank
        FROM ranked;
    """)
