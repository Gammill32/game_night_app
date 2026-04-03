def test_user_stats_page_renders_earned_badges(auth_client, app, db):
    """user_stats page must render actual badge data for the current user."""
    import uuid

    from app.extensions import db as _db
    from app.models import Badge, Person, PersonBadge

    user = Person.query.filter_by(email="test@example.com").first()
    assert user is not None, "Test user not found — check conftest for auth user email"

    # Guard: remove any stale PersonBadge rows for this user left by a failed
    # prior run so that auth_client teardown (which deletes the person) won't
    # hit a FK violation.
    PersonBadge.query.filter_by(person_id=user.id).delete()
    _db.session.flush()

    badge = Badge(
        key=f"test_stats_{uuid.uuid4().hex[:6]}",
        name="Stats Test Badge",
        description="test",
        icon="T",
    )
    _db.session.add(badge)
    _db.session.flush()

    pb = PersonBadge(person_id=user.id, badge_id=badge.id)
    _db.session.add(pb)
    _db.session.commit()

    resp = auth_client.get("/user_stats")
    assert resp.status_code == 200
    assert b"Stats Test Badge" in resp.data

    PersonBadge.query.filter_by(badge_id=badge.id).delete()
    _db.session.delete(badge)
    _db.session.commit()
