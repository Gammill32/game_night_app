"""create views

Revision ID: a1b2c3d4e5f6
Revises: 82a37a1f8996
Create Date: 2026-03-31

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "82a37a1f8996"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE VIEW public.games_index AS
        SELECT
            g.id AS game_id,
            g.name AS game_name,
            g.image_url,
            g.min_players,
            g.max_players,
            g.playtime,
            ob.person_id AS owner_id,
            pe.owner AS player_owner,
            CASE
                WHEN ob.person_id IS NOT NULL THEN true
                ELSE false
            END AS user_owns_game
        FROM public.games g
        LEFT JOIN public.ownedby ob ON g.id = ob.game_id
        LEFT JOIN public.people pe ON pe.id = ob.person_id;
    """)

    op.execute("""
        CREATE VIEW public.user_game_nights_list AS
        SELECT
            row_number() OVER () AS id,
            gn.id AS game_night_id,
            gn.date,
            gn.notes,
            gn.final,
            gn.closed,
            COALESCE(p.people_id, 0) AS user_id
        FROM public.gamenights gn
        LEFT JOIN public.players p ON p.game_night_id = gn.id;
    """)

    op.execute("""
        CREATE VIEW public.user_recent_future_game_nights AS
        WITH user_game_nights AS (
            SELECT DISTINCT
                gn.game_night_id,
                ((gn.date AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago') AS date,
                gn.notes,
                gn.final,
                gn.closed,
                gn.user_id
            FROM public.user_game_nights_list gn
        ), past_game_nights AS (
            SELECT
                ugn.game_night_id, ugn.date, ugn.notes, ugn.final, ugn.closed, ugn.user_id,
                row_number() OVER (PARTITION BY ugn.user_id ORDER BY ugn.date DESC) AS row_num
            FROM user_game_nights ugn
            WHERE ugn.date < ((CURRENT_DATE AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago')
        )
        SELECT
            row_number() OVER () AS id,
            game_night_id, date, notes, final, closed, user_id
        FROM (
            SELECT ugn.game_night_id, ugn.date, ugn.notes, ugn.final, ugn.closed, ugn.user_id
            FROM user_game_nights ugn
            WHERE ugn.date >= ((CURRENT_DATE AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago')
            UNION ALL
            SELECT past.game_night_id, past.date, past.notes, past.final, past.closed, past.user_id
            FROM past_game_nights past
            WHERE past.row_num <= 3
        ) combined
        ORDER BY date DESC;
    """)

    op.execute("""
        CREATE VIEW public.admin_game_nights_list AS
        SELECT row_number() OVER () AS id,
            id AS game_night_id,
            date,
            notes,
            final,
            closed
        FROM public.gamenights gn;
    """)

    op.execute("""
        CREATE VIEW public.admin_recent_future_game_nights AS
        WITH user_game_nights AS (
            SELECT DISTINCT gn.id AS game_night_id,
                ((gn.date AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago') AS date,
                gn.notes,
                gn.final,
                gn.closed
            FROM public.gamenights gn
        ), past_game_nights AS (
            SELECT ugn.game_night_id, ugn.date, ugn.notes, ugn.final, ugn.closed
            FROM user_game_nights ugn
            WHERE ugn.date < ((CURRENT_DATE AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago')
            ORDER BY ugn.date DESC
            LIMIT 3
        )
        SELECT game_night_id, date, notes, final, closed
        FROM (
            SELECT ugn.game_night_id, ugn.date, ugn.notes, ugn.final, ugn.closed
            FROM user_game_nights ugn
            WHERE ugn.date >= ((CURRENT_DATE AT TIME ZONE 'UTC') AT TIME ZONE 'America/Chicago')
            UNION ALL
            SELECT past.game_night_id, past.date, past.notes, past.final, past.closed
            FROM past_game_nights past
        ) combined
        ORDER BY date DESC;
    """)

    op.execute("""
        CREATE VIEW public.earliest_game_night AS
        SELECT min(date) AS earliest_date
        FROM public.gamenights;
    """)

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

    op.execute("""
        CREATE VIEW public.game_night_game_results AS
        SELECT
            gng.id AS game_night_game_id,
            gng.game_night_id,
            gng.game_id,
            gng.round,
            g.name AS game_name,
            g.image_url AS game_image_url,
            COALESCE(
                json_agg(
                    json_build_object(
                        'player_id', r.player_id,
                        'first_name', p.first_name,
                        'last_name', p.last_name,
                        'position', r.position,
                        'score', r.score
                    ) ORDER BY r.position, r.score DESC
                ) FILTER (WHERE r.id IS NOT NULL),
                '[]'::json
            ) AS results
        FROM public.gamenightgames gng
        LEFT JOIN public.results r ON gng.id = r.game_night_game_id
        LEFT JOIN public.games g ON gng.game_id = g.id
        LEFT JOIN public.players pl ON r.player_id = pl.id
        LEFT JOIN public.people p ON pl.people_id = p.id
        GROUP BY gng.id, gng.game_night_id, gng.game_id, g.name, g.image_url
        ORDER BY gng.id;
    """)

    op.execute("""
        CREATE VIEW public.game_night_nominations_votes AS
        SELECT
            gn.id AS game_night_id,
            g.id AS game_id,
            g.name AS game_name,
            g.image_url,
            count(DISTINCT gnm.id) AS total_nominations,
            COALESCE(sum(
                CASE
                    WHEN gv.rank = 1 THEN 3
                    WHEN gv.rank = 2 THEN 2
                    WHEN gv.rank = 3 THEN 1
                    ELSE 0
                END
            ), 0) AS vote_score
        FROM public.gamenights gn
        LEFT JOIN (
            SELECT DISTINCT game_id, game_night_id FROM public.game_nominations
            UNION
            SELECT DISTINCT game_id, game_night_id FROM public.game_votes
        ) included_games ON included_games.game_night_id = gn.id
        JOIN public.games g ON included_games.game_id = g.id
        LEFT JOIN public.game_nominations gnm ON gnm.game_id = g.id AND gnm.game_night_id = gn.id
        LEFT JOIN public.game_votes gv ON gv.game_id = g.id AND gv.game_night_id = gn.id
        GROUP BY gn.id, g.id, g.name, g.image_url
        ORDER BY gn.id DESC, vote_score DESC, total_nominations DESC;
    """)


def downgrade():
    op.execute("DROP VIEW IF EXISTS public.game_night_nominations_votes;")
    op.execute("DROP VIEW IF EXISTS public.game_night_game_results;")
    op.execute("DROP VIEW IF EXISTS public.game_night_rankings_view;")
    op.execute("DROP VIEW IF EXISTS public.earliest_game_night;")
    op.execute("DROP VIEW IF EXISTS public.admin_recent_future_game_nights;")
    op.execute("DROP VIEW IF EXISTS public.admin_game_nights_list;")
    op.execute("DROP VIEW IF EXISTS public.user_recent_future_game_nights;")
    op.execute("DROP VIEW IF EXISTS public.user_game_nights_list;")
    op.execute("DROP VIEW IF EXISTS public.games_index;")
