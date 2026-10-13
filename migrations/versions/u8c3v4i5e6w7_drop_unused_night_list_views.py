"""drop the unused game-night list views

Revision ID: u8c3v4i5e6w7
Revises: u8c2u3n4i5q6
Create Date: 2026-10-09

user_game_nights_list, user_recent_future_game_nights, admin_game_nights_list
and admin_recent_future_game_nights are not read anywhere in the app. Dropping
views deletes no data. Downgrade recreates them as h5i6j7k8l9m0 left them.
"""

from alembic import op

revision = "u8c3v4i5e6w7"
down_revision = "u8c2u3n4i5q6"
branch_labels = None
depends_on = None


def upgrade():
    # user_recent_future_game_nights reads user_game_nights_list, so it goes first.
    op.execute("DROP VIEW IF EXISTS public.user_recent_future_game_nights;")
    op.execute("DROP VIEW IF EXISTS public.admin_recent_future_game_nights;")
    op.execute("DROP VIEW IF EXISTS public.user_game_nights_list;")
    op.execute("DROP VIEW IF EXISTS public.admin_game_nights_list;")


def downgrade():
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
                gn.date,
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
            WHERE ugn.date < CURRENT_DATE
        )
        SELECT
            row_number() OVER () AS id,
            game_night_id, date, notes, final, closed, user_id
        FROM (
            SELECT ugn.game_night_id, ugn.date, ugn.notes, ugn.final, ugn.closed, ugn.user_id
            FROM user_game_nights ugn
            WHERE ugn.date >= CURRENT_DATE
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
                gn.date,
                gn.notes,
                gn.final,
                gn.closed
            FROM public.gamenights gn
        ), past_game_nights AS (
            SELECT ugn.game_night_id, ugn.date, ugn.notes, ugn.final, ugn.closed
            FROM user_game_nights ugn
            WHERE ugn.date < CURRENT_DATE
            ORDER BY ugn.date DESC
            LIMIT 3
        )
        SELECT game_night_id, date, notes, final, closed
        FROM (
            SELECT ugn.game_night_id, ugn.date, ugn.notes, ugn.final, ugn.closed
            FROM user_game_nights ugn
            WHERE ugn.date >= CURRENT_DATE
            UNION ALL
            SELECT past.game_night_id, past.date, past.notes, past.final, past.closed
            FROM past_game_nights past
        ) combined
        ORDER BY date DESC;
    """)
