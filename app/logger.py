"""
Centralized logging module for the LeetCode Stats application.
All application logs are written to a log file instead of the terminal.
Only Flask server-side messages appear in the terminal.

On Vercel (read-only filesystem), logs go to stdout for Vercel's logging dashboard.
"""

import os
import sys
import logging
from logging.handlers import RotatingFileHandler

# Detect Vercel environment (read-only filesystem)
IS_VERCEL = os.environ.get('VERCEL') or os.environ.get('VERCEL_ENV')

# Create logger
logger = logging.getLogger('leetcode_app')
logger.setLevel(logging.DEBUG)

# Prevent propagation to root logger (prevents duplicate console output)
logger.propagate = False

# Create formatter
formatter = logging.Formatter(
    '%(asctime)s | %(levelname)-8s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# Add handler based on environment
if not logger.handlers:
    if IS_VERCEL:
        # Vercel: Use stdout handler (logs appear in Vercel dashboard)
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(logging.INFO)  # Less verbose on Vercel
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    else:
        # Local: Use file handler with rotation
        try:
            LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')
            os.makedirs(LOG_DIR, exist_ok=True)
            LOG_FILE = os.path.join(LOG_DIR, 'app.log')
            
            file_handler = RotatingFileHandler(
                LOG_FILE,
                maxBytes=5 * 1024 * 1024,  # 5MB
                backupCount=5,
                encoding='utf-8'
            )
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)
        except (OSError, PermissionError):
            # Fallback to stdout if file creation fails
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setLevel(logging.INFO)
            stream_handler.setFormatter(formatter)
            logger.addHandler(stream_handler)


def log_info(message: str, tag: str = None):
    """Log an info level message"""
    if tag:
        logger.info(f"[{tag}] {message}")
    else:
        logger.info(message)


def log_warning(message: str, tag: str = None):
    """Log a warning level message"""
    if tag:
        logger.warning(f"[{tag}] {message}")
    else:
        logger.warning(message)


def log_error(message: str, tag: str = None):
    """Log an error level message"""
    if tag:
        logger.error(f"[{tag}] {message}")
    else:
        logger.error(message)


def log_debug(message: str, tag: str = None):
    """Log a debug level message"""
    if tag:
        logger.debug(f"[{tag}] {message}")
    else:
        logger.debug(message)


def log_exception(message: str, tag: str = None):
    """Log an exception with traceback"""
    if tag:
        logger.exception(f"[{tag}] {message}")
    else:
        logger.exception(message)


# Convenience function to replace print() calls
def log(message: str, tag: str = None, level: str = 'info'):
    """
    General log function that can replace print() calls.
    
    Args:
        message: The log message
        tag: Optional tag like 'Scheduler', 'API', etc.
        level: Log level - 'debug', 'info', 'warning', 'error'
    """
    level = level.lower()
    if level == 'debug':
        log_debug(message, tag)
    elif level == 'warning':
        log_warning(message, tag)
    elif level == 'error':
        log_error(message, tag)
    else:
        log_info(message, tag)
