"""Versioning of UI-editable config (agent + general).

Two kinds of versioned config:
  - "agent":   {agents: <agents.json>, prompts: <prompts.json>}
  - "general": {<env_key>: <str-value>, ...} for non-secret env vars

Snapshots live at data/config_versions/<kind>/<id>.json. Secrets (env vars
declared as type="secret" in env_schema, e.g. OPENROUTER_API_KEY) are never
included in a snapshot. When a "general" version is applied, the secret token
remains whatever the live process holds.

Version id format mirrors the eval-run naming convention:
    {YYYYMMDD_HHMMSS}_{kind}[_{keyword-slug}]
e.g. ``20260427_180412_agent_baseline``. Names, labels, and descriptions are
editable after creation; the id (= file name on disk) is immutable.
"""

from __future__ import annotations

import json
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator, Literal

from src.agents_config.schemas import AGENTS_CONFIG_PATH_ENV
from src.agents_config.schemas import CONFIG_DIR as AGENT_CFG_DIR
from src.agents_config.schemas import PROMPTS_CONFIG_PATH_ENV
from src.config.env_schema import ENV_VARS

Kind = Literal["agent", "general"]
KINDS: tuple[Kind, ...] = ("agent", "general")

VERSIONS_ROOT = Path(os.getenv("CONFIG_VERSIONS_DIR", "data/config_versions"))


def _kind_dir(kind: Kind) -> Path:
    d = VERSIONS_ROOT / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


@dataclass(frozen=True)
class Version:
    id: str
    kind: Kind
    created_at: str
    content: dict[str, Any] = field(default_factory=dict)
    name: str | None = None
    label: str | None = None
    description: str | None = None


def _from_payload(data: dict) -> Version:
    """Tolerant constructor — fills missing fields and ignores unknown ones."""
    return Version(
        id=data["id"],
        kind=data.get("kind", "agent"),
        created_at=data.get("created_at", ""),
        content=data.get("content") or {},
        name=data.get("name") or data.get("id"),
        label=data.get("label"),
        description=data.get("description"),
    )


# ---------- snapshotting current state ----------


def _agent_paths() -> tuple[Path, Path]:
    a = os.getenv(AGENTS_CONFIG_PATH_ENV)
    p = os.getenv(PROMPTS_CONFIG_PATH_ENV)
    agents_path = Path(a) if a else (AGENT_CFG_DIR / "agents.json")
    prompts_path = Path(p) if p else (AGENT_CFG_DIR / "prompts.json")
    return agents_path, prompts_path


def current_agent_state() -> dict[str, Any]:
    agents_path, prompts_path = _agent_paths()
    return {
        "agents": json.loads(agents_path.read_text(encoding="utf-8")),
        "prompts": json.loads(prompts_path.read_text(encoding="utf-8")),
    }


def general_allowed_keys() -> list[str]:
    """Env var keys eligible for snapshot — everything except 'secret' types."""
    return [v.key for v in ENV_VARS if v.type != "secret"]


def current_general_state() -> dict[str, str]:
    out: dict[str, str] = {}
    for key in general_allowed_keys():
        raw = os.environ.get(key)
        if raw is not None:
            out[key] = raw
    return out


# ---------- id generation ----------


def _slugify(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _make_id(kind: Kind, keyword: str | None) -> str:
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    parts = [stamp, kind]
    slug = _slugify(keyword or "")
    if slug:
        parts.append(slug)
    return "_".join(parts)


def _unique_id(kind: Kind, base: str) -> str:
    """Append _2, _3, … if a file with the same id already exists."""
    if not (_kind_dir(kind) / f"{base}.json").exists():
        return base
    n = 2
    while (_kind_dir(kind) / f"{base}_{n}.json").exists():
        n += 1
    return f"{base}_{n}"


# ---------- save / list / get / update ----------


def save_version(
    kind: Kind,
    content: dict[str, Any],
    *,
    keyword: str | None = None,
    name: str | None = None,
    label: str | None = None,
    description: str | None = None,
) -> Version:
    if kind not in KINDS:
        raise ValueError(f"Unknown kind: {kind}")
    if kind == "general":
        allowed = set(general_allowed_keys())
        content = {k: v for k, v in content.items() if k in allowed}
    vid = _unique_id(kind, _make_id(kind, keyword))
    payload = {
        "id": vid,
        "kind": kind,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "name": (name or "").strip() or vid,
        "label": (label or "").strip() or None,
        "description": (description or "").strip() or None,
        "content": content,
    }
    path = _kind_dir(kind) / f"{vid}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return _from_payload(payload)


def list_versions(kind: Kind) -> list[Version]:
    out: list[Version] = []
    for p in sorted(_kind_dir(kind).glob("*.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(_from_payload(data))
        except (json.JSONDecodeError, KeyError):
            continue
    return out


def get_version(kind: Kind, version_id: str) -> Version | None:
    if not version_id:
        return None
    path = _kind_dir(kind) / f"{version_id}.json"
    if not path.exists():
        return None
    return _from_payload(json.loads(path.read_text(encoding="utf-8")))


def delete_version(kind: Kind, version_id: str) -> bool:
    """Delete a version's snapshot file. Returns True if a file was removed."""
    path = _kind_dir(kind) / f"{version_id}.json"
    if not path.exists():
        return False
    path.unlink()
    return True


def update_version_meta(
    kind: Kind,
    version_id: str,
    *,
    name: str | None = None,
    label: str | None = None,
    description: str | None = None,
) -> Version:
    """Edit the human-friendly fields of an existing version."""
    path = _kind_dir(kind) / f"{version_id}.json"
    if not path.exists():
        raise FileNotFoundError(f"Version not found: {kind}/{version_id}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if name is not None:
        data["name"] = name.strip() or data.get("id")
    if label is not None:
        data["label"] = label.strip() or None
    if description is not None:
        data["description"] = description.strip() or None
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return _from_payload(data)


def version_choices(kind: Kind) -> list[tuple[str, str]]:
    """(label, id) pairs for Gradio dropdowns. Most recent first."""
    out: list[tuple[str, str]] = []
    for v in list_versions(kind):
        nm = v.name or v.id
        display = nm if nm == v.id else f"{nm} ({v.id})"
        if v.label:
            display = f"{display} — {v.label}"
        out.append((display, v.id))
    return out


# ---------- bootstrap default ----------


def ensure_default_version(kind: Kind) -> Version:
    """Guarantee at least one version exists for `kind`. Returns the latest."""
    existing = list_versions(kind)
    if existing:
        return existing[0]
    if kind == "agent":
        content = current_agent_state()
    else:
        content = current_general_state()
    return save_version(
        kind,
        content,
        keyword="default",
        name=None,
        label="",
        description="",
    )


# ---------- apply (env mutation, restorable) ----------


@contextmanager
def apply_versions(
    *,
    agent_version_id: str | None = None,
    general_version_id: str | None = None,
    tmp_dir: Path | str = "data/config_versions/_active",
) -> Iterator[dict[str, str | None]]:
    """Temporarily apply selected versions.

    - "general": overlays env vars from snapshot (secrets excluded by design).
    - "agent": writes snapshot's `agents`/`prompts` to temp files and points
      AGENTS_CONFIG_PATH / PROMPTS_CONFIG_PATH at them.

    The previous os.environ values for any touched keys are restored on exit.
    Yields a dict {agent_version_id, general_version_id} (resolved or None).
    """
    tmp = Path(tmp_dir)
    tmp.mkdir(parents=True, exist_ok=True)
    saved: dict[str, str | None] = {}
    touched: set[str] = set()

    def _set(key: str, value: str) -> None:
        if key not in saved:
            saved[key] = os.environ.get(key)
        os.environ[key] = value
        touched.add(key)

    try:
        if general_version_id:
            v = get_version("general", general_version_id)
            if v is None:
                raise ValueError(f"General version not found: {general_version_id}")
            for k, val in v.content.items():
                _set(k, str(val))

        if agent_version_id:
            v = get_version("agent", agent_version_id)
            if v is None:
                raise ValueError(f"Agent version not found: {agent_version_id}")
            agents_obj = v.content.get("agents") or {}
            prompts_obj = v.content.get("prompts") or {}
            agents_path = tmp / f"agents_{agent_version_id}.json"
            prompts_path = tmp / f"prompts_{agent_version_id}.json"
            agents_path.write_text(
                json.dumps(agents_obj, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            prompts_path.write_text(
                json.dumps(prompts_obj, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            _set(AGENTS_CONFIG_PATH_ENV, str(agents_path))
            _set(PROMPTS_CONFIG_PATH_ENV, str(prompts_path))

        yield {
            "agent_version_id": agent_version_id,
            "general_version_id": general_version_id,
        }
    finally:
        for key in touched:
            prev = saved.get(key)
            if prev is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prev


def write_active_agent_files(
    version_id: str, *, tmp_dir: Path | str = "data/config_versions/_active"
) -> tuple[Path, Path]:
    """Write an agent version's contents to disk (without mutating env)."""
    v = get_version("agent", version_id)
    if v is None:
        raise ValueError(f"Agent version not found: {version_id}")
    tmp = Path(tmp_dir)
    tmp.mkdir(parents=True, exist_ok=True)
    agents_path = tmp / f"agents_{version_id}.json"
    prompts_path = tmp / f"prompts_{version_id}.json"
    agents_path.write_text(
        json.dumps(v.content.get("agents") or {}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    prompts_path.write_text(
        json.dumps(v.content.get("prompts") or {}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return agents_path, prompts_path
