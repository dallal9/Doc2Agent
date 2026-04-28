import logging
import os
import sys
from datetime import datetime
from pathlib import Path

_configured = False


def _get_level() -> int:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    return getattr(logging, level, logging.INFO)


def _is_enabled(value: str | None, default: str) -> bool:
    return (value or default).lower() == "true"


def _sanitize_prefix(prefix: str) -> str:
    """Keep only filename-safe chars; trim separators."""
    cleaned = "".join(c if (c.isalnum() or c in "-_.") else "_" for c in prefix)
    return cleaned.strip("._-")


def configure_logging(*, log_file: str | None = None) -> None:
    """Configure root logging once per process."""
    global _configured
    if _configured:
        return
    _configured = True

    root = logging.getLogger()
    level = _get_level()
    root.setLevel(level)

    file_path = log_file
    if file_path is None and _is_enabled(os.getenv("LOG_TO_FILE"), "true"):
        Path("logs").mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = _sanitize_prefix(os.getenv("LOG_FILE_PREFIX", "") or "")
        name = f"{prefix}_{ts}.log" if prefix else f"{ts}.log"
        file_path = f"logs/{name}"

    if file_path:
        Path(file_path).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(file_path)
        fh.setLevel(level)
        fh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s"))
        root.addHandler(fh)
        print(f"[Doc2Agent] Logging to file: {Path(file_path).resolve()}")

    if _is_enabled(os.getenv("LOG_TO_STDOUT"), "false"):
        sh = logging.StreamHandler(sys.stdout)
        sh.setLevel(level)
        sh.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(name)s - %(message)s"))
        root.addHandler(sh)


def setup_logging(service_name: str) -> logging.Logger:
    """Get a named logger; config is shared across the whole app."""
    configure_logging()
    return logging.getLogger(service_name)
