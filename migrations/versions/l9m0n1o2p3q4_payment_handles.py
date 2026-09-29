"""payment handles on people

Revision ID: l9m0n1o2p3q4
Revises: k8l9m0n1o2p3
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "l9m0n1o2p3q4"
down_revision = "k8l9m0n1o2p3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "payment_handles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("preferred", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "kind", "value", name="uq_payment_handles"),
        sa.CheckConstraint(
            "kind IN ('venmo', 'cashapp', 'zelle', 'paypal', 'applecash')",
            name="ck_payment_handles_kind",
        ),
    )
    op.create_index("ix_payment_handles_person_id", "payment_handles", ["person_id"])


def downgrade():
    op.drop_index("ix_payment_handles_person_id", table_name="payment_handles")
    op.drop_table("payment_handles")
