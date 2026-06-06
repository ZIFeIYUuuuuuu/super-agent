from __future__ import annotations

import logging
import os
import unittest
from unittest.mock import patch

from app.logging_utils import configure_logging


class LoggingConfigurationTests(unittest.TestCase):
    def test_configure_logging_uses_info_for_invalid_level_names(self) -> None:
        root_logger = logging.getLogger()
        original_level = root_logger.level
        try:
            configure_logging("definitely-not-a-level")
            self.assertEqual(root_logger.level, logging.INFO)
        finally:
            root_logger.setLevel(original_level)

    def test_configure_logging_reads_log_level_from_environment(self) -> None:
        root_logger = logging.getLogger()
        original_level = root_logger.level
        try:
            with patch.dict(os.environ, {"LOG_LEVEL": "DEBUG"}, clear=False):
                configure_logging()
            self.assertEqual(root_logger.level, logging.DEBUG)
        finally:
            root_logger.setLevel(original_level)
