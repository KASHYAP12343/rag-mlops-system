# src/utils/logger.py
"""
Logger configuration module.

This module sets up a centralized logging system using loguru.
Loguru is chosen because it's beginner-friendly and doesn't require
complex handler configuration like Python's built-in logging.

Features:
- Logs to both console and file
- Color-coded output for easy reading
- Automatic log rotation (prevents huge log files)
- Includes timing information for performance tracking
"""

import sys
from pathlib import Path
from loguru import logger as loguru_logger
import logging
from pythonjsonlogger import jsonlogger

def setup_logger(
    log_level: str = "INFO",
    log_file: str = "./logs/app.log",
    retention_days: int = 7
) -> None:
    """
    Configure the application logger.
    
    This function removes default loguru handlers and adds our custom ones.
    It's called once at application startup.
    
    Args:
        log_level: Minimum level to log ('DEBUG', 'INFO', 'WARNING', 'ERROR')
        log_file: Path to the log file (will be created if doesn't exist)
        retention_days: How many days to keep old log files
    """
    
    # Remove default loguru handler to avoid duplicate logs
    loguru_logger.remove()
    
    # Ensure log directory exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Configure jsonlogger from python-json-logger for standard output (ELK compatible)
    log_handler = logging.StreamHandler(sys.stdout)
    formatter = jsonlogger.JsonFormatter(
        "%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    log_handler.setFormatter(formatter)
    
    # We add the python logging handler to loguru.
    # Loguru automatically passes formatted `{message}` down to standard logging
    # to avoid format string errors.
    loguru_logger.add(
        log_handler,
        format="{message}",
        level=log_level,
        backtrace=True,
        diagnose=True,
    )
    
    # Add file handler — serialize=True writes each line as valid JSON
    # Required by Fluent Bit's 'json' parser in fluent-bit.conf
    # Without this, Fluent Bit silently drops every log line → Kibana stays empty
    loguru_logger.add(
        log_file,
        serialize=True,          # ← Each log line = one JSON object
        level=log_level,
        rotation="10 MB",
        retention=f"{retention_days} days",
        compression="zip",
        backtrace=True,
        diagnose=True,
    )
    
    # Log that setup is complete
    loguru_logger.info(f"Logger initialized | Level: {log_level} | File: {log_file}")


def get_logger(name: str = None):
    """
    Get a logger instance for a specific module.
    
    Usage example in another file:
        from src.utils.logger import get_logger
        logger = get_logger(__name__)
        logger.info("Starting data ingestion...")
    
    Args:
        name: Usually __name__ of the calling module
        
    Returns:
        loguru.logger instance configured for the module
    """
    if name:
        return loguru_logger.bind(module=name)
    return loguru_logger


# Create a default logger instance for direct imports
logger = get_logger()