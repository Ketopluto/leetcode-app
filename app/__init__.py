from flask import Flask
from flask_caching import Cache
from app.config import Config
from app.models import db
import os
from datetime import timedelta

app = Flask(__name__)
app.config.from_object(Config)

# Configure session to be permanent (stays logged in until logout)
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)  # Session lasts 7 days

# Initialize extensions
cache = Cache(app)
db.init_app(app)

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Create database directory if it doesn't exist (for Render persistent disk)
db_dir = os.path.dirname(app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', ''))
os.makedirs(db_dir, exist_ok=True)

# Initialize database tables ONLY if database doesn't exist
with app.app_context():
    db_path = app.config['SQLALCHEMY_DATABASE_URI'].replace('sqlite:///', '')
    
    if not os.path.exists(db_path):
        # Database doesn't exist - create tables
        db.create_all()
        print(f"✅ New database created at: {db_path}")
    else:
        # Database exists - just ensure all tables are present (safe operation)
        db.create_all()  # This won't delete existing data
        print(f"✅ Using existing database at: {db_path}")

# Optional: disable browser caching via response headers
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

app.jinja_env.globals.update(min=min, max=max)

from app import routes
