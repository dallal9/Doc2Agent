"""Resolve the running app version.

Source of truth is the `version` field in `pyproject.toml`. We read it via
`importlib.metadata` first (works when the package is installed, which is the
normal case under `uv sync`); on miss we fall back to parsing `pyproject.toml`
directly so dev checkouts and editable layouts still work.
"""

from __future__ import annotations

import re
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _meta_version
from pathlib import Path

PACKAGE_NAME = "Doc2Agent"
_PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


@lru_cache(maxsize=1)
def app_version() -> str:
    """Return the current app version, or "unknown" if it can't be resolved."""
    try:
        return _meta_version(PACKAGE_NAME)
    except PackageNotFoundError:
        pass
    here = Path(__file__).resolve()
    for parent in (here.parent, *here.parents):
        candidate = parent / "pyproject.toml"
        if candidate.exists():
            match = _PYPROJECT_VERSION_RE.search(candidate.read_text(encoding="utf-8"))
            if match:
                return match.group(1)
            break
    return "unknown"
