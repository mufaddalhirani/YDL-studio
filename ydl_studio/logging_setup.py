"""Rotating file logging for support-friendly diagnostics."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import log_dir


def configure_logging() -> Path:
    directory = log_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "app.log"

    root = logging.getLogger()
    if getattr(root, "_ydl_studio_configured", False):
        return path

    root.setLevel(logging.INFO)
    handler = RotatingFileHandler(
        path,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root.addHandler(handler)
    root._ydl_studio_configured = True  # type: ignore[attr-defined]
    return path
