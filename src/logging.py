import logging
import os
import sys
from datetime import datetime
from pathlib import Path

_configured = False


def setup_logging(service_name: str) -> logging.Logger:
    """Setup logging for a service. Logs to console and optionally to file."""
    global _configured

    logger = logging.getLogger(service_name)

    if _configured and logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Console handler
    console = logging.StreamHandler(sys.stdout)
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
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        logger.info("Logging to file: %s", log_file)

    _configured = True
    return logger

