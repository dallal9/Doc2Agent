from __future__ import annotations

from dotenv import find_dotenv, load_dotenv

_initialized = False


def init_app() -> None:
    global _initialized
    if _initialized:
        return
    _initialized = True
    env_path = find_dotenv(usecwd=True)
    if env_path:
        # override=True so values rewritten via Config → System
        # win over the parent env inherited across os.execv restarts.
        load_dotenv(env_path, override=True)
    from src.logging import configure_logging

    configure_logging()
