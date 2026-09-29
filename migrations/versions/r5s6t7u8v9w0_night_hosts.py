"""night hosts: people.can_host and gamenights.host_id

Revision ID: r5s6t7u8v9w0
Revises: q4r5s6t7u8v9
Create Date: 2026-09-29

Existing nights were all run by the owner, so they become the host.
"""

import sqlalchemy as sa
from alembic import op

revision = "r5s6t7u8v9w0"
down_revision = "q4r5s6t7u8v9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "people", sa.Column("can_host", sa.Boolean(), nullable=False, server_default="false")
    )
    op.add_column("gamenights", sa.Column("host_id", sa.Integer(), nullable=True))
    op.create_foreign_key(
        "fk_gamenights_host", "gamenights", "people", ["host_id"], ["id"], ondelete="SET NULL"
    )
    op.execute(
        "UPDATE gamenights SET host_id = " "(SELECT id FROM people WHERE owner ORDER BY id LIMIT 1)"
    )


def downgrade():
    op.drop_constraint("fk_gamenights_host", "gamenights", type_="foreignkey")
    op.drop_column("gamenights", "host_id")
    op.drop_column("people", "can_host")
