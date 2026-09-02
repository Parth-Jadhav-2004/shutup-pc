from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def configure_file_logging(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("laptop_remote")
    logger.setLevel(logging.INFO)

    resolved = str(log_path.resolve())
    already_configured = any(
        isinstance(handler, RotatingFileHandler)
        and getattr(handler, "baseFilename", None) == resolved
        for handler in logger.handlers
    )
    if not already_configured:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_path,
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S%z",
            )
        )
        logger.addHandler(handler)

    return logger
