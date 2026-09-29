# models.py

from flask_login import UserMixin
from sqlalchemy import ForeignKey, func
from sqlalchemy.dialects.postgresql import ARRAY as PG_ARRAY
from sqlalchemy.orm import relationship

from app.extensions import db


class GameNight(db.Model):
    __tablename__ = "gamenights"
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=func.now())
    final = db.Column(db.Boolean, default=False)
    closed = db.Column(db.Boolean, default=False)
    # Food: none / provided (someone has it covered) / signup (who's bringing
    # what) / split (someone buys, everyone chips in) / both (signup + split).
    food_mode = db.Column(db.String, nullable=False, default="none", server_default="none")
    food_provider_id = db.Column(db.Integer, db.ForeignKey("people.id", ondelete="SET NULL"))
    food_note = db.Column(db.String)

    food_provider = relationship("Person", foreign_keys=[food_provider_id])
    food_items = relationship(
        "FoodItem",
        back_populates="game_night",
        cascade="all, delete-orphan",
        order_by="FoodItem.id",
    )
    food_expenses = relationship(
        "FoodExpense",
        back_populates="game_night",
        cascade="all, delete-orphan",
        order_by="FoodExpense.id",
    )
    players = relationship("Player", back_populates="game_night", cascade="all, delete-orphan")
    game_night_games = relationship(
        "GameNightGame", back_populates="game_night", cascade="all, delete-orphan"
    )
    nominations = db.relationship(
        "GameNominations", back_populates="game_night", cascade="all, delete-orphan"
    )
    votes = db.relationship("GameVotes", back_populates="game_night", cascade="all, delete-orphan")
    photos = db.relationship(
        "GameNightPhoto",
        back_populates="game_night",
        cascade="all, delete-orphan",
        order_by="GameNightPhoto.created_at",
    )
    polls = db.relationship(
        "Poll",
        back_populates="game_night",
        order_by="Poll.created_at",
        foreign_keys="Poll.game_night_id",
    )

    @property
    def food_signup(self):
        return self.food_mode in ("signup", "both")

    @property
    def food_split(self):
        return self.food_mode in ("split", "both")

    @property
    def availability_poll(self):
        """The Can Make It / Maybe / Can't Make It poll; its answers are the RSVPs."""
        return next((p for p in self.polls if p.availability), None)


class Person(db.Model, UserMixin):
    __tablename__ = "people"
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String, nullable=False)
    last_name = db.Column(db.String, nullable=False)
    email = db.Column(db.String, unique=True, nullable=True)
    password = db.Column(db.String, nullable=True)
    created_at = db.Column(db.DateTime, server_default=func.now())
    temp_pass = db.Column(db.Boolean, default=False)
    temp_pass_expires_at = db.Column(db.DateTime, nullable=True)
    admin = db.Column(db.Boolean, default=False, nullable=False)
    owner = db.Column(db.Boolean, default=False, nullable=False)
    # Removed people who have history are deactivated instead of deleted, so
    # past results keep their names. They can't log in or be picked.
    active = db.Column(db.Boolean, default=True, nullable=False, server_default="true")

    players = relationship("Player", back_populates="person", cascade="all, delete-orphan")
    owned_games = relationship("OwnedBy", back_populates="person", cascade="all, delete-orphan")
    wishlist_items = db.relationship(
        "Wishlist", back_populates="person", cascade="all, delete-orphan"
    )
    wishlist_votes = db.relationship(
        "WishlistVote", back_populates="person", cascade="all, delete-orphan"
    )
    ratings = relationship("GameRatings", back_populates="person", cascade="all, delete-orphan")
    person_badges = relationship(
        "PersonBadge", back_populates="person", cascade="all, delete-orphan"
    )
    payment_handles = relationship(
        "PaymentHandle",
        back_populates="person",
        cascade="all, delete-orphan",
        order_by="(PaymentHandle.preferred.desc(), PaymentHandle.id)",
    )

    @property
    def is_admin_or_owner(self):
        return self.admin or self.owner

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Game(db.Model):
    __tablename__ = "games"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    bgg_id = db.Column(db.Integer)
    min_players = db.Column(db.Integer)
    max_players = db.Column(db.Integer)
    playtime = db.Column(db.Integer)
    description = db.Column(db.Text)
    image_url = db.Column(db.String)
    tutorial_url = db.Column(db.String)

    game_night_games = relationship(
        "GameNightGame", back_populates="game", cascade="all, delete-orphan"
    )
    owners = relationship("OwnedBy", back_populates="game", cascade="all, delete-orphan")
    nominations = db.relationship(
        "GameNominations", back_populates="game", cascade="all, delete-orphan"
    )
    votes = db.relationship("GameVotes", back_populates="game", cascade="all, delete-orphan")
    wishlist_entries = db.relationship(
        "Wishlist", back_populates="game", cascade="all, delete-orphan"
    )
    wishlist_vote_entries = db.relationship(
        "WishlistVote", back_populates="game", cascade="all, delete-orphan"
    )
    ratings = relationship("GameRatings", back_populates="game", cascade="all, delete-orphan")


class OwnedBy(db.Model):
    __tablename__ = "ownedby"
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, ForeignKey("games.id"), nullable=False)
    person_id = db.Column(db.Integer, ForeignKey("people.id"), nullable=False)

    game = relationship("Game", back_populates="owners")
    person = relationship("Person", back_populates="owned_games")


class GameRatings(db.Model):
    __tablename__ = "game_ratings"
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, ForeignKey("games.id"), nullable=False)
    person_id = db.Column(db.Integer, ForeignKey("people.id"), nullable=False)
    ranking = db.Column(db.Integer)

    game = relationship("Game", back_populates="ratings")
    person = relationship("Person", back_populates="ratings")


class Player(db.Model):
    __tablename__ = "players"
    id = db.Column(db.Integer, primary_key=True)
    game_night_id = db.Column(db.Integer, ForeignKey("gamenights.id"))
    people_id = db.Column(db.Integer, ForeignKey("people.id"))
    created_at = db.Column(db.DateTime, server_default=func.now())

    game_night = relationship("GameNight", back_populates="players")
    person = relationship("Person", back_populates="players")
    results = relationship("Result", back_populates="player", cascade="all, delete-orphan")
    nominations = db.relationship(
        "GameNominations", back_populates="player", cascade="all, delete-orphan"
    )
    votes = db.relationship("GameVotes", back_populates="player", cascade="all, delete-orphan")


class GameNightGame(db.Model):
    __tablename__ = "gamenightgames"
    id = db.Column(db.Integer, primary_key=True)
    game_night_id = db.Column(db.Integer, ForeignKey("gamenights.id"), nullable=True)
    game_id = db.Column(db.Integer, ForeignKey("games.id"), nullable=True)
    round = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, server_default=func.now())

    game_night = relationship("GameNight", back_populates="game_night_games")
    game = relationship("Game", back_populates="game_night_games")
    results = relationship("Result", back_populates="game_night_game", cascade="all, delete-orphan")
    tracker_session = relationship(
        "TrackerSession",
        back_populates="game_night_game",
        uselist=False,
        cascade="all, delete-orphan",
    )


class Result(db.Model):
    __tablename__ = "results"
    id = db.Column(db.Integer, primary_key=True)
    game_night_game_id = db.Column(db.Integer, ForeignKey("gamenightgames.id"), nullable=True)
    player_id = db.Column(db.Integer, ForeignKey("players.id"), nullable=True)
    score = db.Column(db.Integer)
    position = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, server_default=func.now())

    game_night_game = relationship("GameNightGame", back_populates="results")
    player = relationship("Player", back_populates="results")


class GameNominations(db.Model):
    __tablename__ = "game_nominations"

    id = db.Column(db.Integer, primary_key=True)
    game_night_id = db.Column(db.Integer, db.ForeignKey("gamenights.id"), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False)

    game_night = db.relationship("GameNight", back_populates="nominations")
    player = db.relationship("Player", back_populates="nominations")
    game = db.relationship("Game", back_populates="nominations")


class GameVotes(db.Model):
    __tablename__ = "game_votes"

    id = db.Column(db.Integer, primary_key=True)
    game_night_id = db.Column(db.Integer, db.ForeignKey("gamenights.id"), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False)
    rank = db.Column(db.Integer, nullable=False)

    game_night = db.relationship("GameNight", back_populates="votes")
    player = db.relationship("Player", back_populates="votes")
    game = db.relationship("Game", back_populates="votes")


class Wishlist(db.Model):
    __tablename__ = "wishlist"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("people.id"), nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False)

    person = db.relationship("Person", back_populates="wishlist_items")
    game = db.relationship("Game", back_populates="wishlist_entries")


class WishlistVote(db.Model):
    __tablename__ = "wishlist_votes"
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("people.id"), nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey("games.id"), nullable=False)

    person = db.relationship("Person", back_populates="wishlist_votes")
    game = db.relationship("Game", back_populates="wishlist_vote_entries")


class GamesIndex(db.Model):  # SQL View
    __tablename__ = "games_index"
    __table_args__ = {"extend_existing": True}

    game_id = db.Column(db.Integer, primary_key=True)
    game_name = db.Column(db.String, nullable=False)
    image_url = db.Column(db.String, nullable=True)
    min_players = db.Column(db.Integer, nullable=False)
    max_players = db.Column(db.Integer, nullable=False)
    playtime = db.Column(db.Integer, nullable=True)
    owner_ids = db.Column(PG_ARRAY(db.Integer), nullable=True)  # all owner person_ids
    owner_names = db.Column(db.String, nullable=True)  # "Alice Smith, Bob Jones"
    player_owner = db.Column(db.Boolean, nullable=True)


class UserRecentFutureGameNight(db.Model):  # SQL View
    __tablename__ = "user_recent_future_game_nights"
    id = db.Column(db.Integer, primary_key=True)  # Artificial primary key from row_number()
    game_night_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    final = db.Column(db.Boolean, nullable=False)
    closed = db.Column(db.Boolean, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)


class UserGameNightList(db.Model):  # SQL View
    __tablename__ = "user_game_nights_list"
    id = db.Column(db.Integer, primary_key=True)  # Artificial primary key from row_number()
    game_night_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    final = db.Column(db.Boolean, nullable=False)
    closed = db.Column(db.Boolean, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)


class AdminRecentFutureGameNight(db.Model):  # SQL View
    __tablename__ = "admin_recent_future_game_nights"
    game_night_id = db.Column(
        db.Integer, primary_key=True
    )  # Use game_night_id as PK since row_number() isn't used
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    final = db.Column(db.Boolean, nullable=False)
    closed = db.Column(db.Boolean, nullable=False)


class AdminGameNightList(db.Model):  # SQL View
    __tablename__ = "admin_game_nights_list"
    id = db.Column(db.Integer, primary_key=True)  # Artificial primary key from row_number()
    game_night_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    final = db.Column(db.Boolean, nullable=False)
    closed = db.Column(db.Boolean, nullable=False)


class GameNightRankings(db.Model):  # SQL View
    __tablename__ = "game_night_rankings_view"

    id = db.Column(db.Integer, primary_key=True)  # Artificial primary key from row_number()
    game_night_id = db.Column(db.Integer, nullable=False)
    player_id = db.Column(db.Integer, nullable=False)
    position_counts = db.Column(db.ARRAY(db.Integer), nullable=False)  # Array of position counts
    overall_score = db.Column(db.Integer, nullable=False)
    rank = db.Column(db.Integer, nullable=False)


class GameNightGameResults(db.Model):  # SQL View
    __tablename__ = "game_night_game_results"
    __table_args__ = {"extend_existing": True}  # Ensures compatibility

    game_night_game_id = db.Column(db.Integer, primary_key=True)
    game_night_id = db.Column(db.Integer, nullable=False)
    game_id = db.Column(db.Integer, nullable=False)
    round = db.Column(db.Integer, nullable=False)
    game_name = db.Column(db.String, nullable=False)
    game_image_url = db.Column(db.String, nullable=True)
    results = db.Column(db.JSON, nullable=False)


class GameNightNominationsVotes(db.Model):  # SQL View
    __tablename__ = "game_night_nominations_votes"
    __table_args__ = {"extend_existing": True}  # Ensures compatibility

    game_night_id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, primary_key=True)
    game_name = db.Column(db.String, nullable=False)
    image_url = db.Column(db.String, nullable=True)
    total_nominations = db.Column(db.Integer, nullable=False)
    vote_score = db.Column(db.Integer, nullable=False)


import secrets as _secrets  # noqa: E402


class Poll(db.Model):
    __tablename__ = "polls"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("people.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=func.current_timestamp())
    closes_at = db.Column(db.DateTime, nullable=True)
    closed = db.Column(db.Boolean, default=False, nullable=False)
    token = db.Column(db.Text, unique=True, nullable=False)
    multi_select = db.Column(db.Boolean, default=False, nullable=False)
    private = db.Column(db.Boolean, default=False, nullable=False)
    game_night_id = db.Column(db.Integer, db.ForeignKey("gamenights.id"), nullable=True)
    # The night's RSVP poll (created from the night page), as opposed to any
    # other poll that's merely linked to the night.
    availability = db.Column(db.Boolean, default=False, nullable=False, server_default="false")
    # A date poll: one option per date in a range; people answer yes / maybe
    # / no for each date, and an admin picks one to create the game night.
    date_poll = db.Column(db.Boolean, default=False, nullable=False, server_default="false")
    picked_game_night_id = db.Column(
        db.Integer, db.ForeignKey("gamenights.id", ondelete="SET NULL"), nullable=True
    )

    creator = db.relationship("Person", foreign_keys=[created_by])
    game_night = db.relationship("GameNight", back_populates="polls", foreign_keys=[game_night_id])
    picked_game_night = db.relationship("GameNight", foreign_keys=[picked_game_night_id])
    options = db.relationship(
        "PollOption",
        back_populates="poll",
        cascade="all, delete-orphan",
        order_by="PollOption.display_order",
    )
    responses = db.relationship("PollResponse", back_populates="poll", cascade="all, delete-orphan")
    invitees = db.relationship("PollInvitee", back_populates="poll", cascade="all, delete-orphan")

    @staticmethod
    def generate_token() -> str:
        return _secrets.token_urlsafe(16)


class PollOption(db.Model):
    __tablename__ = "poll_options"

    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey("polls.id"), nullable=False)
    label = db.Column(db.Text, nullable=False)
    display_order = db.Column(db.Integer, default=0, nullable=False)
    option_date = db.Column(db.Date, nullable=True)  # date polls only

    poll = db.relationship("Poll", back_populates="options")
    responses = db.relationship(
        "PollResponse", back_populates="option", cascade="all, delete-orphan"
    )


class PollResponse(db.Model):
    __tablename__ = "poll_responses"

    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey("polls.id"), nullable=False)
    option_id = db.Column(db.Integer, db.ForeignKey("poll_options.id"), nullable=False)
    person_id = db.Column(db.Integer, db.ForeignKey("people.id"), nullable=True)
    respondent_name = db.Column(db.Text, nullable=True)
    answer = db.Column(db.String, nullable=True)  # date polls: yes / maybe / no
    created_at = db.Column(db.DateTime, default=func.current_timestamp())

    poll = db.relationship("Poll", back_populates="responses")
    option = db.relationship("PollOption", back_populates="responses")
    person = db.relationship("Person")


class PollInvitee(db.Model):
    __tablename__ = "poll_invitees"
    __table_args__ = (db.UniqueConstraint("poll_id", "person_id", name="uq_poll_invitees"),)

    id = db.Column(db.Integer, primary_key=True)
    poll_id = db.Column(db.Integer, db.ForeignKey("polls.id", ondelete="CASCADE"), nullable=False)
    person_id = db.Column(
        db.Integer, db.ForeignKey("people.id", ondelete="CASCADE"), nullable=False
    )

    poll = db.relationship("Poll", back_populates="invitees")
    person = db.relationship("Person")


class Badge(db.Model):
    __tablename__ = "badges"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String, unique=True, nullable=False)
    name = db.Column(db.String, nullable=False)
    description = db.Column(db.Text, nullable=False)
    icon = db.Column(db.String, nullable=False)

    person_badges = relationship("PersonBadge", back_populates="badge")


class PersonBadge(db.Model):
    __tablename__ = "person_badges"
    __table_args__ = (db.UniqueConstraint("person_id", "badge_id", name="uq_person_badge"),)

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey("people.id"), nullable=False)
    badge_id = db.Column(db.Integer, db.ForeignKey("badges.id"), nullable=False)
    earned_at = db.Column(db.DateTime, server_default=func.now(), nullable=False)
    game_night_id = db.Column(db.Integer, db.ForeignKey("gamenights.id"), nullable=True)

    person = relationship("Person", back_populates="person_badges")
    badge = relationship("Badge", back_populates="person_badges")
    game_night = relationship("GameNight")


# ---------------------------------------------------------------------------
# Live Tracker
# ---------------------------------------------------------------------------

tracker_team_players = db.Table(
    "tracker_team_players",
    db.Column(
        "team_id",
        db.Integer,
        db.ForeignKey("tracker_teams.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    db.Column("player_id", db.Integer, db.ForeignKey("players.id"), primary_key=True),
)


class TrackerSession(db.Model):
    __tablename__ = "tracker_sessions"

    id = db.Column(db.Integer, primary_key=True)
    game_night_game_id = db.Column(
        db.Integer,
        db.ForeignKey("gamenightgames.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    mode = db.Column(db.String, nullable=False)  # "individual" or "teams"
    status = db.Column(db.String, nullable=False)  # "configuring", "active", "completed"
    created_at = db.Column(db.DateTime, server_default=func.now())

    game_night_game = relationship("GameNightGame", back_populates="tracker_session")
    fields = relationship(
        "TrackerField",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="TrackerField.sort_order",
    )
    teams = relationship("TrackerTeam", back_populates="session", cascade="all, delete-orphan")
    values = relationship("TrackerValue", back_populates="session", cascade="all, delete-orphan")


class TrackerField(db.Model):
    __tablename__ = "tracker_fields"

    id = db.Column(db.Integer, primary_key=True)
    tracker_session_id = db.Column(
        db.Integer, db.ForeignKey("tracker_sessions.id", ondelete="CASCADE"), nullable=False
    )
    type = db.Column(db.String, nullable=False)
    label = db.Column(db.String, nullable=False)
    starting_value = db.Column(db.Integer, server_default="0")
    is_score_field = db.Column(db.Boolean, server_default="false", nullable=False)
    sort_order = db.Column(db.Integer, server_default="0")

    session = relationship("TrackerSession", back_populates="fields")
    values = relationship("TrackerValue", back_populates="field", cascade="all, delete-orphan")


class TrackerTeam(db.Model):
    __tablename__ = "tracker_teams"

    id = db.Column(db.Integer, primary_key=True)
    tracker_session_id = db.Column(
        db.Integer, db.ForeignKey("tracker_sessions.id", ondelete="CASCADE"), nullable=False
    )
    name = db.Column(db.String, nullable=False)

    session = relationship("TrackerSession", back_populates="teams")
    players = relationship("Player", secondary=tracker_team_players)
    values = relationship("TrackerValue", back_populates="team", cascade="all, delete-orphan")


class TrackerValue(db.Model):
    __tablename__ = "tracker_values"

    id = db.Column(db.Integer, primary_key=True)
    tracker_session_id = db.Column(
        db.Integer, db.ForeignKey("tracker_sessions.id", ondelete="CASCADE"), nullable=False
    )
    tracker_field_id = db.Column(
        db.Integer, db.ForeignKey("tracker_fields.id", ondelete="CASCADE"), nullable=False
    )
    player_id = db.Column(db.Integer, db.ForeignKey("players.id"), nullable=True)
    team_id = db.Column(
        db.Integer, db.ForeignKey("tracker_teams.id", ondelete="CASCADE"), nullable=True
    )
    value = db.Column(db.Text, nullable=False, default="0")

    session = relationship("TrackerSession", back_populates="values")
    field = relationship("TrackerField", back_populates="values")
    player = relationship("Player")
    team = relationship("TrackerTeam", back_populates="values")


# ---------------------------------------------------------------------------
# Payment methods
# ---------------------------------------------------------------------------

PAYMENT_KINDS = ("venmo", "cashapp", "zelle", "paypal", "applecash")


class PaymentHandle(db.Model):
    """How someone likes to be paid back (e.g. for split food costs): a Venmo
    username, $Cashtag, Zelle email/phone, PayPal.me username or Apple Cash
    phone. One can be marked preferred."""

    __tablename__ = "payment_handles"
    __table_args__ = (
        db.UniqueConstraint("person_id", "kind", "value", name="uq_payment_handles"),
        db.CheckConstraint(
            "kind IN ('venmo', 'cashapp', 'zelle', 'paypal', 'applecash')",
            name="ck_payment_handles_kind",
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(
        db.Integer, db.ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind = db.Column(db.String, nullable=False)
    value = db.Column(db.String, nullable=False)
    preferred = db.Column(db.Boolean, nullable=False, default=False, server_default="false")
    created_at = db.Column(db.DateTime, server_default=func.now())

    person = relationship("Person", back_populates="payment_handles")


class GameNightPhoto(db.Model):
    """A photo from a game night. The files live under MEDIA_DIR; only people
    who can see the night can load them."""

    __tablename__ = "game_night_photos"

    id = db.Column(db.Integer, primary_key=True)
    game_night_id = db.Column(
        db.Integer, db.ForeignKey("gamenights.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploader_id = db.Column(db.Integer, db.ForeignKey("people.id", ondelete="SET NULL"))
    path = db.Column(db.String, nullable=False)
    thumb_path = db.Column(db.String, nullable=False)
    caption = db.Column(db.String)
    created_at = db.Column(db.DateTime, server_default=func.now())

    game_night = relationship("GameNight", back_populates="photos")
    uploader = relationship("Person")


# ---------------------------------------------------------------------------
# Food
# ---------------------------------------------------------------------------

FOOD_MODES = ("none", "provided", "signup", "split", "both")


class FoodItem(db.Model):
    """A sign-up list entry: something someone is bringing."""

    __tablename__ = "food_items"

    id = db.Column(db.Integer, primary_key=True)
    game_night_id = db.Column(
        db.Integer, db.ForeignKey("gamenights.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = db.Column(db.String, nullable=False)
    claimed_by = db.Column(db.Integer, db.ForeignKey("people.id", ondelete="SET NULL"))
    added_by = db.Column(db.Integer, db.ForeignKey("people.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, server_default=func.now())

    game_night = relationship("GameNight", back_populates="food_items")
    claimer = relationship("Person", foreign_keys=[claimed_by])
    adder = relationship("Person", foreign_keys=[added_by])


class FoodExpense(db.Model):
    """Food someone paid for, split evenly among the people it covers."""

    __tablename__ = "food_expenses"
    __table_args__ = (db.CheckConstraint("amount_cents > 0", name="ck_food_expenses_positive"),)

    id = db.Column(db.Integer, primary_key=True)
    game_night_id = db.Column(
        db.Integer, db.ForeignKey("gamenights.id", ondelete="CASCADE"), nullable=False, index=True
    )
    description = db.Column(db.String, nullable=False)
    amount_cents = db.Column(db.Integer, nullable=False)
    paid_by = db.Column(
        db.Integer, db.ForeignKey("people.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    receipt_path = db.Column(db.String)  # relative to MEDIA_DIR
    created_by = db.Column(db.Integer, db.ForeignKey("people.id", ondelete="SET NULL"))
    created_at = db.Column(db.DateTime, server_default=func.now())

    game_night = relationship("GameNight", back_populates="food_expenses")
    payer = relationship("Person", foreign_keys=[paid_by])
    creator = relationship("Person", foreign_keys=[created_by])
    shares = relationship(
        "FoodExpenseShare",
        back_populates="expense",
        cascade="all, delete-orphan",
        order_by="FoodExpenseShare.person_id",
    )

    @property
    def covered_ids(self):
        return {s.person_id for s in self.shares}


class FoodExpenseShare(db.Model):
    """One person's share of a food expense, and whether they've paid the buyer."""

    __tablename__ = "food_expense_shares"
    __table_args__ = (
        db.UniqueConstraint("expense_id", "person_id", name="uq_food_expense_shares"),
    )

    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(
        db.Integer,
        db.ForeignKey("food_expenses.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    person_id = db.Column(
        db.Integer, db.ForeignKey("people.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amount_cents = db.Column(db.Integer, nullable=False)
    paid = db.Column(db.Boolean, nullable=False, default=False, server_default="false")
    paid_at = db.Column(db.DateTime)

    expense = relationship("FoodExpense", back_populates="shares")
    person = relationship("Person")
