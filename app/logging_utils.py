from __future__ import annotations

import logging
import os

DEFAULT_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def configure_logging(level_name: str | None = None) -> None:
    """Initialize process logging once and keep the root level adjustable."""
    resolved_name = (level_name or os.getenv("LOG_LEVEL", "INFO")).strip().upper() or "INFO"
    level = getattr(logging, resolved_name, logging.INFO)
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        logging.basicConfig(level=level, format=DEFAULT_LOG_FORMAT)

    root_logger.setLevel(level)
