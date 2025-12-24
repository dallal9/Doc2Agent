from __future__ import annotations

from pydantic_ai import Agent

from src.agents.base import create_agent
from src.agents.tooling import register_extraction_tools, register_reader_tools
from src.agents_config import AgentsConfigFile, PersonalInfo, PromptsConfigFile
from src.logging import setup_logging
from src.schemas import StructuredDocument

logger = setup_logging("main_agent")


class MainDeps:
    def __init__(
        self,
        *,
        document: StructuredDocument | None = None,
        text: str = "",
        personal_info: PersonalInfo | None = None,
    ):
        self.document = document
        self.text = text
        self.personal_info = personal_info


def create_main_agent(
    agents_config: AgentsConfigFile, prompts: PromptsConfigFile
) -> Agent[MainDeps, str]:
    agent: Agent[MainDeps, str] = create_agent(
        "main",
        agents_config,
        prompts,
        output_type=str,
        deps_type=MainDeps,
    )

    @agent.tool
    async def get_document_text(ctx, max_chars: int = 8000) -> str:
        logger.info("tool=get_document_text max_chars=%s", max_chars)
        return (ctx.deps.text or "")[:max_chars]

    @agent.tool
    async def get_document_spans(ctx, max_spans: int = 40) -> list[dict]:
        logger.info("tool=get_document_spans max_spans=%s", max_spans)
        doc: StructuredDocument | None = ctx.deps.document
        if not doc:
            return []
        return [s.model_dump() for s in doc.citable_spans[:max_spans]]

    register_reader_tools(agent)
    register_extraction_tools(agent)
    return agent
