"""photos on game nights

Revision ID: m0n1o2p3q4r5
Revises: l9m0n1o2p3q4
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "m0n1o2p3q4r5"
down_revision = "l9m0n1o2p3q4"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "game_night_photos",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_night_id", sa.Integer(), nullable=False),
        sa.Column("uploader_id", sa.Integer(), nullable=True),
        sa.Column("path", sa.String(), nullable=False),
        sa.Column("thumb_path", sa.String(), nullable=False),
        sa.Column("caption", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["game_night_id"], ["gamenights.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploader_id"], ["people.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_game_night_photos_game_night_id", "game_night_photos", ["game_night_id"])


def downgrade():
    op.drop_index("ix_game_night_photos_game_night_id", table_name="game_night_photos")
    op.drop_table("game_night_photos")
