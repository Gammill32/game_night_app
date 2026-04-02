"""add tracker tables

Revision ID: d1e2f3a4b5c6
Revises: 8b9f3a3784a3
Create Date: 2026-04-02 12:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

revision = 'd1e2f3a4b5c6'
down_revision = '8b9f3a3784a3'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "tracker_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_night_game_id", sa.Integer(), nullable=False),
        sa.Column("mode", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["game_night_game_id"], ["gamenightgames.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("game_night_game_id"),
    )

    op.create_table(
        "tracker_fields",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracker_session_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("starting_value", sa.Integer(), server_default="0"),
        sa.Column("is_score_field", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0"),
        sa.ForeignKeyConstraint(["tracker_session_id"], ["tracker_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # Enforce exactly one score field per session
    op.execute("""
        CREATE UNIQUE INDEX uq_one_score_field
        ON tracker_fields (tracker_session_id)
        WHERE is_score_field = true
    """)

    op.create_table(
        "tracker_teams",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracker_session_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(["tracker_session_id"], ["tracker_sessions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "tracker_team_players",
        sa.Column("team_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["team_id"], ["tracker_teams.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.PrimaryKeyConstraint("team_id", "player_id"),
    )

    op.create_table(
        "tracker_values",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tracker_session_id", sa.Integer(), nullable=False),
        sa.Column("tracker_field_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=True),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("value", sa.Text(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["tracker_session_id"], ["tracker_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tracker_field_id"], ["tracker_fields.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["team_id"], ["tracker_teams.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    # NULLS NOT DISTINCT so global fields (both NULLs) are also deduplicated (PostgreSQL 15+)
    op.execute("""
        ALTER TABLE tracker_values
        ADD CONSTRAINT uq_tracker_value
        UNIQUE NULLS NOT DISTINCT (tracker_field_id, player_id, team_id)
    """)
    op.create_index("ix_tracker_values_field_id", "tracker_values", ["tracker_field_id"])
    op.create_index("ix_tracker_values_player_id", "tracker_values", ["player_id"])


def downgrade():
    op.drop_table("tracker_team_players")
    op.execute("ALTER TABLE tracker_values DROP CONSTRAINT IF EXISTS uq_tracker_value")
    op.drop_table("tracker_values")
    op.drop_table("tracker_teams")
    op.execute("DROP INDEX IF EXISTS uq_one_score_field")
    op.drop_table("tracker_fields")
    op.drop_table("tracker_sessions")
