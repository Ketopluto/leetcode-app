import os
import secrets

# Vercel (and most serverless platforms) run each request in a fresh process,
# so a per-process random SECRET_KEY would invalidate every session constantly.
# We only allow that fallback when explicitly running in local development.
IS_DEV = os.environ.get('FLASK_ENV') == 'development' or os.environ.get('FLASK_DEBUG') == '1'


class Config:
    # Secret key - REQUIRED in production. Generate one with:
    #   python -c "import secrets; print(secrets.token_hex(32))"
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        if IS_DEV:
            SECRET_KEY = secrets.token_hex(32)
        else:
            raise RuntimeError(
                "SECRET_KEY environment variable is not set. Refusing to start "
                "with an insecure default outside of local development."
            )

    # HOD password - REQUIRED in production, no insecure default.
    HOD_PASSWORD = os.environ.get('HOD_PASSWORD')
    if not HOD_PASSWORD:
        if IS_DEV:
            HOD_PASSWORD = secrets.token_hex(8)
            print(f"[DEV ONLY] Generated random HOD_PASSWORD: {HOD_PASSWORD}")
        else:
            raise RuntimeError(
                "HOD_PASSWORD environment variable is not set. Refusing to start "
                "with an insecure default outside of local development."
            )

    # Database configuration
    DATABASE_URL = os.environ.get('DATABASE_URL')
    
    if DATABASE_URL:
        # Production: Use Supabase PostgreSQL
        if DATABASE_URL.startswith('postgres://'):
            DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
        SQLALCHEMY_DATABASE_URI = DATABASE_URL
    else:
        # Development: Use SQLite
        SQLALCHEMY_DATABASE_URI = 'sqlite:////tmp/leetcode_stats.db'
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Upload folder (Vercel uses /tmp for temporary storage)
    UPLOAD_FOLDER = '/tmp/uploads' if os.environ.get('VERCEL') else 'uploads'
    ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
    
    # Cache configuration
    CACHE_TYPE = "SimpleCache"
    CACHE_DEFAULT_TIMEOUT = 300

    # Session cookie hardening
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = not IS_DEV
