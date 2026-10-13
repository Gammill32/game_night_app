"""people.session_token and the auth_throttle table

Revision ID: u8v9w0auth01
Revises: u8c4r5a6n7k8
Create Date: 2026-10-09

- people.session_token: part of the Flask-Login session id ("<id>:<token>").
  Changing it (password change or reset, deactivation) logs out every other
  session. NULL until first set, so sessions from before this keep working.
- auth_throttle: one row per failed sign-in or reset request, keyed by
  address or email digest, so /login and /forgot_password can be slowed down
  across all workers.
"""

import sqlalchemy as sa
from alembic import op

revision = "u8v9w0auth01"
down_revision = "u8c4r5a6n7k8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("people", sa.Column("session_token", sa.String(length=64), nullable=True))
    op.create_table(
        "auth_throttle",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_auth_throttle_key_created_at", "auth_throttle", ["key", "created_at"])
    op.create_index("ix_auth_throttle_created_at", "auth_throttle", ["created_at"])


def downgrade():
    op.drop_index("ix_auth_throttle_created_at", table_name="auth_throttle")
    op.drop_index("ix_auth_throttle_key_created_at", table_name="auth_throttle")
    op.drop_table("auth_throttle")
    op.drop_column("people", "session_token")
