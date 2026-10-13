"""tracker rows go with the player they belong to

Revision ID: u8c1a2s3c4d5
Revises: t7u8v9w0x1y2
Create Date: 2026-10-09

tracker_values.player_id and tracker_team_players.player_id referenced
players with no ON DELETE, so removing an attendee who had a tracker value or
a team spot failed. Both now cascade. Existing rows are not changed.
"""

from alembic import op

revision = "u8c1a2s3c4d5"
down_revision = "t7u8v9w0x1y2"
branch_labels = None
depends_on = None

FKS = (
    ("tracker_values", "tracker_values_player_id_fkey"),
    ("tracker_team_players", "tracker_team_players_player_id_fkey"),
)


def _replace(ondelete):
    for table, name in FKS:
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(name, table, "players", ["player_id"], ["id"], ondelete=ondelete)


def upgrade():
    _replace("CASCADE")


def downgrade():
    _replace(None)
