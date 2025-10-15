import os

class Config:
    # Secret key - read from environment variable or use default for dev
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # HOD password - read from environment variable or use default for dev
    HOD_PASSWORD = os.environ.get('HOD_PASSWORD', 'hod_secure_password_123')
    
    # Database - use persistent disk path on Render, local path in dev
    if os.environ.get('RENDER'):
        # On Render, use /data persistent disk
        SQLALCHEMY_DATABASE_URI = 'sqlite:////data/leetcode_stats.db'
    else:
        # Local development
        BASE_DIR = os.path.abspath(os.path.dirname(__file__))
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, '..', 'leetcode_stats.db')
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    # Upload folder
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), '..', 'uploads')
    ALLOWED_EXTENSIONS = {'xlsx', 'xls'}
    
    # Cache configuration
    CACHE_TYPE = "SimpleCache"
    CACHE_DEFAULT_TIMEOUT = 300
