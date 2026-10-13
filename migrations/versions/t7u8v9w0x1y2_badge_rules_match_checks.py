"""badge text matches the corrected rules

Revision ID: t7u8v9w0x1y2
Revises: s6t7u8v9w0x1
Create Date: 2026-10-09

Early Bird was "first to join 10 nights", but join order isn't recorded, so it
is now about hosting. Gracious Host is judged once the year is over, and Social
Butterfly only counts active people who have played.
"""

from alembic import op

revision = "t7u8v9w0x1y2"
down_revision = "s6t7u8v9w0x1"
branch_labels = None
depends_on = None

NEW = {
    "early_bird": ("Host with the Most", "Host 10 game nights", "🔑"),
    "gracious_host": (
        "Gracious Host",
        "Attend every game night in a calendar year (awarded once the year is over)",
        "🏠",
    ),
    "social_butterfly": (
        "Social Butterfly",
        "Play at least one game with everyone else who has played",
        "🦋",
    ),
}

OLD = {
    "early_bird": ("Early Bird", "Be the first person to join 10 different game nights", "🐦"),
    "gracious_host": (
        "Gracious Host",
        "Attend every single game night recorded in a calendar year",
        "🏠",
    ),
    "social_butterfly": (
        "Social Butterfly",
        "Play at least one game with every other registered person",
        "🦋",
    ),
}


def _apply(rows):
    for key, (name, description, icon) in rows.items():
        op.get_bind().exec_driver_sql(
            "UPDATE badges SET name = %s, description = %s, icon = %s WHERE key = %s",
            (name, description, icon, key),
        )


def upgrade():
    _apply(NEW)


def downgrade():
    _apply(OLD)
