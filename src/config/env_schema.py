"""Canonical schema of supported .env variables.

Single source of truth for the Config → System tab. Each entry declares its
type, default, group, description, and whether changes can be applied live or
require a process restart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

EnvType = Literal["str", "int", "float", "bool", "json", "secret"]
ReloadKind = Literal["live", "restart"]


@dataclass(frozen=True)
class EnvVar:
    key: str
    type: EnvType
    default: str | None
    group: str
    description: str
    reload: ReloadKind


# Group order is preserved when rendering.
GROUPS = (
    "LLM Backend",
    "Default Models",
    "Logging",
    "Storage",
    "Query",
    "Caching",
    "Evaluation",
    "Personal Info",
    "Misc",
)


ENV_VARS: list[EnvVar] = [
    # LLM Backend
    EnvVar(
        "OLLAMA_BASE_URL",
        "str",
        "http://localhost:11434/v1",
        "LLM Backend",
        "Ollama API endpoint (used when an agent's backend is 'local').",
        "live",
    ),
    EnvVar(
        "OPENROUTER_API_KEY",
        "secret",
        None,
        "LLM Backend",
        "OpenRouter API key for cloud inference.",
        "live",
    ),
    EnvVar(
        "LLM_MAX_RETRIES",
        "int",
        "2",
        "LLM Backend",
        "Retries on transient LLM errors (5xx, 429/408, network/timeouts). 4xx are not retried.",
        "live",
    ),
    EnvVar(
        "LLM_RETRY_BACKOFF_S",
        "float",
        "1.0",
        "LLM Backend",
        "Base seconds for exponential backoff between retries (jittered).",
        "live",
    ),
    # Default Models — referenced from agents.json via ${VAR}
    EnvVar(
        "DEFAULT_MODEL",
        "str",
        None,
        "Default Models",
        "Generic fallback model name. Reference in agents.json as ${DEFAULT_MODEL}.",
        "live",
    ),
    EnvVar(
        "DEFAULT_LIGHT",
        "str",
        None,
        "Default Models",
        "Small/fast model (e.g. ingestion). Reference in agents.json as ${DEFAULT_LIGHT}.",
        "live",
    ),
    EnvVar(
        "DEFAULT_MID",
        "str",
        None,
        "Default Models",
        "Balanced model (e.g. main, validator). Reference in agents.json as ${DEFAULT_MID}.",
        "live",
    ),
    EnvVar(
        "DEFAULT_HIGH",
        "str",
        None,
        "Default Models",
        "Strongest model (e.g. reviewer). Reference in agents.json as ${DEFAULT_HIGH}.",
        "live",
    ),
    # Logging
    EnvVar(
        "LOG_LEVEL",
        "str",
        "INFO",
        "Logging",
        "Logging level: DEBUG, INFO, WARNING, ERROR.",
        "live",
    ),
    EnvVar(
        "LOG_TO_STDOUT",
        "bool",
        "false",
        "Logging",
        "Stream logs to terminal in addition to file.",
        "live",
    ),
    EnvVar(
        "LOG_FILE_PREFIX",
        "str",
        None,
        "Logging",
        "Optional prefix for the auto-generated log filename "
        "(logs/{prefix}_{YYYYMMDD_HHMMSS}.log).",
        "restart",
    ),
    EnvVar(
        "LOG_TO_FILE",
        "bool",
        "true",
        "Logging",
        "Write logs to file. File handler attached at startup.",
        "restart",
    ),
    # Storage
    EnvVar(
        "PDF_SQLITE_DIR",
        "str",
        "data",
        "Storage",
        "Directory for SQLite database files.",
        "live",
    ),
    EnvVar(
        "PDF_JSON_DIR",
        "str",
        "data",
        "Storage",
        "Directory for optional JSON export of small documents.",
        "live",
    ),
    EnvVar(
        "PDF_JSON_MAX_BYTES",
        "int",
        "2000000",
        "Storage",
        "Max file size (bytes) for JSON storage.",
        "live",
    ),
    EnvVar(
        "PDF_STORAGE_DIR",
        "str",
        "data/pdfs",
        "Storage",
        "Directory for permanent PDF file storage. Used by Gradio file allowlist at startup.",
        "restart",
    ),
    # Query
    EnvVar(
        "INLINE_DOC_MAX_CHARS",
        "int",
        "20000",
        "Query",
        "Max characters to inline in prompt.",
        "live",
    ),
    EnvVar(
        "AGENTS_CONFIG_PATH",
        "str",
        None,
        "Query",
        "Path to agents.json (defaults to src/agents_config/agents.json).",
        "live",
    ),
    EnvVar(
        "PROMPTS_CONFIG_PATH",
        "str",
        None,
        "Query",
        "Path to prompts.json (defaults to src/agents_config/prompts.json).",
        "live",
    ),
    # Caching
    EnvVar(
        "PAGE_INGESTION_CONCURRENCY",
        "int",
        "1",
        "Query",
        "Pages enriched in parallel within a single document. 1 for local Ollama, 4–8 for OpenRouter.",
        "live",
    ),
    EnvVar(
        "DOC_INGESTION_CONCURRENCY",
        "int",
        "1",
        "Query",
        "Documents ingested in parallel for bulk uploads. Multiplies with PAGE_INGESTION_CONCURRENCY for total in-flight enrichment calls.",
        "live",
    ),
    EnvVar(
        "QUERY_CACHE_ENABLED",
        "bool",
        "true",
        "Caching",
        "Enable/disable query caching.",
        "live",
    ),
    EnvVar(
        "QUERY_CACHE_MAX_PER_FILE",
        "int",
        "10",
        "Caching",
        "Max cached queries per document.",
        "live",
    ),
    # Evaluation run defaults
    EnvVar(
        "EVAL_CONCURRENCY",
        "int",
        "1",
        "Evaluation",
        "Default max annotations run in parallel per evaluation run.",
        "live",
    ),
    EnvVar(
        "EVAL_MAX_SAMPLES",
        "int",
        None,
        "Evaluation",
        "Default cap on annotations per run (empty = no cap).",
        "live",
    ),
    EnvVar(
        "EVAL_SHUFFLE",
        "bool",
        "false",
        "Evaluation",
        "Shuffle annotations before running.",
        "live",
    ),
    EnvVar(
        "EVAL_SEED",
        "int",
        None,
        "Evaluation",
        "Random seed used when shuffling.",
        "live",
    ),
    EnvVar(
        "EVAL_CONTEXT_MODE",
        "str",
        "full_doc",
        "Evaluation",
        "Context mode for eval queries: full_doc | spans_only | question_only.",
        "live",
    ),
    EnvVar(
        "JUDGE_CONCURRENCY",
        "int",
        "1",
        "Evaluation",
        "Default max predictions judged in parallel per LLM judge run. Keep at 1 for local Ollama.",
        "live",
    ),
    # Personal Info
    EnvVar(
        "PERSONAL_INFO_JSON",
        "json",
        None,
        "Personal Info",
        'JSON object with user data (e.g. {"name": "...", "email": "..."}).',
        "live",
    ),
    # Misc / startup-cached flags
    EnvVar(
        "ASSISTANT_NAME",
        "str",
        "Doc2Agent",
        "Misc",
        "App display name shown in the UI.",
        "restart",
    ),
    EnvVar(
        "SHOW_REASONING",
        "bool",
        "true",
        "Misc",
        "Parse <think> tags and show agent reasoning in chat.",
        "restart",
    ),
    EnvVar(
        "USE_ENRICHMENT",
        "bool",
        "true",
        "Misc",
        "Enable LLM page enrichment during PDF ingestion.",
        "restart",
    ),
    EnvVar(
        "SHOW_INGESTION_LOGS",
        "bool",
        "false",
        "Misc",
        "Stream per-page ingestion progress in chat UI.",
        "restart",
    ),
]


_BY_KEY = {v.key: v for v in ENV_VARS}


def get_var(key: str) -> EnvVar | None:
    return _BY_KEY.get(key)


def vars_by_group(reload: ReloadKind | None = None) -> dict[str, list[EnvVar]]:
    """Return vars grouped by `group`, optionally filtered by reload kind.

    Group ordering follows GROUPS; vars within a group preserve declaration order.
    """
    out: dict[str, list[EnvVar]] = {g: [] for g in GROUPS}
    for v in ENV_VARS:
        if reload is not None and v.reload != reload:
            continue
        out.setdefault(v.group, []).append(v)
    return {g: items for g, items in out.items() if items}
