"""fix date-at-timezone bug in game night views

Revision ID: h5i6j7k8l9m0
Revises: g4h5i6j7k8l9
Create Date: 2026-04-03

The original views applied `AT TIME ZONE 'America/Chicago'` to a Date column.
PostgreSQL implicitly casts Date to timestamp-at-midnight-UTC before shifting,
which means a game night stored as 2024-12-15 appears as 2024-12-14 in the
view during winter (UTC-6). Since the date column already stores the local
calendar date (not a UTC timestamp), the timezone conversion should not be
applied at all. This migration drops and recreates the affected views using
CURRENT_DATE directly.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "h5i6j7k8l9m0"
down_revision = "g4h5i6j7k8l9"
branch_labels = None
depends_on = None


def upgrade():
    # Drop dependent views first (user_recent_future relies on user_game_nights_list)
    op.execute("DROP VIEW IF EXISTS public.user_recent_future_game_nights;")
    op.execute("DROP VIEW IF EXISTS public.admin_recent_future_game_nights;")
    op.execute("DROP VIEW IF EXISTS public.user_game_nights_list;")
    op.execute("DROP VIEW IF EXISTS public.admin_game_nights_list;")

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


def downgrade():
    op.execute("DROP VIEW IF EXISTS public.user_recent_future_game_nights;")
    op.execute("DROP VIEW IF EXISTS public.admin_recent_future_game_nights;")
    op.execute("DROP VIEW IF EXISTS public.user_game_nights_list;")
    op.execute("DROP VIEW IF EXISTS public.admin_game_nights_list;")

    # Restore original (buggy) views
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
