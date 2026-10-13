"""How a refused service call (ServiceError) reaches the user."""

from urllib.parse import urlsplit

from flask import flash, jsonify, redirect, request, url_for

from app.extensions import db
from app.services.errors import ServiceError


def wants_json() -> bool:
    return request.is_json or request.accept_mimetypes.best == "application/json"


def is_htmx_fragment() -> bool:
    """An HTMX request that swaps part of a page (not a boosted full page)."""
    return bool(request.headers.get("HX-Request")) and not request.headers.get("HX-Boosted")


def back_url(default_endpoint: str = "main.index", **values) -> str:
    """The page the request came from (same site only), else a default."""
    ref = request.referrer
    if ref and urlsplit(ref).netloc == request.host:
        return ref
    return url_for(default_endpoint, **values)


def service_error_response(error: ServiceError, redirect_to: str | None = None):
    """JSON {"error": msg} for JSON callers, the bare message for HTMX
    fragments (both with the error's status), otherwise flash + redirect."""
    db.session.rollback()
    if wants_json():
        return jsonify({"error": error.message}), error.status
    if is_htmx_fragment():
        return error.message, error.status
    flash(error.message, "error")
    return redirect(redirect_to or back_url())


def register_error_handlers(app) -> None:
    app.register_error_handler(ServiceError, service_error_response)
