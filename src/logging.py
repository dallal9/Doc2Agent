import logging
import os
from datetime import datetime
from pathlib import Path

_configured = False


def _get_level() -> int:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level, logging.INFO)


def configure_logging(*, log_file: str | None = None) -> None:
    """Configure root logging once per process."""
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    level = _get_level()
    root.setLevel(level)

    file_path = log_file or os.getenv("LOG_FILE")
    if file_path is None and os.getenv("LOG_TO_FILE", "true").lower() == "true":
        Path("logs").mkdir(exist_ok=True)
        file_path = f"logs/{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        os.environ.setdefault("LOG_FILE", file_path)

    if file_path:
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(file_path)
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s"))
        root.addHandler(fh)


def setup_logging(service_name: str) -> logging.Logger:
    """Get a named logger; config is shared across the whole app."""
    configure_logging()
    return logging.getLogger(service_name)
