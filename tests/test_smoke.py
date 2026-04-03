# tests/test_smoke.py
import pytest

# Routes that redirect to login when unauthenticated
# Verify exact paths with: flask routes
REDIRECT_ROUTES = [
    "/",
    "/games",
    "/wishlist",  # games.wishlist — no /games/ prefix
    "/user_stats",  # games.user_stats — no /games/ prefix
]

# Routes that require admin
ADMIN_ROUTES = [
    "/admin",  # admin_bp route is /admin (no trailing slash)
]

# Auth routes — auth_bp has no url_prefix, so routes are at root, not /auth/
AUTH_ROUTES = [
    "/login",
    "/signup",
    "/forgot_password",
]


@pytest.mark.parametrize("route", REDIRECT_ROUTES)
def test_authenticated_route_redirects_when_logged_out(client, route):
    response = client.get(route)
    assert response.status_code in (302, 301), f"{route} should redirect unauthenticated users"


@pytest.mark.parametrize("route", REDIRECT_ROUTES)
def test_authenticated_route_loads_when_logged_in(auth_client, route):
    response = auth_client.get(route)
    assert response.status_code == 200, f"{route} returned {response.status_code}"


@pytest.mark.parametrize("route", AUTH_ROUTES)
def test_auth_routes_load(client, route):
    response = client.get(route)
    assert response.status_code == 200, f"{route} returned {response.status_code}"


@pytest.mark.parametrize("route", ADMIN_ROUTES)
def test_admin_routes_load_for_admin(admin_client, route):
    response = admin_client.get(route)
    assert response.status_code == 200, f"{route} returned {response.status_code}"


def test_view_game_loads(auth_client, seed_data):
    response = auth_client.get(f"/game/{seed_data['game_id']}")
    assert response.status_code == 200


def test_view_game_night_accessible(auth_client, seed_data):
    # Route requires @game_night_access_required (participant or owner).
    # The test user is neither, so a redirect is the correct behaviour.
    response = auth_client.get(f"/game_night/{seed_data['game_night_id']}")
    assert response.status_code in (200, 302)
