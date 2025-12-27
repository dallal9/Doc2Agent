import os
import time
from typing import Any, TypeVar

from pydantic import BaseModel
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from src.agents_config import AgentsConfigFile, BackendConfig, PromptsConfigFile
from src.logging import setup_logging

T = TypeVar("T", bound=BaseModel)
logger = setup_logging("agents")


def get_model_string(backend_cfg: BackendConfig, model_name: str) -> str:
    """Build model string for pydantic-ai (e.g., 'ollama:gemma2:2b')."""
    if backend_cfg.type == "ollama":
        if backend_cfg.base_url and not os.getenv("OLLAMA_BASE_URL"):
            os.environ["OLLAMA_BASE_URL"] = backend_cfg.base_url
            logger.debug("Set OLLAMA_BASE_URL from agents config")
        logger.debug("Using Ollama model: %s", model_name)
        return f"ollama:{model_name}"
    elif backend_cfg.type == "openrouter":
        api_key = os.getenv(backend_cfg.api_key_env or "OPENROUTER_API_KEY", "")
        if api_key and not os.getenv("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = api_key
            logger.debug(
                "Set OPENAI_API_KEY from %s", backend_cfg.api_key_env or "OPENROUTER_API_KEY"
            )
        if not os.getenv("OPENAI_BASE_URL"):
            os.environ["OPENAI_BASE_URL"] = "https://openrouter.ai/api/v1"
            logger.debug("Set OPENAI_BASE_URL for OpenRouter")
        logger.debug("Using OpenRouter model: %s", model_name)
        return f"openai:{model_name}"
    raise ValueError(f"Unknown backend type: {backend_cfg.type}")


async def run_agent(agent: Agent, prompt: str, *, deps: Any = None, label: str = "") -> Any:
    """Run agent with timing and usage logging."""
    t0 = time.time()
    agent_label = label or "agent"
    logger.info("agent=%s start prompt_chars=%d", agent_label, len(prompt))
    logger.debug("agent=%s prompt=%s", agent_label, prompt[:500])

    usage_limits = getattr(agent, "_usage_limits", None)
    try:
        if deps:
            result = await agent.run(prompt, deps=deps, usage_limits=usage_limits)
        else:
            result = await agent.run(prompt, usage_limits=usage_limits)
    except TypeError as e:
        # Support simple stubs/mocks in unit tests that don't accept `usage_limits`.
        if "usage_limits" not in str(e):
            raise
        if deps:
            result = await agent.run(prompt, deps=deps)
        else:
            result = await agent.run(prompt)

    dt = time.time() - t0
    usage = result.usage()
    output = result.output
    tps = usage.output_tokens / dt if dt > 0 else 0
    out_chars = len(output) if isinstance(output, str) else 0

    agent_label = label or "agent"
    logger.info(
        "agent=%s done time=%.2fs in_tok=%d out_tok=%d tps=%.1f out_chars=%d",
        agent_label,
        dt,
        usage.input_tokens,
        usage.output_tokens,
        tps,
        out_chars,
    )
    logger.debug("agent=%s output=%s", agent_label, output[:500] if isinstance(output, str) else output)
    
    # Log if this is a nested agent call (reviewer/validator)
    if agent_label in ("reviewer", "validator"):
        logger.info("agent=%s nested_call_complete output_preview=%r", agent_label, (output[:100] if isinstance(output, str) else str(output)[:100]))
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
    model_string = get_model_string(backend_cfg, agent_cfg.model)
    system_prompt = getattr(prompts, agent_name)
    if extra_system_prompt:
        system_prompt = f"{system_prompt}\n\n{extra_system_prompt}"
    logger.info(
        "Created agent=%s model=%s backend=%s", agent_name, agent_cfg.model, agent_cfg.backend
    )
    logger.debug(
        "Agent config agent=%s model_string=%s temperature=%s",
        agent_name,
        model_string,
        agent_cfg.temperature,
    )
    agent = Agent(
        model_string, system_prompt=system_prompt, output_type=output_type, deps_type=deps_type
    )
    agent._usage_limits = (
        UsageLimits(request_limit=agent_cfg.max_turns) if agent_cfg.max_turns else None
    )
    return agent
