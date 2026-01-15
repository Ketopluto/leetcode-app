from flask import Flask, Blueprint
from flask_caching import Cache
from app.config import Config
from app.models import db
from app.logger import log_info, log_warning, log_error
import os
from datetime import timedelta

app = Flask(__name__)
app.config.from_object(Config)

# Create a blueprint to serve the assets folder
assets_blueprint = Blueprint('assets', __name__, static_folder='assets', static_url_path='/assets')
app.register_blueprint(assets_blueprint)

# Configure session
app.config['SESSION_PERMANENT'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# Add Python built-in functions to Jinja2 templates
app.jinja_env.globals.update(min=min, max=max)

# Database pool settings - adjust based on environment
IS_SERVERLESS = os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV')
if IS_SERVERLESS:
    # Serverless: use NullPool (no connection pooling)
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'poolclass': __import__('sqlalchemy.pool', fromlist=['NullPool']).NullPool
    }
else:
    # Local/traditional: use connection pooling
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_size': 5,
        'pool_recycle': 300,
        'pool_pre_ping': True,
        'max_overflow': 10,
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
        log_info("Database initialized", tag="OK")
except Exception as e:
    log_warning(f"Database initialization: {e}", tag="WARNING")

# Disable browser caching
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

from app import routes

# Initialize background scheduler for automated tasks
# NOTE: On Vercel (serverless), the scheduler won't work. Use external cron service
# to call POST /api/cron/weekly-reports endpoint instead.
import os
IS_VERCEL = os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV')
IS_RELOADER = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'

if IS_VERCEL:
    log_info("Skipping - Vercel serverless detected. Use /api/cron/weekly-reports endpoint.", tag="Scheduler")
elif not IS_RELOADER:
    # Only init scheduler in main process, not in Flask debug reloader subprocess
    try:
        from app.scheduler import init_scheduler
        init_scheduler(app)
    except Exception as e:
        log_error(f"Failed to initialize: {e}", tag="Scheduler")


