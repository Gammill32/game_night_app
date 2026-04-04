"""add poll private flag and invitees table

Revision ID: j7k8l9m0n1o2
Revises: i6j7k8l9m0n1
Create Date: 2026-04-03

- Add private boolean column to polls (default False)
- Add poll_invitees join table linking polls to people
"""

import sqlalchemy as sa
from alembic import op

revision = "j7k8l9m0n1o2"
down_revision = "i6j7k8l9m0n1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "polls", sa.Column("private", sa.Boolean(), nullable=False, server_default="false")
    )
    op.create_table(
        "poll_invitees",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("poll_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["poll_id"], ["polls.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("poll_id", "person_id", name="uq_poll_invitees"),
    )
    op.create_index("ix_poll_invitees_poll_id", "poll_invitees", ["poll_id"])


def downgrade():
    op.drop_index("ix_poll_invitees_poll_id", table_name="poll_invitees")
    op.drop_table("poll_invitees")
    op.drop_column("polls", "private")
