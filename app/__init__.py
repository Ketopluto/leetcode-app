from flask import Flask
from flask_caching import Cache
from app.config import Config
from app.models import db
import os
from datetime import timedelta

app = Flask(__name__)
app.config.from_object(Config)

# Configure session
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# Add Python built-in functions to Jinja2 templates
app.jinja_env.globals.update(min=min, max=max)

# Serverless-friendly database settings
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'pool_size': 1,
    'pool_recycle': 300,
    'pool_pre_ping': True,
    'max_overflow': 0,
}

# Initialize extensions
cache = Cache(app)
db.init_app(app)

# Create upload folder if it doesn't exist
try:
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
except:
    pass  # Read-only filesystem on Vercel

# Initialize database tables (wrapped in try-except for graceful failure)
try:
    with app.app_context():
        db.create_all()
        print("✅ Database initialized")
except Exception as e:
    print(f"⚠️ Database initialization: {e}")

# Disable browser caching
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

from app import routes
