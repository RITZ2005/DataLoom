"""
Logging utilities — extracted from hybrid_chat_system.py.

Provides colored console output, rotating file handler, and
helper functions for exception logging and user-facing error messages.
"""
from __future__ import annotations

import logging
import sys
import traceback
import warnings

from logging.handlers import RotatingFileHandler

# ---------------------------------------------------------------------------
# Suppress noisy warnings from LangChain / Pandas
# ---------------------------------------------------------------------------
warnings.filterwarnings("ignore", category=UserWarning, module="langchain_experimental")
warnings.filterwarnings("ignore", category=UserWarning, module="pandas")

# ---------------------------------------------------------------------------
# Colored console formatter
# ---------------------------------------------------------------------------

class _ColoredFormatter(logging.Formatter):
    """ANSI-colored log formatter for console output."""
    COLORS = {
        logging.DEBUG:    "\033[36m",   # Cyan
        logging.INFO:     "\033[32m",   # Green
        logging.WARNING:  "\033[33m",   # Yellow
        logging.ERROR:    "\033[31m",   # Red
        logging.CRITICAL: "\033[1;31m", # Bold Red
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)

# ---------------------------------------------------------------------------
# Handler setup
# ---------------------------------------------------------------------------
_log_format = "%(asctime)s - %(name)s - %(levelname)s - [%(funcName)s] %(message)s"

# Console handler with colors
_console_handler = logging.StreamHandler(sys.stdout)
_console_handler.setFormatter(_ColoredFormatter(_log_format))

# File handler with rotation (10 MB per file, keep 5 backups)
_file_handler = RotatingFileHandler(
    'production_system.log', maxBytes=10 * 1024 * 1024, backupCount=5, encoding='utf-8'
)
_file_handler.setFormatter(logging.Formatter(_log_format))

logging.basicConfig(level=logging.INFO, handlers=[_console_handler, _file_handler])

# Canonical logger for the hybrid system
logger = logging.getLogger("HybridSystem")


# ---------------------------------------------------------------------------
# Exception logging & user-facing messages
# ---------------------------------------------------------------------------

def log_full_exception(exc: Exception, context: str = "") -> None:
    """Log the full exception with traceback in a single log call."""
    try:
        tb = traceback.format_exc()
    except Exception:
        tb = "(traceback unavailable)"
    prefix = f"{context} - " if context else ""
    logger.error("%sException: %s\nTraceback:\n%s", prefix, exc, tb)


def user_facing_error_message(exc: Exception) -> str:
    """Return a sanitized, user-friendly error message for common exception types.

    Do NOT expose stack traces or developer details.
    """
    # Network / external service errors
    try:
        import requests as _requests
        if isinstance(exc, _requests.exceptions.RequestException):
            return "Network error: failed to reach an external service. Please check your network or try again later."
    except Exception:
        pass

    # Database errors (psycopg2)
    try:
        import psycopg2 as _psycopg2
        if isinstance(exc, _psycopg2.OperationalError):
            return "Database connection error. Please verify the database server is reachable."
        if isinstance(exc, _psycopg2.DatabaseError):
            return "A database error occurred while processing your request."
    except Exception:
        pass

    # Redis errors
    try:
        import redis as _redis
        if isinstance(exc, _redis.RedisError):
            return "Cache service error. Some features may be temporarily unavailable."
    except Exception:
        pass

    # Generic fallback message
    return "An internal server error occurred. Please try again later or contact support."


__all__ = [
    "log_full_exception",
    "user_facing_error_message",
    "logger",
    "_ColoredFormatter",
]
