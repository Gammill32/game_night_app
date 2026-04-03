"""add_achievement_badges

Revision ID: 8b9f3a3784a3
Revises: c5d6e7f8a9b0
Create Date: 2026-04-01 09:16:15.099059

"""

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "8b9f3a3784a3"
down_revision = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "badges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("icon", sa.String(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )
    op.create_table(
        "person_badges",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=False),
        sa.Column("badge_id", sa.Integer(), nullable=False),
        sa.Column(
            "earned_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False
        ),
        sa.Column("game_night_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["badge_id"], ["badges.id"]),
        sa.ForeignKeyConstraint(["game_night_id"], ["gamenights.id"]),
        sa.ForeignKeyConstraint(["person_id"], ["people.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("person_id", "badge_id", name="uq_person_badge"),
    )

    # Seed badge catalog with raw SQL (no ORM dependency)
    op.execute("""
        INSERT INTO badges (key, name, description, icon) VALUES
        ('first_blood',       'First Blood',       'First time winning any game at a game night',                                '🩸'),
        ('hat_trick',         'Hat Trick',         'Win 3 games in a single game night session',                                 '🎩'),
        ('veteran',           'Veteran',           'Attend 25 game nights total',                                                '🎖️'),
        ('kingslayer',        'Kingslayer',         'Beat the person with the most all-time wins in a head-to-head game',         '👑'),
        ('collector',         'Collector',         'Own 10+ games in the group library',                                         '📦'),
        ('variety_pack',      'Variety Pack',      'Play 10 different unique games across any number of nights',                 '🎲'),
        ('nemesis',           'Nemesis',           'One specific person has beaten you 5+ times in the same game',               '😈'),
        ('redemption_arc',    'Redemption Arc',    'Win a game you have previously lost 3+ times',                               '🔄'),
        ('night_owl',         'Night Owl',         'Attend 5 game nights in a single calendar month',                           '🦉'),
        ('gracious_host',     'Gracious Host',     'Attend every single game night recorded in a calendar year',                 '🏠'),
        ('jack_of_all_trades','Jack of All Trades','Finish in the top half in every game played at a single game night',         '🃏'),
        ('upset_special',     'Upset Special',     'Beat a player whose win rate against you was 80% or more (min 5 games)',     '⚡'),
        ('bench_warmer',      'Bench Warmer',      'Attend a game night but finish last in every game you played',               '🪑'),
        ('grudge_match',      'Grudge Match',      'Play the same game against the same opponent 10+ times',                     '⚔️'),
        ('the_closer',        'The Closer',        'Win the last game at 5 consecutive game nights you attended',                '🔒'),
        ('opening_night',     'Opening Night',     'Play in the very first game night ever recorded',                           '🎬'),
        ('winning_streak',    'Winning Streak',    'Win at least one game at 3 consecutive game nights you attended',            '🔥'),
        ('the_diplomat',      'The Diplomat',      'Play a game night where every game ends in a tie or shared first place',     '🕊️'),
        ('early_bird',        'Early Bird',        'Be the first person to join 10 different game nights',                      '🐦'),
        ('the_rematch',       'The Rematch',       'Play the same game at back-to-back consecutive game nights you attended',    '🔁'),
        ('century_club',      'Century Club',      'Play in 100 total game night games across all nights',                      '💯'),
        ('dark_horse',        'Dark Horse',        'Within one game night: finish last in your first 3 games then win the last', '🐴'),
        ('social_butterfly',  'Social Butterfly',  'Play at least one game with every other registered person',                 '🦋'),
        ('the_oracle',        'The Oracle',        'Nominate a game, have it played, and win it — 5 times',                    '🔮'),
        ('founding_member',   'Founding Member',   'Be one of the first 5 people to ever play a game night',                   '🏛️'),
        ('most_wins',         'Most Wins',         'Once hold the record for most all-time wins across the group',              '🥇')
        ON CONFLICT (key) DO NOTHING;
    """)


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("person_badges")
    op.drop_table("badges")
    # ### end Alembic commands ###
