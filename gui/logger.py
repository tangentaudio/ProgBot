"""
Centralized logging configuration for ProgBot.

Usage in any module:
    from logger import get_logger
    log = get_logger(__name__)
    
    log.debug("Detailed debugging info")
    log.info("Normal operational messages") 
    log.warning("Warning conditions")
    log.error("Error conditions")
    log.critical("Critical failures")

Log output goes to /tmp/progbot.log with format:
    [HH:MM:SS.mmm] [LEVEL] [module] message
"""

import logging
import sys
from logging.handlers import RotatingFileHandler

# Log file path - same location we were using before
LOG_FILE_PATH = '/tmp/progbot.log'

# Flag to track if logging has been configured
_logging_configured = False


def setup_logging(level=logging.DEBUG):
    """Configure the root logger with file and optional console handlers.
    
    Call this once at application startup (in kvui.py).
    """
    global _logging_configured
    if _logging_configured:
        return
    
    # Create formatter with timestamp, level, module name
    formatter = logging.Formatter(
        '[%(asctime)s.%(msecs)03d] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # File handler with rotation (5MB max, keep 3 backups)
    file_handler = RotatingFileHandler(
        LOG_FILE_PATH,
        maxBytes=5*1024*1024,  # 5MB
        backupCount=3,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)  # File gets everything
    
    # Console handler for terminal output (INFO and above)
    console_handler = logging.StreamHandler(sys.__stdout__)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)  # Console only gets INFO+
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Suppress noisy third-party loggers
    logging.getLogger('kivy').setLevel(logging.WARNING)
    logging.getLogger('PIL').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    logging.getLogger('pynnex').setLevel(logging.WARNING)
    
    _logging_configured = True
    
    # Log startup
    logger = logging.getLogger('logger')
    logger.info(f"Logging initialized, writing to {LOG_FILE_PATH}")


def get_logger(name: str) -> logging.Logger:
    """Get a logger for the given module name.
    
    Args:
        name: Usually __name__ of the calling module
        
    Returns:
        Configured logger instance
    """
    # Ensure logging is set up
    if not _logging_configured:
        setup_logging()
    
    return logging.getLogger(name)


# Convenience function for quick migration from print statements
def log_info(msg: str):
    """Quick INFO level log - use get_logger() for better practice."""
    get_logger('app').info(msg)


def log_debug(msg: str):
    """Quick DEBUG level log - use get_logger() for better practice."""
    get_logger('app').debug(msg)


def log_warning(msg: str):
    """Quick WARNING level log - use get_logger() for better practice."""
    get_logger('app').warning(msg)


def log_error(msg: str):
    """Quick ERROR level log - use get_logger() for better practice."""
    get_logger('app').error(msg)
