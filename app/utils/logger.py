from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.config import LOG_DIR, get_settings


def setup_logging() -> logging.Logger:
    """
    Configure application-wide logging.
    """
    settings = get_settings()
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger()
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    console.setLevel(logging.INFO)

    file_handler = RotatingFileHandler(
        LOG_DIR / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    logger.addHandler(console)
    logger.addHandler(file_handler)
    logger.info("Logging initialized for %s", settings.app_name)
    return logger
