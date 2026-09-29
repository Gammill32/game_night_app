"""people.active: removed people with history are deactivated, not deleted

Revision ID: o2p3q4r5s6t7
Revises: n1o2p3q4r5s6
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "o2p3q4r5s6t7"
down_revision = "n1o2p3q4r5s6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "people", sa.Column("active", sa.Boolean(), nullable=False, server_default="true")
    )


def downgrade():
    op.drop_column("people", "active")
