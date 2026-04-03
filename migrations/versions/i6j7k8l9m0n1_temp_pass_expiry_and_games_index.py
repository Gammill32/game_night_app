"""temp password expiry and games_index multi-owner fix

Revision ID: i6j7k8l9m0n1
Revises: h5i6j7k8l9m0
Create Date: 2026-04-03

- Add temp_pass_expires_at to people table (24-hour temp password expiry)
- Rebuild games_index view to return one row per game with aggregated owner
  information (owner_ids array, owner_names string) instead of one row per
  (game, owner) which caused multi-owner games to be silently deduplicated
  by SQLAlchemy's identity map
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "i6j7k8l9m0n1"
down_revision = "h5i6j7k8l9m0"
branch_labels = None
depends_on = None


def upgrade():
    # ── temp_pass_expires_at ───────────────────────────────────────────────────
    op.add_column("people", sa.Column("temp_pass_expires_at", sa.DateTime(), nullable=True))

    # ── games_index view: one row per game, aggregated owners ──────────────────
    op.execute("DROP VIEW IF EXISTS public.games_index;")
    op.execute("""
        CREATE VIEW public.games_index AS
        SELECT
            g.id AS game_id,
            g.name AS game_name,
            g.image_url,
            g.min_players,
            g.max_players,
            g.playtime,
            array_remove(
                array_agg(ob.person_id ORDER BY pe.last_name, pe.first_name),
                NULL
            ) AS owner_ids,
            string_agg(
                pe.first_name || ' ' || pe.last_name,
                ', '
                ORDER BY pe.last_name, pe.first_name
            ) AS owner_names,
            bool_or(COALESCE(pe.owner, false)) AS player_owner
        FROM public.games g
        LEFT JOIN public.ownedby ob ON g.id = ob.game_id
        LEFT JOIN public.people pe ON pe.id = ob.person_id
        GROUP BY g.id, g.name, g.image_url, g.min_players, g.max_players, g.playtime;
    """)


def downgrade():
    op.execute("DROP VIEW IF EXISTS public.games_index;")
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

    op.drop_column("people", "temp_pass_expires_at")
