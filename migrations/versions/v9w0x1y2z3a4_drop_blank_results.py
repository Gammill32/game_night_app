"""delete results with neither a score nor a place

Revision ID: v9w0x1y2z3a4
Revises: u8v9w0auth01
Create Date: 2026-10-10

The log-results page used to save a row for every attendee, including the ones
left blank because they didn't play that game. Those rows carry nothing, but
they counted as having played: in recap player counts and in badge checks
(Social Butterfly, Century Club, ...). The page no longer saves them; this
removes the old ones. Attendance itself lives in players and is untouched.
Downgrade can't bring them back (there's nothing in them to restore).
"""

from alembic import op

revision = "v9w0x1y2z3a4"
down_revision = "u8v9w0auth01"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("DELETE FROM results WHERE score IS NULL AND position IS NULL")


def downgrade():
    pass
