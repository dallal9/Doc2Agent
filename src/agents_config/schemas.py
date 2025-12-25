import json
import os
from pathlib import Path
from typing import Any, Literal, cast

from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.logging import setup_logging

CONFIG_DIR = Path(__file__).parent
AGENTS_CONFIG_PATH_ENV = "AGENTS_CONFIG_PATH"
PROMPTS_CONFIG_PATH_ENV = "PROMPTS_CONFIG_PATH"
_env_loaded = False


def _ensure_env_loaded() -> None:
    global _env_loaded
    if _env_loaded:
        return
    load_dotenv()
    setup_logging("config").debug("Loaded .env (if present)")
    _env_loaded = True


class BackendConfig(BaseModel):
    type: Literal["ollama", "openrouter"]
    base_url: str | None = None
    api_key_env: str | None = None


class AgentConfig(BaseModel):
    model: str
    temperature: float = 0.2
    backend: str = "local"


class AgentsConfigFile(BaseModel):
    default_backend: str = "local"
    backends: dict[str, BackendConfig]
    agents: dict[str, AgentConfig]


class PromptsConfigFile(BaseModel):
    main: str
    reviewer: str


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
    _ensure_env_loaded()
    if path is None:
        env_path = os.getenv(AGENTS_CONFIG_PATH_ENV)
        path = Path(env_path) if env_path else (CONFIG_DIR / "agents.json")
    cfg = AgentsConfigFile.model_validate_json(path.read_text(encoding="utf-8"))
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
    _ensure_env_loaded()
    if path is None:
        env_path = os.getenv(PROMPTS_CONFIG_PATH_ENV)
        path = Path(env_path) if env_path else (CONFIG_DIR / "prompts.json")
    cfg = PromptsConfigFile.model_validate_json(path.read_text(encoding="utf-8"))
    setup_logging("config").info("Prompts config path=%s", str(path))
    return cfg


def load_personal_info() -> PersonalInfo:
    return PersonalInfo.from_env()
