import os

class Config:
    # Secret key
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # HOD password
    HOD_PASSWORD = os.environ.get('HOD_PASSWORD', 'hod_secure_password_123')
    
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
