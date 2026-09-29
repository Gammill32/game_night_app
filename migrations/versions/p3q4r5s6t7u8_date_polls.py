"""date polls: options carry a date, answers are yes / maybe / no

Revision ID: p3q4r5s6t7u8
Revises: o2p3q4r5s6t7
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "p3q4r5s6t7u8"
down_revision = "o2p3q4r5s6t7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "polls", sa.Column("date_poll", sa.Boolean(), nullable=False, server_default="false")
    )
    op.add_column("polls", sa.Column("picked_game_night_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_polls_picked_game_night",
        "polls",
        "gamenights",
        ["picked_game_night_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.add_column("poll_options", sa.Column("option_date", sa.Date(), nullable=True))
    op.add_column("poll_responses", sa.Column("answer", sa.String(), nullable=True))
    op.create_check_constraint(
        "ck_poll_responses_answer",
        "poll_responses",
        "answer IS NULL OR answer IN ('yes', 'maybe', 'no')",
    )


def downgrade():
    op.drop_constraint("ck_poll_responses_answer", "poll_responses", type_="check")
    op.drop_column("poll_responses", "answer")
    op.drop_column("poll_options", "option_date")
    op.drop_constraint("fk_polls_picked_game_night", "polls", type_="foreignkey")
    op.drop_column("polls", "picked_game_night_id")
    op.drop_column("polls", "date_poll")
