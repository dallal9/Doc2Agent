import logging
import os
import sys
from datetime import datetime
from pathlib import Path

_configured = False
_level = None


def _get_level() -> int:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level, logging.INFO)


def setup_logging(service_name: str) -> logging.Logger:
    """Setup logging for a service. Logs to console and optionally to file."""
    global _configured
    global _level

    logger = logging.getLogger(service_name)

    if _configured and logger.handlers:
        return logger

    _level = _level or _get_level()
    logger.setLevel(_level)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(_level)
    console.setFormatter(formatter)
    logger.addHandler(console)

    # File handler (optional)
    log_file = os.getenv("LOG_FILE")
    if log_file is None and os.getenv("LOG_TO_FILE", "").lower() == "true":
        Path("logs").mkdir(exist_ok=True)
        log_file = f"logs/{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(_level)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.info("Logging to file: %s", log_file)

    _configured = True
    logger.info("Logging configured level=%s", logging.getLevelName(_level))
    return logger
