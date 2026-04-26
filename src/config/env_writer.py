"""Atomic .env writer.

Preserves comments and key order. Updates existing keys in place; appends
unknown keys at the end. Empty values comment the line out.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

_KEY_RE = re.compile(r"^\s*#?\s*([A-Z][A-Z0-9_]*)\s*=")
_NEEDS_QUOTE_RE = re.compile(r"[\s#'\"]")


def _quote(value: str) -> str:
    """Quote a value for .env if it contains whitespace, #, or quotes.

    Uses double quotes; backslash-escapes embedded double quotes.
    """
    if value == "":
        return ""
    if not _NEEDS_QUOTE_RE.search(value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _format_line(key: str, value: str) -> str:
    if value == "":
        return f"# {key}="
    return f"{key}={_quote(value)}"


def write_env(
    updates: dict[str, str],
    env_path: Path | str = ".env",
    example_path: Path | str = "env.example",
) -> Path:
    """Write `updates` to `env_path`, preserving existing comments and order.

    - Existing keys (active or commented) are replaced in place.
    - Empty-string values cause the line to be commented out (`# KEY=`).
    - Keys not present in the file are appended at the end.
    - If `env_path` doesn't exist, seeds from `example_path` if available.
    - Atomic: writes to <path>.tmp then os.replace.

    Returns the absolute path of the .env file written.
    """
    env_path = Path(env_path)
    example_path = Path(example_path)

    if not env_path.exists():
        if example_path.exists():
            shutil.copyfile(example_path, env_path)
        else:
            env_path.touch()

    original = env_path.read_text(encoding="utf-8").splitlines()
    pending = dict(updates)
    out_lines: list[str] = []

    for line in original:
        match = _KEY_RE.match(line)
        if match and match.group(1) in pending:
            key = match.group(1)
            value = pending.pop(key)
            out_lines.append(_format_line(key, value))
        else:
            out_lines.append(line)

    if pending:
        if out_lines and out_lines[-1].strip() != "":
            out_lines.append("")
        out_lines.append("# Added via Config → System")
        for key, value in pending.items():
            out_lines.append(_format_line(key, value))

    tmp_path = env_path.with_suffix(env_path.suffix + ".tmp")
    tmp_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    os.replace(tmp_path, env_path)
    return env_path.resolve()
