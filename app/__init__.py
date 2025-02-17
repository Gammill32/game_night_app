import logging
from flask import Flask
from flask_session import Session
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# Import Config & Extensions
from app.config import Config
from app.extensions import db, bcrypt, mail, login_manager

def create_app():
    """Factory function to create a Flask app instance."""
    app = Flask(__name__)
    app.config.from_object(Config)

    # Initialize Extensions
    Session(app)
    db.init_app(app)
    bcrypt.init_app(app)
    mail.init_app(app)
    login_manager.init_app(app)

    # Set up logging
    logging.basicConfig(level=logging.DEBUG)

    # Initialize Database
    from app.models import (
        Person, 
        UserRecentFutureGameNight, 
        UserGameNightList,
        AdminGameNightList, 
        AdminRecentFutureGameNight
    )
    from sqlalchemy import Table

    # with app.app_context():
    #     db.create_all()  # Create tables if they don't exist

    #     # Assign SQL views inside the app context
    #     UserRecentFutureGameNight.__table__ = Table(
    #         "user_recent_future_game_nights", db.metadata, autoload_with=db.engine
    #     )
    #     UserGameNightList.__table__ = Table(
    #         "user_game_nights_list", db.metadata, autoload_with=db.engine
    #     )
    #     AdminGameNightList.__table__ = Table(
    #         "admin_game_nights_list", db.metadata, autoload_with=db.engine
    #     )
    #     AdminRecentFutureGameNight.__table__ = Table(
    #         "admin_recent_future_game_nights", db.metadata, autoload_with=db.engine
    #     )
        
    @login_manager.user_loader
    def load_user(user_id):
        return Person.query.get(int(user_id))

    # Register Blueprints
    from app.blueprints import auth_bp, admin_bp, game_night_bp, games_bp, voting_bp, reminders_bp, main_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(game_night_bp)
    app.register_blueprint(games_bp)
    app.register_blueprint(voting_bp)
    app.register_blueprint(reminders_bp)
    app.register_blueprint(main_bp)

    # Scheduler for reminders
    from app.blueprints.reminders import check_and_send_reminders
    dallas_timezone = pytz.timezone("America/Chicago")
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        func=check_and_send_reminders,
        trigger=CronTrigger(hour=10, minute=0, timezone=dallas_timezone),
        id="daily_game_night_reminder",
        replace_existing=True
    )
    scheduler.start()

    return app