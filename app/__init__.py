from flask import Flask
from flask_caching import Cache
from app.config import Config

app = Flask(__name__)
app.config.from_object(Config)
cache = Cache(app)

# Optional: disable browser caching via response headers
@app.after_request
def add_header(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, post-check=0, pre-check=0, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '-1'
    return response

from app import routes
