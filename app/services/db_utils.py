"""Writes that a unique constraint can race.

A "look it up, insert it if it's missing" can lose to a second request (a
double-submit) that inserts the same row in between; the unique constraint
then raises IntegrityError. These helpers make that case a normal outcome.
"""

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from app.extensions import db


def violated_constraint(error: IntegrityError) -> str | None:
    """The name of the constraint a (psycopg2) IntegrityError broke."""
    diag = getattr(error.orig, "diag", None)
    return getattr(diag, "constraint_name", None)


def add_unless_duplicate(obj, *constraints: str) -> bool:
    """Add obj inside a savepoint. False, with nothing added and the rest of
    the transaction intact, if one of these unique constraints says the row
    is already there; any other IntegrityError is raised."""
    try:
        with db.session.begin_nested():
            db.session.add(obj)
    except IntegrityError as e:
        if violated_constraint(e) not in constraints:
            raise
        return False
    return True


def upsert(model, values: dict, constraint: str, update: list[str]) -> None:
    """INSERT ... ON CONFLICT (constraint) DO UPDATE the given columns, as one
    statement, so there's no gap between a lookup and an insert to race.
    ORM objects already loaded for the row are stale until the commit."""
    stmt = pg_insert(model).values(**values)
    db.session.execute(
        stmt.on_conflict_do_update(
            constraint=constraint, set_={col: stmt.excluded[col] for col in update}
        )
    )
