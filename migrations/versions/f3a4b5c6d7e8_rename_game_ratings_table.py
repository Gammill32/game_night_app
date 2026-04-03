"""rename game_Ratings to game_ratings

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-04-03

"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "f3a4b5c6d7e8"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    op.rename_table("game_Ratings", "game_ratings")


def downgrade():
    op.rename_table("game_ratings", "game_Ratings")
