"""Central, idempotent logging configuration."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import sys
from pathlib import Path

from app.core.config import Settings, get_settings


_HANDLER_MARKER = "_local_rag_chat_handler"
_FORMAT = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging(app_settings: Settings | None = None) -> logging.Logger:
    """Configure one console and one UTF-8 file handler on the root logger.

    Repeated calls reuse existing project handlers instead of adding duplicates.
    Third-party handlers are left untouched.
    """

    current_settings = app_settings or get_settings()
    log_dir = Path(current_settings.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = (log_dir / "app.log").resolve()
    level = getattr(logging, current_settings.LOG_LEVEL.upper())
    formatter = logging.Formatter(_FORMAT, datefmt=_DATE_FORMAT)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    console_handler = _find_project_handler(root_logger, "console")
    if console_handler is None:
        console_handler = logging.StreamHandler(sys.stdout)
        setattr(console_handler, _HANDLER_MARKER, "console")
        root_logger.addHandler(console_handler)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)

    file_handler = _find_project_handler(root_logger, "file")
    if file_handler is not None and Path(file_handler.baseFilename).resolve() != log_file:
        root_logger.removeHandler(file_handler)
        file_handler.close()
        file_handler = None
    if file_handler is None:
        file_handler = RotatingFileHandler(
            log_file,
            maxBytes=current_settings.LOG_MAX_BYTES,
            backupCount=current_settings.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        setattr(file_handler, _HANDLER_MARKER, "file")
        root_logger.addHandler(file_handler)
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)

    return root_logger


def _find_project_handler(
    logger: logging.Logger, handler_kind: str
) -> logging.Handler | None:
    for handler in logger.handlers:
        if getattr(handler, _HANDLER_MARKER, None) == handler_kind:
            return handler
    return None


def get_logger(name: str) -> logging.Logger:
    """Return a named logger without installing module-local handlers."""

    return logging.getLogger(name)
