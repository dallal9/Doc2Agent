import asyncio
import json
import os
import random
import time
from typing import Any, TypeVar

import httpx
from openai import AsyncOpenAI
from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.usage import UsageLimits

from src.agents_config import AgentsConfigFile, BackendConfig, PromptsConfigFile
from src.logging import setup_logging

T = TypeVar("T", bound=BaseModel)
logger = setup_logging("agents")


# HTTP statuses worth retrying. 4xx other than 408/429 are deterministic and
# would just burn tokens.
_RETRIABLE_STATUSES = {408, 425, 429, 500, 502, 503, 504}


async def _coerce_null_assistant_content(request: httpx.Request) -> None:
    """Coerce assistant messages with `content: null` to empty string.

    Why: some OpenAI-compatible servers (notably Ollama, observed with gemma)
    reject replayed assistant turns where content is null and there are no
    tool_calls — they return 400 'invalid message content type: <nil>'.
    Empty string is accepted everywhere, so this is safe to apply universally.
    """
    if request.method != "POST" or not request.url.path.endswith("/chat/completions"):
        return
    raw = request.content
    if not raw:
        return
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        return
    messages = body.get("messages")
    if not isinstance(messages, list):
        return
    changed = False
    for msg in messages:
        if (
            isinstance(msg, dict)
            and msg.get("role") == "assistant"
            and msg.get("content") is None
            and not msg.get("tool_calls")
        ):
            msg["content"] = ""
            changed = True
    if changed:
        new_body = json.dumps(body).encode("utf-8")
        request._content = new_body
        request.headers["content-length"] = str(len(new_body))


def _make_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        event_hooks={"request": [_coerce_null_assistant_content]},
        timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0),
    )


def build_model(backend_cfg: BackendConfig, model_name: str) -> OpenAIChatModel:
    """Build a pydantic-ai model with a patched HTTP client.

    Both backends (ollama, openrouter) go through OpenAIChatModel; the patched
    httpx client adds the null-content coercion + sane timeouts.
    """
    if backend_cfg.type == "ollama":
        base_url = backend_cfg.base_url or os.getenv("OLLAMA_BASE_URL")
        if not base_url:
            raise ValueError("Ollama backend requires base_url or OLLAMA_BASE_URL env var")
        # Keep env in sync so other code paths that still read it stay consistent.
        os.environ["OLLAMA_BASE_URL"] = base_url
        provider = OllamaProvider(base_url=base_url, http_client=_make_http_client())
        logger.debug("Built ollama model=%s base_url=%s", model_name, base_url)
        return OpenAIChatModel(model_name, provider=provider)

    if backend_cfg.type == "openrouter":
        api_key_env = backend_cfg.api_key_env or "OPENROUTER_API_KEY"
        api_key = os.getenv(api_key_env, "")
        if not api_key:
            raise ValueError(f"OpenRouter backend requires {api_key_env} env var")
        base_url = "https://openrouter.ai/api/v1"
        client = AsyncOpenAI(base_url=base_url, api_key=api_key, http_client=_make_http_client())
        provider = OpenAIProvider(openai_client=client)
        logger.debug("Built openrouter model=%s", model_name)
        return OpenAIChatModel(model_name, provider=provider)

    raise ValueError(f"Unknown backend type: {backend_cfg.type}")


def _retry_settings() -> tuple[int, float]:
    """Read retry config from env. Defaults: 2 retries, 1.0s base backoff."""
    try:
        attempts = max(0, int(os.getenv("LLM_MAX_RETRIES", "2")))
    except ValueError:
        attempts = 2
    try:
        backoff = max(0.0, float(os.getenv("LLM_RETRY_BACKOFF_S", "1.0")))
    except ValueError:
        backoff = 1.0
    return attempts, backoff


def _is_retriable(exc: BaseException) -> bool:
    if isinstance(exc, ModelHTTPError):
        return exc.status_code in _RETRIABLE_STATUSES
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.TransportError):
        return True
    return False


async def run_agent(agent: Agent, prompt: str, *, deps: Any = None, label: str = "") -> Any:
    """Run agent with timing, usage logging, and configurable retry.

    Retries only on transient errors (5xx, 429/408, network/timeouts). 4xx like
    the 'invalid message content type' bug stay non-retriable so we don't
    silently burn tokens repeating a deterministic failure.
    """
    t0 = time.time()
    agent_label = label or "agent"
    logger.info("agent=%s start prompt_chars=%d", agent_label, len(prompt))
    logger.debug("agent=%s prompt=%s", agent_label, prompt[:500])

    usage_limits = getattr(agent, "_usage_limits", None)
    max_retries, backoff_base = _retry_settings()

    async def _call_once() -> Any:
        try:
            if deps:
                return await agent.run(prompt, deps=deps, usage_limits=usage_limits)
            return await agent.run(prompt, usage_limits=usage_limits)
        except TypeError as e:
            # Support simple stubs/mocks in unit tests that don't accept `usage_limits`.
            if "usage_limits" not in str(e):
                raise
            if deps:
                return await agent.run(prompt, deps=deps)
            return await agent.run(prompt)

    attempt = 0
    while True:
        try:
            result = await _call_once()
            break
        except Exception as e:  # noqa: BLE001
            if attempt >= max_retries or not _is_retriable(e):
                raise
            delay = backoff_base * (2**attempt) * (0.5 + random.random())
            attempt += 1
            logger.warning(
                "agent=%s transient error (attempt %d/%d) — retrying in %.2fs: %s",
                agent_label,
                attempt,
                max_retries,
                delay,
                e,
            )
            await asyncio.sleep(delay)

    dt = time.time() - t0
    usage = result.usage()
    output = result.output
    tps = usage.output_tokens / dt if dt > 0 else 0
    out_chars = len(output) if isinstance(output, str) else 0

    logger.info(
        "agent=%s done time=%.2fs in_tok=%d out_tok=%d tps=%.1f out_chars=%d",
        agent_label,
        dt,
        usage.input_tokens,
        usage.output_tokens,
        tps,
        out_chars,
    )
    logger.debug(
        "agent=%s output=%s", agent_label, output[:500] if isinstance(output, str) else output
    )

    if agent_label in ("reviewer", "validator"):
        logger.info(
            "agent=%s nested_call_complete output_preview=%r",
            agent_label,
            (output[:100] if isinstance(output, str) else str(output)[:100]),
        )
    return result


def create_agent(
    agent_name: str,
    agents_config: AgentsConfigFile,
    prompts: PromptsConfigFile,
    output_type: type[T] | type[str] = str,
    deps_type: Any = None,
    extra_system_prompt: str = "",
) -> Agent:
    agent_cfg = agents_config.agents[agent_name]
    backend_cfg = agents_config.backends[agent_cfg.backend]
    model = build_model(backend_cfg, agent_cfg.model)
    system_prompt = getattr(prompts, agent_name)
    if extra_system_prompt:
        system_prompt = f"{system_prompt}\n\n{extra_system_prompt}"
    logger.info(
        "Created agent=%s model=%s backend=%s", agent_name, agent_cfg.model, agent_cfg.backend
    )
    logger.debug(
        "Agent config agent=%s temperature=%s",
        agent_name,
        agent_cfg.temperature,
    )
    agent = Agent(model, system_prompt=system_prompt, output_type=output_type, deps_type=deps_type)
    agent._usage_limits = (
        UsageLimits(request_limit=agent_cfg.max_turns) if agent_cfg.max_turns else None
    )
    return agent
