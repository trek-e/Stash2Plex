"""Structured JSON logging configuration for the Stash2Plex provider."""

from __future__ import annotations

import logging

from pythonjsonlogger import json as jsonlogger


def configure_logging(log_level: str) -> None:
    """Configure root logger with structured JSON output.

    Output format: {"ts": "...", "level": "...", "name": "...", "msg": "..."}

    Args:
        log_level: Logging level string (e.g., "info", "debug", "warning").
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        rename_fields={
            "asctime": "ts",
            "levelname": "level",
            "message": "msg",
        },
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    # Clear any existing handlers to avoid duplicate output
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(level)
