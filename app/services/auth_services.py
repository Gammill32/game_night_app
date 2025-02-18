from app.models import db, Person
from app.extensions import bcrypt
from sqlalchemy import func
import secrets
from app.utils import send_email

def login(email, password):
    """Authenticate user and return success status, message, and user instance."""
    user = Person.query.filter(func.lower(Person.email) == email).first()
    if user and bcrypt.check_password_hash(user.password, password):
        return True, "Login successful.", user
    return False, "Invalid email or password.", None

def signup(first_name, last_name, email, password):
    """Register a new user."""
    existing_user = Person.query.filter_by(email=email).first()
    if existing_user:
        return False, "An account with this email already exists."
    
    hashed_password = bcrypt.generate_password_hash(password)
    new_user = Person(first_name=first_name, last_name=last_name, email=email, password=hashed_password)
    db.session.add(new_user)
    db.session.commit()
    
    return True, "Account created successfully! Please log in."

def forgot_password(email):
    """Generate a temporary password and send it to the user's email."""
    user = Person.query.filter_by(email=email).first()
    if not user:
        return False, "Email not found."
    
    temp_password = secrets.token_urlsafe(8)
    user.password = bcrypt.generate_password_hash(temp_password).decode('utf-8')
    user.temp_pass = True
    db.session.commit()
    
    subject = "Password Reset for Game Night App"
    html_body = f"""
    <p>Hello {user.first_name},</p>
    <p>Your temporary password is: <strong>{temp_password}</strong></p>
    <p>Please log in and change your password.</p>
    """
    send_email(user.email, subject, html_body)
    
    return True, "A temporary password has been sent to your email."

def update_password(user, current_password, new_password, confirm_password):
    """Update user password if the current password is correct."""
    if not bcrypt.check_password_hash(user.password, current_password):
        return False, "Current password is incorrect."
    
    if new_password != confirm_password:
        return False, "New passwords do not match."
    
    user.password = bcrypt.generate_password_hash(new_password)
    user.temp_pass = False
    db.session.commit()
    
    return True, "Password updated successfully."
