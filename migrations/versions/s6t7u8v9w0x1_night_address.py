"""gamenights.address: a private address, deleted when the night is over

Revision ID: s6t7u8v9w0x1
Revises: r5s6t7u8v9w0
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "s6t7u8v9w0x1"
down_revision = "r5s6t7u8v9w0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("gamenights", sa.Column("address", sa.String(), nullable=True))


def downgrade():
    op.drop_column("gamenights", "address")
