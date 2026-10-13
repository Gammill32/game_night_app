"""Regressions for what a click-through of the merged app turned up: blank
result rows, out-of-range numbers, lost flashes and anchors, pages that only
refused on submit, and the RSVP poll closing with voting."""

import datetime
import uuid

import pytest

from app.extensions import db as _db
from app.models import GameNight, Poll, Result
from tests.conftest import login
from tests.night_world import World


@pytest.fixture()
def w(app, db):
    world = World()
    yield world
    world.cleanup()


def _setup(w, **night):
    host, ann = w.person("Host"), w.person("Ann")
    gn = w.night(host, ann, host=host, **night)
    gng = w.play(gn)
    return host, ann, gn, gng, w.player(gn, host), w.player(gn, ann)


def _log(client, gn, gng, body):
    return client.post(f"/game_night/{gn.id}/log_results/{gng.id}", json=body)


def _entry(player, score, position):
    return {"user_id": player.id, "score": score, "position": position}


# --- log results ---------------------------------------------------------------


def test_blank_entries_save_no_result_row(client, w):
    host, ann, gn, gng, ph, pa = _setup(w)
    login(client, host)
    _log(client, gn, gng, {"a": _entry(ph, 12, 1), "b": _entry(pa, None, None)})
    assert {r.player_id for r in Result.query.filter_by(game_night_game_id=gng.id)} == {ph.id}


def test_clearing_an_entry_removes_its_result(client, w):
    host, ann, gn, gng, ph, pa = _setup(w)
    login(client, host)
    _log(client, gn, gng, {"a": _entry(ph, 12, 1), "b": _entry(pa, 3, 2)})
    _log(client, gn, gng, {"a": _entry(ph, 12, 1), "b": _entry(pa, None, None)})
    assert {r.player_id for r in Result.query.filter_by(game_night_game_id=gng.id)} == {ph.id}


def test_out_of_range_score_is_a_400_not_a_500(client, w):
    host, ann, gn, gng, ph, pa = _setup(w)
    login(client, host)
    resp = _log(client, gn, gng, {"a": _entry(ph, 99999999999, 1)})
    assert resp.status_code == 400
    assert "too big" in resp.get_json()["error"]


@pytest.mark.parametrize("place", [0, -1, 3, 20000000])
def test_places_must_be_within_the_nights_players(client, w, place):
    host, ann, gn, gng, ph, pa = _setup(w)  # two players: places 1..2
    login(client, host)
    resp = _log(client, gn, gng, {"a": _entry(ph, 5, place)})
    assert resp.status_code == 400
    assert Result.query.filter_by(game_night_game_id=gng.id).count() == 0


def test_saved_results_answer_with_where_to_go_and_keep_the_flash(client, w):
    host, ann, gn, gng, ph, pa = _setup(w)
    login(client, host)
    resp = _log(client, gn, gng, {"a": _entry(ph, 12, 1)})
    assert resp.status_code == 200
    assert resp.get_json()["redirect"].endswith(f"/game_night/{gn.id}?saved={gng.id}#played")
    assert "Results logged" in client.get(f"/game_night/{gn.id}").get_data(as_text=True)


# --- tracker save lands on #played -----------------------------------------------


def test_tracker_save_redirects_to_played(client, w):
    from app.services import tracker_services

    host, ann, gn, gng, ph, pa = _setup(w)
    session = tracker_services.get_or_create_configuring_session(gng.id)
    tracker_services.launch_session(
        session.id, mode="individual", teams_data=[], player_ids=[ph.id, pa.id]
    )
    login(client, host)
    resp = client.post(f"/tracker/{session.id}/save")
    assert resp.status_code == 302
    assert resp.location.endswith(f"/game_night/{gn.id}?saved={gng.id}#played")


# --- closing voting ----------------------------------------------------------------


def test_closing_voting_says_so_and_keeps_the_rsvp_poll_open(client, w):
    host, ann, gn, gng, ph, pa = _setup(w)
    rsvp = Poll(
        title="RSVP",
        created_by=host.id,
        token=uuid.uuid4().hex,
        game_night_id=gn.id,
        availability=True,
    )
    _db.session.add(rsvp)
    _db.session.commit()
    w.polls.append(rsvp.id)
    login(client, host)
    resp = client.post(f"/game_night/{gn.id}/toggle/closed", follow_redirects=True)
    assert "Voting closed." in resp.get_data(as_text=True)
    _db.session.refresh(rsvp)
    assert rsvp.closed is False
    resp = client.post(f"/game_night/{gn.id}/toggle/closed", follow_redirects=True)
    assert "Voting reopened." in resp.get_data(as_text=True)


def test_finalize_closes_the_rsvp_poll_and_reopen_opens_it(client, w):
    host, ann, gn, gng, ph, pa = _setup(w, date=datetime.date(2024, 1, 1))
    _db.session.add(Result(game_night_game_id=gng.id, player_id=ph.id, position=1))
    rsvp = Poll(
        title="RSVP",
        created_by=host.id,
        token=uuid.uuid4().hex,
        game_night_id=gn.id,
        availability=True,
    )
    closed_by_hand = Poll(
        title="Snacks?", created_by=host.id, token=uuid.uuid4().hex, game_night_id=gn.id
    )
    closed_by_hand.closed = True
    _db.session.add_all([rsvp, closed_by_hand])
    _db.session.commit()
    login(client, host)
    client.post(f"/game_night/{gn.id}/finalize")
    _db.session.refresh(rsvp)
    assert rsvp.closed is True
    client.post(f"/game_night/{gn.id}/unfinalize")
    _db.session.refresh(rsvp)
    _db.session.refresh(closed_by_hand)
    assert rsvp.closed is False
    assert closed_by_hand.closed is True


@pytest.mark.parametrize("when", ["future", "no_results"])
def test_finalize_refuses_a_night_that_isnt_ready(client, w, when):
    date = datetime.date(2099, 1, 1) if when == "future" else datetime.date(2024, 1, 1)
    host, ann, gn, gng, ph, pa = _setup(w, date=date)
    if when == "future":
        _db.session.add(Result(game_night_game_id=gng.id, player_id=ph.id, position=1))
        _db.session.commit()
    login(client, host)
    resp = client.post(f"/game_night/{gn.id}/finalize", follow_redirects=True)
    assert "once it has happened" in resp.get_data(as_text=True)
    _db.session.refresh(gn)
    assert gn.final is False


# --- pages that can't be used say so up front ---------------------------------------


def test_nominate_page_redirects_when_voting_is_closed(client, w):
    host, ann, gn, gng, ph, pa = _setup(w, closed=True)
    login(client, ann)
    resp = client.get(f"/game_night/{gn.id}/nominate")
    assert resp.status_code == 302 and resp.location.endswith(f"/game_night/{gn.id}")


@pytest.mark.parametrize("path", ["log_results/{gng}", "add_game"])
def test_editing_pages_redirect_on_a_finalized_night(client, w, path):
    host, ann, gn, gng, ph, pa = _setup(w, final=True)
    login(client, host)
    resp = client.get(f"/game_night/{gn.id}/" + path.format(gng=gng.id))
    assert resp.status_code == 302 and resp.location.endswith(f"/game_night/{gn.id}")


def test_new_tracker_on_a_finalized_night_redirects_with_a_message(client, w):
    host, ann, gn, gng, ph, pa = _setup(w, final=True)
    login(client, host)
    resp = client.get(f"/game_night/{gng.id}/tracker/new", follow_redirects=True)
    assert resp.status_code == 200 and "finalized" in resp.get_data(as_text=True)


def test_night_page_marks_each_game_for_the_winner_sweep(client, w):
    host, ann, gn, gng, ph, pa = _setup(w)
    login(client, host)
    assert f'data-gng="{gng.id}"' in client.get(f"/game_night/{gn.id}").get_data(as_text=True)


# --- public recap ---------------------------------------------------------------------


def test_public_recap_leaves_out_the_notes(client, w):
    host, ann, gn, gng, ph, pa = _setup(w, final=True, notes="Gate code 4321")
    client.post("/logout")
    page = client.get(f"/game_night/{gn.id}/recap").get_data(as_text=True)
    assert "Gate code 4321" not in page
    assert _db.session.get(GameNight, gn.id).notes == "Gate code 4321"


# --- background toggles (heart, "I bought it") answer for fetch, not with a redirect ---


def test_background_claim_answers_204_then_400_when_already_owned(client, w):
    host = w.person("Host")
    game = w.game()
    login(client, host)
    headers = {"X-Background": "1"}
    assert client.post(f"/game/{game.id}/claim", headers=headers).status_code == 204
    resp = client.post(f"/game/{game.id}/claim", headers=headers)
    assert resp.status_code == 400 and "already own" in resp.get_data(as_text=True)


def test_background_wishlist_toggle_answers_204(client, w):
    host = w.person("Host")
    game = w.game()
    login(client, host)
    assert (
        client.post(f"/wishlist/toggle/{game.id}", headers={"X-Background": "1"}).status_code == 204
    )


# --- the tracker is locked with the rest of a finalized night ------------------------


def test_finalized_night_refuses_tracker_discard_and_new_fields(w):
    from app.services import tracker_services
    from app.services.night_policy import NightRuleError

    host, ann, gn, gng, ph, pa = _setup(w)
    session = tracker_services.get_or_create_configuring_session(gng.id)
    gn.final = True
    _db.session.commit()
    with pytest.raises(NightRuleError):
        tracker_services.add_field(session.id, type="counter", label="Gold")
    with pytest.raises(NightRuleError):
        tracker_services.discard_session(session.id)


# --- writes that a double-submit can race -------------------------------------------


def test_rating_twice_keeps_one_row_with_the_latest(w):
    from app.models import GameRatings
    from app.services.games_services import update_game_rating

    host = w.person("Host")
    game = w.game()
    assert update_game_rating(game.id, host.id, 4)[0]
    assert update_game_rating(game.id, host.id, 9)[0]
    rows = GameRatings.query.filter_by(game_id=game.id, person_id=host.id).all()
    assert [r.ranking for r in rows] == [9]


def test_tracker_create_returns_the_existing_session_instead_of_crashing(w):
    """A second tab may have started (or launched) this game's tracker first."""
    from app.models import TrackerSession
    from app.services import tracker_services

    host, ann, gn, gng, ph, pa = _setup(w)
    first = tracker_services.get_or_create_configuring_session(gng.id)
    first.status = "active"
    _db.session.commit()
    assert tracker_services.get_or_create_configuring_session(gng.id).id == first.id
    assert TrackerSession.query.filter_by(game_night_game_id=gng.id).count() == 1
