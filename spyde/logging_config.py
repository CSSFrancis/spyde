"""
Centralized logging configuration for the spyde application.

This module provides a standardized logging setup that works in both
development and production environments.
"""
import logging
import os
import sys


def setup_logging():
    """
    Configure logging for the application.
    
    Uses environment variables:
    - LOG_LEVEL: Set the logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
                 Default: INFO in production, DEBUG in development
    """
    # Get log level from environment, default to INFO
    log_level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    
    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Remove any existing handlers to avoid duplicates
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    
    # Add console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # Suppress overly verbose third-party loggers
    logging.getLogger("matplotlib").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("distributed").setLevel(logging.WARNING)
    logging.getLogger("bokeh").setLevel(logging.WARNING)
    
    return root_logger


def set_log_level(level_name):
    """
    Dynamically change the logging level.
    
    Parameters
    ----------
    level_name : str
        One of: 'DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'
    """
    log_level = getattr(logging, level_name.upper(), logging.INFO)
    
    # Update root logger level
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    
    # Update all handlers
    for handler in root_logger.handlers:
        handler.setLevel(log_level)
    
    root_logger.info("Log level changed to %s", level_name.upper())
