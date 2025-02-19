import logging
from flask import Flask
from flask_session import Session

# Import Config & Extensions
from app.config import Config
from app.extensions import db, bcrypt, mail, login_manager


def init_extensions(app):
    """Initialize Flask extensions."""
    Session(app)
    db.init_app(app)
    bcrypt.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)


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
    app.register_blueprint(blueprints.test_bp)


def setup_logging():
    """Configure logging."""
    logging.basicConfig(level=logging.DEBUG)


def setup_database(app):
    """Set up the database and create tables if necessary."""
    from app.models import Person  # Lazy import

    with app.app_context():
        db.create_all()  # Avoid in production; use migrations instead

    @login_manager.user_loader
    def load_user(user_id):
        return Person.query.get(int(user_id))


def start_schedulers():
    """Start the background scheduler for reminders."""
    from app.services.reminders_services import start_scheduler
    start_scheduler()


def create_app():
    """Factory function to create a Flask app instance."""
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize components
    setup_logging()
    init_extensions(app)
    setup_database(app)
    register_blueprints(app)
    start_schedulers()

    return app