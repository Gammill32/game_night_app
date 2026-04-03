"""add FK indexes and missing unique constraints

Revision ID: g4h5i6j7k8l9
Revises: f3a4b5c6d7e8
Create Date: 2026-04-03

PostgreSQL does not auto-index FK columns. Every FK lookup without an index
results in a sequential scan as the table grows. This migration adds the
missing indexes for all high-traffic FK columns and adds unique constraints
that enforce business rules the application relies on.
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "g4h5i6j7k8l9"
down_revision = "f3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade():
    # ── players ────────────────────────────────────────────────────────────────
    op.create_index("ix_players_game_night_id", "players", ["game_night_id"])
    op.create_index("ix_players_people_id", "players", ["people_id"])

    # ── results ────────────────────────────────────────────────────────────────
    op.create_index("ix_results_game_night_game_id", "results", ["game_night_game_id"])
    op.create_index("ix_results_player_id", "results", ["player_id"])

    # ── gamenightgames ─────────────────────────────────────────────────────────
    op.create_index("ix_gamenightgames_game_night_id", "gamenightgames", ["game_night_id"])
    op.create_index("ix_gamenightgames_game_id", "gamenightgames", ["game_id"])

    # ── game_nominations ───────────────────────────────────────────────────────
    op.create_index("ix_game_nominations_game_night_id", "game_nominations", ["game_night_id"])
    op.create_index("ix_game_nominations_player_id", "game_nominations", ["player_id"])
    op.create_index("ix_game_nominations_game_id", "game_nominations", ["game_id"])

    # ── game_votes ─────────────────────────────────────────────────────────────
    op.create_index("ix_game_votes_game_night_id", "game_votes", ["game_night_id"])
    op.create_index("ix_game_votes_player_id", "game_votes", ["player_id"])
    op.create_index("ix_game_votes_game_id", "game_votes", ["game_id"])

    # ── ownedby ────────────────────────────────────────────────────────────────
    op.create_index("ix_ownedby_game_id", "ownedby", ["game_id"])
    op.create_index("ix_ownedby_person_id", "ownedby", ["person_id"])

    # ── game_ratings ───────────────────────────────────────────────────────────
    op.create_index("ix_game_ratings_game_id", "game_ratings", ["game_id"])
    op.create_index("ix_game_ratings_person_id", "game_ratings", ["person_id"])

    # ── poll_options ───────────────────────────────────────────────────────────
    op.create_index("ix_poll_options_poll_id", "poll_options", ["poll_id"])

    # ── poll_responses ─────────────────────────────────────────────────────────
    op.create_index("ix_poll_responses_poll_id", "poll_responses", ["poll_id"])
    op.create_index("ix_poll_responses_option_id", "poll_responses", ["option_id"])
    op.create_index("ix_poll_responses_person_id", "poll_responses", ["person_id"])

    # ── person_badges ──────────────────────────────────────────────────────────
    op.create_index("ix_person_badges_person_id", "person_badges", ["person_id"])
    op.create_index("ix_person_badges_game_night_id", "person_badges", ["game_night_id"])

    # ── tracker ────────────────────────────────────────────────────────────────
    op.create_index("ix_tracker_fields_session_id", "tracker_fields", ["tracker_session_id"])
    op.create_index("ix_tracker_teams_session_id", "tracker_teams", ["tracker_session_id"])

    # ── unique constraints ─────────────────────────────────────────────────────
    # ownedby: a person can own a game only once
    op.create_unique_constraint("uq_ownedby_game_person", "ownedby", ["game_id", "person_id"])
    # game_nominations: one nomination per player per night
    op.create_unique_constraint(
        "uq_game_nominations_night_player", "game_nominations", ["game_night_id", "player_id"]
    )
    # game_ratings: one rating per person per game
    op.create_unique_constraint(
        "uq_game_ratings_game_person", "game_ratings", ["game_id", "person_id"]
    )


def downgrade():
    op.drop_constraint("uq_game_ratings_game_person", "game_ratings", type_="unique")
    op.drop_constraint("uq_game_nominations_night_player", "game_nominations", type_="unique")
    op.drop_constraint("uq_ownedby_game_person", "ownedby", type_="unique")

    op.drop_index("ix_tracker_teams_session_id", table_name="tracker_teams")
    op.drop_index("ix_tracker_fields_session_id", table_name="tracker_fields")
    op.drop_index("ix_person_badges_game_night_id", table_name="person_badges")
    op.drop_index("ix_person_badges_person_id", table_name="person_badges")
    op.drop_index("ix_poll_responses_person_id", table_name="poll_responses")
    op.drop_index("ix_poll_responses_option_id", table_name="poll_responses")
    op.drop_index("ix_poll_responses_poll_id", table_name="poll_responses")
    op.drop_index("ix_poll_options_poll_id", table_name="poll_options")
    op.drop_index("ix_game_ratings_person_id", table_name="game_ratings")
    op.drop_index("ix_game_ratings_game_id", table_name="game_ratings")
    op.drop_index("ix_ownedby_person_id", table_name="ownedby")
    op.drop_index("ix_ownedby_game_id", table_name="ownedby")
    op.drop_index("ix_game_votes_game_id", table_name="game_votes")
    op.drop_index("ix_game_votes_player_id", table_name="game_votes")
    op.drop_index("ix_game_votes_game_night_id", table_name="game_votes")
    op.drop_index("ix_game_nominations_game_id", table_name="game_nominations")
    op.drop_index("ix_game_nominations_player_id", table_name="game_nominations")
    op.drop_index("ix_game_nominations_game_night_id", table_name="game_nominations")
    op.drop_index("ix_gamenightgames_game_id", table_name="gamenightgames")
    op.drop_index("ix_gamenightgames_game_night_id", table_name="gamenightgames")
    op.drop_index("ix_results_player_id", table_name="results")
    op.drop_index("ix_results_game_night_game_id", table_name="results")
    op.drop_index("ix_players_people_id", table_name="players")
    op.drop_index("ix_players_game_night_id", table_name="players")
