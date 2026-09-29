"""food on game nights: provided / sign-up list / split cost

Revision ID: n1o2p3q4r5s6
Revises: m0n1o2p3q4r5
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from alembic import op

revision = "n1o2p3q4r5s6"
down_revision = "m0n1o2p3q4r5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "gamenights", sa.Column("food_mode", sa.String(), nullable=False, server_default="none")
    )
    op.add_column("gamenights", sa.Column("food_provider_id", sa.Integer(), nullable=True))
    op.add_column("gamenights", sa.Column("food_note", sa.String(), nullable=True))
    op.create_foreign_key(
        "fk_gamenights_food_provider",
        "gamenights",
        "people",
        ["food_provider_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_gamenights_food_mode",
        "gamenights",
        "food_mode IN ('none', 'provided', 'signup', 'split', 'both')",
    )

    op.create_table(
        "food_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_night_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("claimed_by", sa.Integer(), nullable=True),
        sa.Column("added_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["game_night_id"], ["gamenights.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["claimed_by"], ["people.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["added_by"], ["people.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_food_items_game_night_id", "food_items", ["game_night_id"])

    op.create_table(
        "food_expenses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("game_night_id", sa.Integer(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("paid_by", sa.Integer(), nullable=False),
        sa.Column("receipt_path", sa.String(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["game_night_id"], ["gamenights.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["paid_by"], ["people.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["created_by"], ["people.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("amount_cents > 0", name="ck_food_expenses_positive"),
    )
    op.create_index("ix_food_expenses_game_night_id", "food_expenses", ["game_night_id"])
    op.create_index("ix_food_expenses_paid_by", "food_expenses", ["paid_by"])

    op.create_table(
        "food_expense_shares",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("expense_id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("paid", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["expense_id"], ["food_expenses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("expense_id", "person_id", name="uq_food_expense_shares"),
    )
    op.create_index("ix_food_expense_shares_expense_id", "food_expense_shares", ["expense_id"])
    op.create_index("ix_food_expense_shares_person_id", "food_expense_shares", ["person_id"])


def downgrade():
    op.drop_table("food_expense_shares")
    op.drop_table("food_expenses")
    op.drop_table("food_items")
    op.drop_constraint("ck_gamenights_food_mode", "gamenights", type_="check")
    op.drop_constraint("fk_gamenights_food_provider", "gamenights", type_="foreignkey")
    op.drop_column("gamenights", "food_note")
    op.drop_column("gamenights", "food_provider_id")
    op.drop_column("gamenights", "food_mode")
