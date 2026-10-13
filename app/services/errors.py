"""The one way a service says no.

A service that refuses an operation raises ServiceError (or a subclass) with
a message that's safe to show the user. Routes don't need to catch it: the
handler in app/utils/errors.py rolls back the session, then flashes the
message and redirects back (form posts) or returns it with the status
(JSON / HTMX requests). A blueprint can register its own handler when its
pages should land somewhere more specific (see blueprints/food.py).
"""


class ServiceError(Exception):
    """A service refused the operation; str(e) is safe to show the user."""

    status = 400

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.message = message
        if status is not None:
            self.status = status
