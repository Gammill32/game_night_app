"""link polls to game nights

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-04-02

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "e2f3a4b5c6d7"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "polls",
        sa.Column("game_night_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_polls_game_night_id",
        "polls",
        "gamenights",
        ["game_night_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_polls_game_night_id", "polls", type_="foreignkey")
    op.drop_column("polls", "game_night_id")
