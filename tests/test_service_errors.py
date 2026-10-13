"""ServiceError reaches the user as a flash + redirect, JSON or a bare message."""

from flask import get_flashed_messages

from app.services.errors import ServiceError
from app.services.food_services import FoodError
from app.services.media_services import MediaError
from app.services.night_policy import NightRuleError
from app.utils.errors import service_error_response


def test_domain_errors_are_service_errors_and_value_errors():
    for cls in (FoodError, MediaError, NightRuleError):
        assert issubclass(cls, ServiceError)
        assert issubclass(cls, ValueError)


def test_status_defaults_to_400_and_can_be_set():
    assert ServiceError("no").status == 400
    assert ServiceError("gone", status=404).status == 404
    assert str(ServiceError("no")) == "no"


def test_form_post_flashes_and_redirects_back(app, db):
    with app.test_request_context(
        "/x", method="POST", headers={"Referer": "http://localhost/game_night/3"}
    ):
        resp = service_error_response(ServiceError("Nope."))
        assert resp.status_code == 302
        assert resp.location == "http://localhost/game_night/3"
        assert get_flashed_messages(with_categories=True) == [("error", "Nope.")]


def test_redirect_ignores_another_sites_referrer(app, db):
    with app.test_request_context(
        "/x", method="POST", headers={"Referer": "https://evil.example/"}
    ):
        resp = service_error_response(ServiceError("Nope."))
        assert resp.location == "/"


def test_json_request_gets_error_object_with_status(app, db):
    with app.test_request_context("/x", method="POST", json={"a": 1}):
        body, status = service_error_response(ServiceError("Gone.", status=409))
        assert status == 409
        assert body.get_json() == {"error": "Gone."}


def test_htmx_request_gets_bare_message(app, db):
    with app.test_request_context("/x", method="POST", headers={"HX-Request": "true"}):
        assert service_error_response(ServiceError("Bad value.")) == ("Bad value.", 400)
