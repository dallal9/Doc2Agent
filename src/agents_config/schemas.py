import json
import os
import re
from pathlib import Path
from typing import Any, Literal, cast

from pydantic import BaseModel, Field

from src.logging import setup_logging

CONFIG_DIR = Path(__file__).parent
AGENTS_CONFIG_PATH_ENV = "AGENTS_CONFIG_PATH"
PROMPTS_CONFIG_PATH_ENV = "PROMPTS_CONFIG_PATH"

_ENV_PLACEHOLDER_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _resolve_env_placeholders(raw: str, source: str) -> str:
    """Replace ${VAR} placeholders with os.environ values.

    Raises ValueError if a referenced var is unset, naming `source` for context.
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = os.environ.get(name)
        if value is None or value == "":
            raise ValueError(
                f"{source} references unset env var: ${{{name}}}. "
                f"Set {name} in your .env or via Config → System."
            )
        return value

    return _ENV_PLACEHOLDER_RE.sub(replace, raw)


class BackendConfig(BaseModel):
    type: Literal["ollama", "openrouter"]
    base_url: str | None = None
    api_key_env: str | None = None


class AgentConfig(BaseModel):
    model: str
    temperature: float = 0.2
    backend: str = "local"
    max_turns: int | None = 20


class AgentsConfigFile(BaseModel):
    default_backend: str = "local"
    backends: dict[str, BackendConfig]
    agents: dict[str, AgentConfig]


class PromptsConfigFile(BaseModel):
    main: str
    reviewer: str
    validator: str
    ingestion: str


class PersonalInfo(BaseModel):
    """Dynamic personal info loaded from PERSONAL_INFO_JSON env var.
    Supports any fields for forms, applications, resumes, contracts."""

    data: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_env(cls) -> "PersonalInfo":
        raw = os.getenv("PERSONAL_INFO_JSON", "{}")
        return cls(data=json.loads(raw))

    def get(self, key: str, default: Any = None) -> Any:
        data = cast(dict[str, Any], self.model_dump().get("data", {}))
        return data.get(key, default)

    def to_prompt_context(self) -> str:
        data = cast(dict[str, Any], self.model_dump().get("data", {}))
        if not data:
            return ""
        lines = ["User's personal information:"]
        for k, v in data.items():
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)


def load_agents_config(path: Path | None = None) -> AgentsConfigFile:
    if path is None:
        env_path = os.getenv(AGENTS_CONFIG_PATH_ENV)
        path = Path(env_path) if env_path else (CONFIG_DIR / "agents.json")
    raw = path.read_text(encoding="utf-8")
    raw = _resolve_env_placeholders(raw, source=f"agents config ({path})")
    cfg = AgentsConfigFile.model_validate_json(raw)
    setup_logging("config").info(
        "Agents config path=%s default_backend=%s backends=%s agents=%s",
        str(path),
        cfg.default_backend,
        sorted(cfg.backends.keys()),
        sorted(cfg.agents.keys()),
    )
    details = {
        k: {"backend": v.backend, "model": v.model, "temperature": v.temperature}
        for k, v in cfg.agents.items()
    }
    setup_logging("config").debug("Agents config details=%s", details)
    return cfg


def load_prompts_config(path: Path | None = None) -> PromptsConfigFile:
    if path is None:
        env_path = os.getenv(PROMPTS_CONFIG_PATH_ENV)
        path = Path(env_path) if env_path else (CONFIG_DIR / "prompts.json")
    cfg = PromptsConfigFile.model_validate_json(path.read_text(encoding="utf-8"))
    setup_logging("config").info("Prompts config path=%s", str(path))
    return cfg


def load_personal_info() -> PersonalInfo:
    return PersonalInfo.from_env()
