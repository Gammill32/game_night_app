"""remove votes for games that are no longer nominated

Revision ID: q4r5s6t7u8v9
Revises: p3q4r5s6t7u8
Create Date: 2026-09-29

Before this release, changing your nomination cleared only your own votes,
so other people's votes for the replaced game stayed behind and the
standings view (which lists any game with votes) showed it as nominated.
Nominating and removing players now clean these up; this clears the ones
already there.
"""

from alembic import op

revision = "q4r5s6t7u8v9"
down_revision = "p3q4r5s6t7u8"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        DELETE FROM game_votes gv
        WHERE NOT EXISTS (
            SELECT 1 FROM game_nominations n
            WHERE n.game_night_id = gv.game_night_id AND n.game_id = gv.game_id
        )
        """
    )


def downgrade():
    pass  # the deleted votes counted for nothing
