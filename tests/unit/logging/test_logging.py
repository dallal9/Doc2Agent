import logging
import os
import tempfile
from unittest.mock import patch

from src.logging import setup_logging


def test_setup_logging_console_only():
    logger = setup_logging("test_console")
    assert logger.name == "test_console"
    assert len(logging.getLogger().handlers) >= 1


def test_setup_logging_with_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        log_file = os.path.join(tmpdir, "test.log")
        with patch.dict(os.environ, {"LOG_FILE": log_file}):
            import src.logging as log_mod

            logging.getLogger().handlers.clear()

            logger = setup_logging("test_file")
            logger.info("test message")

            assert os.path.exists(log_file)
            with open(log_file) as f:
                assert "test message" in f.read()
