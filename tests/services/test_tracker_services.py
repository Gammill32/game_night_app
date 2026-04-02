def test_tracker_models_importable():
    from app.models import TrackerSession, TrackerField, TrackerTeam, TrackerValue
    assert TrackerSession.__tablename__ == "tracker_sessions"
    assert TrackerField.__tablename__ == "tracker_fields"
    assert TrackerTeam.__tablename__ == "tracker_teams"
    assert TrackerValue.__tablename__ == "tracker_values"
