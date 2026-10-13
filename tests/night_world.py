"""A small builder for night-rule tests: people, nights, games, results.

Everything it makes is deleted by cleanup(), so a failing assertion doesn't
leak rows into the session-scoped test database.
"""

import datetime
import uuid

from app.extensions import bcrypt
from app.extensions import db as _db
from app.models import (
    Game,
    GameNight,
    GameNightGame,
    Person,
    PersonBadge,
    Player,
    Poll,
    Result,
)


class World:
    def __init__(self):
        self.people, self.nights, self.games, self.polls = [], [], [], []

    def person(self, first="P", admin=False):
        p = Person(
            first_name=first,
            last_name="T",
            email=f"rules_{uuid.uuid4().hex[:8]}@test.invalid",
            password=bcrypt.generate_password_hash("password", rounds=4).decode("utf-8"),
            admin=admin,
        )
        _db.session.add(p)
        _db.session.commit()
        self.people.append(p.id)
        return p

    def game(self):
        g = Game(name=f"Rules {uuid.uuid4().hex[:8]}")
        _db.session.add(g)
        _db.session.commit()
        self.games.append(g.id)
        return g

    def night(self, *people, host=None, date=None, **fields):
        gn = GameNight(
            date=date or datetime.date(2030, 1, 1), host_id=host.id if host else None, **fields
        )
        _db.session.add(gn)
        _db.session.flush()
        for p in people:
            _db.session.add(Player(game_night_id=gn.id, people_id=p.id))
        _db.session.commit()
        self.nights.append(gn.id)
        return gn

    def player(self, gn, person):
        return Player.query.filter_by(game_night_id=gn.id, people_id=person.id).one()

    def play(self, gn, game=None, positions=None, round=1):
        """positions: {person: position}; returns the GameNightGame."""
        gng = GameNightGame(game_night_id=gn.id, game_id=(game or self.game()).id, round=round)
        _db.session.add(gng)
        _db.session.flush()
        for p, pos in (positions or {}).items():
            _db.session.add(
                Result(
                    game_night_game_id=gng.id,
                    player_id=self.player(gn, p).id,
                    position=pos,
                    score=10 - pos,
                )
            )
        _db.session.commit()
        return gng

    def cleanup(self):
        _db.session.rollback()
        for pid in self.polls:
            poll = _db.session.get(Poll, pid)
            if poll is not None:
                _db.session.delete(poll)
        for gid in self.nights:
            gn = _db.session.get(GameNight, gid)
            if gn is not None:
                PersonBadge.query.filter_by(game_night_id=gid).delete()
                for poll in gn.polls:
                    _db.session.delete(poll)
                _db.session.delete(gn)  # ORM cascade: players, games, results, votes
        _db.session.flush()
        for pid in self.people:
            p = _db.session.get(Person, pid)
            if p is not None:
                for poll in Poll.query.filter_by(created_by=pid):
                    _db.session.delete(poll)
                _db.session.flush()
                _db.session.delete(p)
        for gid in self.games:
            g = _db.session.get(Game, gid)
            if g is not None:
                _db.session.delete(g)
        _db.session.commit()
