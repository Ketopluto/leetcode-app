from flask import Flask
from flask_caching import Cache
from app.config import Config
from app.models import db
import os
from datetime import timedelta

app = Flask(__name__)
app.config.from_object(Config)

# Configure session to be permanent
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# Add Python built-in functions to Jinja2 templates
app.jinja_env.globals.update(min=min, max=max)

# Initialize extensions
cache = Cache(app)
db.init_app(app)

# Create upload folder if it doesn't exist
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Initialize database tables
with app.app_context():
    db.create_all()
    print(f"✅ Database initialized: {app.config['SQLALCHEMY_DATABASE_URI'][:30]}...")

# Disable browser caching
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

from app import routes
