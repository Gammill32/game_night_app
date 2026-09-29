"""mark availability polls so a night can have other linked polls too

Revision ID: k8l9m0n1o2p3
Revises: j7k8l9m0n1o2
Create Date: 2026-09-29

Until now the only polls with a game_night_id were availability polls, so
those are the ones flagged.
"""

import sqlalchemy as sa
from alembic import op

revision = "k8l9m0n1o2p3"
down_revision = "j7k8l9m0n1o2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "polls", sa.Column("availability", sa.Boolean(), nullable=False, server_default="false")
    )
    op.execute("UPDATE polls SET availability = true WHERE game_night_id IS NOT NULL")


def downgrade():
    op.drop_column("polls", "availability")
