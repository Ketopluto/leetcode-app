"""
Shared pytest fixtures.

Environment variables must be set *before* `app` is imported, since
app/config.py reads them at class-definition time and app/__init__.py
runs DB setup and (conditionally) starts a background scheduler at
import time.
"""
import os
import tempfile

import pytest
import werkzeug

# Flask 2.2.5 (pinned in requirements.txt) reads werkzeug.__version__ when
# building its test client's User-Agent header. Werkzeug >=3.0 dropped that
# attribute in favor of importlib.metadata, so the pinned Flask/Werkzeug
# combo breaks Flask's test client specifically (production/gunicorn/Vercel
# never hit this code path - only `flask.testing`). Patch it back in so the
# test suite runs without forcing a Flask major-version bump.
if not hasattr(werkzeug, "__version__"):
    import importlib.metadata
    werkzeug.__version__ = importlib.metadata.version("werkzeug")

os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("HOD_PASSWORD", "test-admin-password")
# Pretend to be on Vercel so the APScheduler background thread never starts
# during tests, and so /api/stats takes the DB-only fast path (no live
# LeetCode API calls).
os.environ["VERCEL"] = "1"

_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{_db_path}"

from app import app as flask_app, db as _db, cache as _cache, limiter as _limiter  # noqa: E402


@pytest.fixture
def app():
    flask_app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)
    # Login rate limiting and the stats cache are shared, in-memory,
    # module-level state - reset them per test so one test's requests can't
    # affect another's assertions.
    _limiter.reset()
    _cache.clear()
    with flask_app.app_context():
        _db.create_all()
        yield flask_app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def admin_client(client):
    client.post("/admin/login", data={"password": os.environ["HOD_PASSWORD"]})
    return client
