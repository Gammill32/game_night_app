# blueprints/__init__.py

from flask import Blueprint

# Import blueprints to be registered in app.py
from .auth import auth_bp
from .admin import admin_bp
from .game_night import game_night_bp
from .games import games_bp
from .voting import voting_bp
from .reminders import reminders_bp
from .main import main_bp
from .test import test_bp