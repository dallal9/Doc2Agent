from __future__ import annotations

from pydantic_ai import Agent

from src.agents.base import create_agent
from src.agents_config import AgentsConfigFile, PromptsConfigFile


def create_reviewer_agent(
    agents_config: AgentsConfigFile, prompts: PromptsConfigFile
) -> Agent[None, str]:
    agent: Agent[None, str] = create_agent("reviewer", agents_config, prompts, output_type=str)
    return agent
