# models.py

from sqlalchemy import ForeignKey, func, Table
from sqlalchemy.orm import relationship
from flask_login import UserMixin
from app.extensions import db


class GameNight(db.Model):
    __tablename__ = 'gamenights'
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, server_default=func.now())
    final = db.Column(db.Boolean, default=False)
    closed = db.Column(db.Boolean, default=False)

    players = relationship('Player', back_populates='game_night', cascade='all, delete-orphan')
    game_night_games = relationship('GameNightGame', back_populates='game_night', cascade='all, delete-orphan')
    nominations = db.relationship('GameNominations', back_populates='game_night', cascade='all, delete-orphan')
    votes = db.relationship('GameVotes', back_populates='game_night', cascade='all, delete-orphan')

class Person(db.Model, UserMixin):
    __tablename__ = 'people'
    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String, nullable=False)
    last_name = db.Column(db.String, nullable=False)
    email = db.Column(db.String, unique=True, nullable=True)
    password = db.Column(db.String, nullable=True)
    created_at = db.Column(db.DateTime, server_default=func.now())
    temp_pass = db.Column(db.Boolean, default=False)
    admin = db.Column(db.Boolean, default=False, nullable=False)
    owner = db.Column(db.Boolean, default=False, nullable=False)

    players = relationship('Player', back_populates='person', cascade='all, delete-orphan')
    owned_games = relationship('OwnedBy', back_populates='person', cascade='all, delete-orphan')
    wishlist_items = db.relationship('Wishlist', back_populates='person', cascade='all, delete-orphan')
    ratings = relationship('GameRatings', back_populates='person', cascade='all, delete-orphan')

    @property
    def is_admin_or_owner(self):
        return self.admin or self.owner

class Game(db.Model):
    __tablename__ = 'games'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    bgg_id = db.Column(db.Integer)
    min_players = db.Column(db.Integer)
    max_players = db.Column(db.Integer)
    playtime = db.Column(db.Integer)
    description = db.Column(db.Text)
    image_url = db.Column(db.String)
    tutorial_url = db.Column(db.String)

    game_night_games = relationship('GameNightGame', back_populates='game', cascade='all, delete-orphan')
    owners = relationship('OwnedBy', back_populates='game', cascade='all, delete-orphan')
    nominations = db.relationship('GameNominations', back_populates='game', cascade='all, delete-orphan')
    votes = db.relationship('GameVotes', back_populates='game', cascade='all, delete-orphan')
    wishlist_entries = db.relationship('Wishlist', back_populates='game', cascade='all, delete-orphan')
    ratings = relationship('GameRatings', back_populates='game', cascade='all, delete-orphan')

class OwnedBy(db.Model):
    __tablename__ = 'ownedby'
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, ForeignKey('games.id'), nullable=False)
    person_id = db.Column(db.Integer, ForeignKey('people.id'), nullable=False)

    game = relationship('Game', back_populates='owners')
    person = relationship('Person', back_populates='owned_games')

class GameRatings(db.Model):
    __tablename__ = 'game_Ratings'
    id = db.Column(db.Integer, primary_key=True)
    game_id = db.Column(db.Integer, ForeignKey('games.id'), nullable=False)
    person_id = db.Column(db.Integer, ForeignKey('people.id'), nullable=False)
    ranking = db.Column(db.Integer)

    game = relationship('Game', back_populates='ratings')
    person = relationship('Person', back_populates='ratings')

class Player(db.Model):
    __tablename__ = 'players'
    id = db.Column(db.Integer, primary_key=True)
    game_night_id = db.Column(db.Integer, ForeignKey('gamenights.id'))
    people_id = db.Column(db.Integer, ForeignKey('people.id'))
    created_at = db.Column(db.DateTime, server_default=func.now())

    game_night = relationship('GameNight', back_populates='players')
    person = relationship('Person', back_populates='players')
    results = relationship('Result', back_populates='player', cascade='all, delete-orphan')
    nominations = db.relationship('GameNominations', back_populates='player', cascade='all, delete-orphan')
    votes = db.relationship('GameVotes', back_populates='player', cascade='all, delete-orphan')

class GameNightGame(db.Model):
    __tablename__ = 'gamenightgames'
    id = db.Column(db.Integer, primary_key=True)
    game_night_id = db.Column(db.Integer, ForeignKey('gamenights.id'), nullable=True)
    game_id = db.Column(db.Integer, ForeignKey('games.id'), nullable=True)
    round = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, server_default=func.now())

    game_night = relationship('GameNight', back_populates='game_night_games')
    game = relationship('Game', back_populates='game_night_games')
    results = relationship('Result', back_populates='game_night_game', cascade='all, delete-orphan')

class Result(db.Model):
    __tablename__ = 'results'
    id = db.Column(db.Integer, primary_key=True)
    game_night_game_id = db.Column(db.Integer, ForeignKey('gamenightgames.id'), nullable=True)
    player_id = db.Column(db.Integer, ForeignKey('players.id'), nullable=True)
    score = db.Column(db.Integer)
    position = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, server_default=func.now())

    game_night_game = relationship('GameNightGame', back_populates='results')
    player = relationship('Player', back_populates='results')

class GameNominations(db.Model):
    __tablename__ = 'game_nominations'

    id = db.Column(db.Integer, primary_key=True)
    game_night_id = db.Column(db.Integer, db.ForeignKey('gamenights.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey('games.id'), nullable=False)

    game_night = db.relationship('GameNight', back_populates='nominations')
    player = db.relationship('Player', back_populates='nominations')
    game = db.relationship('Game', back_populates='nominations')

class GameVotes(db.Model):
    __tablename__ = 'game_votes'

    id = db.Column(db.Integer, primary_key=True)
    game_night_id = db.Column(db.Integer, db.ForeignKey('gamenights.id'), nullable=False)
    player_id = db.Column(db.Integer, db.ForeignKey('players.id'), nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey('games.id'), nullable=False)
    rank = db.Column(db.Integer, nullable=False)

    game_night = db.relationship('GameNight', back_populates='votes')
    player = db.relationship('Player', back_populates='votes')
    game = db.relationship('Game', back_populates='votes')

class Wishlist(db.Model):
    __tablename__ = 'wishlist'
    id = db.Column(db.Integer, primary_key=True)
    person_id = db.Column(db.Integer, db.ForeignKey('people.id'), nullable=False)
    game_id = db.Column(db.Integer, db.ForeignKey('games.id'), nullable=False)

    person = db.relationship('Person', back_populates='wishlist_items')
    game = db.relationship('Game', back_populates='wishlist_entries')

class GamesIndex(db.Model): #SQL View
    __tablename__ = "games_index"
    __table_args__ = {"extend_existing": True}  # Ensures no conflicts

    game_id = db.Column(db.Integer, primary_key=True)
    game_name = db.Column(db.String, nullable=False)
    image_url = db.Column(db.String, nullable=True)
    min_players = db.Column(db.Integer, nullable=False)
    max_players = db.Column(db.Integer, nullable=False)
    playtime = db.Column(db.Integer, nullable=True)
    owner_id = db.Column(db.Integer, nullable=True)
    player_owner = db.Column(db.Boolean, nullable=True)
    user_owns_game = db.Column(db.Boolean, nullable=False)  # Precomputed boolean

class UserRecentFutureGameNight(db.Model): #SQL View
    __tablename__ = "user_recent_future_game_nights"
    id = db.Column(db.Integer, primary_key=True)  # Artificial primary key from row_number()
    game_night_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    final = db.Column(db.Boolean, nullable=False)
    closed = db.Column(db.Boolean, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)

class UserGameNightList(db.Model): #SQL View
    __tablename__ = "user_game_nights_list"
    id = db.Column(db.Integer, primary_key=True)  # Artificial primary key from row_number()
    game_night_id = db.Column(db.Integer, nullable=False)
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    final = db.Column(db.Boolean, nullable=False)
    closed = db.Column(db.Boolean, nullable=False)
    user_id = db.Column(db.Integer, nullable=False)

class AdminRecentFutureGameNight(db.Model): #SQL View
    __tablename__ = "admin_recent_future_game_nights"
    game_night_id = db.Column(db.Integer, primary_key=True)  # Use game_night_id as PK since row_number() isn't used
    date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text, nullable=True)
    final = db.Column(db.Boolean, nullable=False)
    closed = db.Column(db.Boolean, nullable=False)

class AdminGameNightList(db.Model): #SQL View
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