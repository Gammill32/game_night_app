import logging

from flask import Flask

from app.config import Config
from app.extensions import bcrypt, db, login_manager, mail, migrate, sess


def init_extensions(app):
    """Initialize Flask extensions."""
    sess.init_app(app)
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
    # test_bp removed — was a debug artifact registered unconditionally


def setup_logging():
    """Configure logging."""
    logging.basicConfig(level=logging.DEBUG)


def register_user_loader(app):
    """Register the user_loader callback for Flask-Login."""
    from app.models import Person

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(Person, int(user_id))


def start_schedulers(app):
    """Start the background scheduler for reminders."""
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

    setup_logging()
    init_extensions(app)
    register_user_loader(app)
    register_blueprints(app)
    start_schedulers(app)

    return app
