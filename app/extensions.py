from apscheduler.schedulers.background import BackgroundScheduler
from flask_bcrypt import Bcrypt
from flask_login import LoginManager
from flask_mail import Mail
from flask_migrate import Migrate
from flask_session import Session
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()
migrate = Migrate()
bcrypt = Bcrypt()
mail = Mail()
sess = Session()

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please log in to access this page."
scheduler = BackgroundScheduler()
