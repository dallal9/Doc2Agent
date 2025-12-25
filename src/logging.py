import logging
import os
import sys
from datetime import datetime
from pathlib import Path


def _get_level() -> int:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level, logging.INFO)


def configure_logging(*, log_file: str | None = None) -> None:
    """Configure root logging once per process."""
    root = logging.getLogger()
    if root.handlers:
        return

    level = _get_level()
    root.setLevel(level)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_path = log_file or os.getenv("LOG_FILE")
    if file_path is None and os.getenv("LOG_TO_FILE", "").lower() == "true":
        Path("logs").mkdir(exist_ok=True)
        file_path = f"logs/{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        os.environ.setdefault("LOG_FILE", file_path)

    if file_path:
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(file_path)
        fh.setLevel(level)
        fh.setFormatter(formatter)
        root.addHandler(fh)


def setup_logging(service_name: str) -> logging.Logger:
    """Get a named logger; config is shared across the whole app."""
    configure_logging()
    return logging.getLogger(service_name)
