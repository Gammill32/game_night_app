import logging

from flask import Flask

from app.config import Config
from app.extensions import bcrypt, csrf, db, login_manager, mail, migrate, sess


def init_extensions(app):
    """Initialize Flask extensions."""
    sess.init_app(app)
    csrf.init_app(app)
    db.init_app(app)
    bcrypt.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)


def register_blueprints(app):
    """Register Flask blueprints."""
    from app import blueprints

    app.register_blueprint(blueprints.auth_bp)
    app.register_blueprint(blueprints.admin_bp)
    app.register_blueprint(blueprints.game_night_bp)
    app.register_blueprint(blueprints.games_bp)
    app.register_blueprint(blueprints.voting_bp)
    app.register_blueprint(blueprints.reminders_bp)
    app.register_blueprint(blueprints.main_bp)
    app.register_blueprint(blueprints.api_bp)
    app.register_blueprint(blueprints.polls_bp)
    app.register_blueprint(blueprints.tracker_bp)
    # test_bp removed — was a debug artifact registered unconditionally


def setup_logging(debug: bool = False):
    """Configure logging."""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level)


def register_user_loader(app):
    """Register the user_loader callback for Flask-Login."""
    from app.models import Person

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Person, int(user_id))


def start_schedulers(app):
    """Start the background scheduler for reminders.

    In multi-worker Gunicorn deployments each worker calls create_app(), which
    would start N copies of the scheduler and send N reminder emails per run.
    Set ENABLE_SCHEDULER=false on web worker processes and run a dedicated
    single-process scheduler worker (e.g. `gunicorn --workers 1`) or a
    standalone cron process instead.
    """
    import os

    if os.getenv("ENABLE_SCHEDULER", "true").lower() != "true":
        return
    from app.services.reminders_services import start_scheduler

    start_scheduler(app)


def create_app(config_class=None):
    """Factory function to create a Flask app instance."""
    app = Flask(__name__)
    if config_class is None:
        config_class = Config
    app.config.from_object(config_class)

    if not app.debug and app.config.get("SECRET_KEY") == "dev-insecure-default":
        raise RuntimeError(
            "SECRET_KEY must be set to a secure value in production. Set the SECRET_KEY environment variable."
        )

    setup_logging(debug=app.debug)
    init_extensions(app)
    register_user_loader(app)
    register_blueprints(app)
    start_schedulers(app)

    @app.after_request
    def set_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if not app.debug:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    return app
