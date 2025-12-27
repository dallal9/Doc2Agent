"""Ingestion agent for page-level semantic enrichment."""

from pydantic_ai import Agent

from src.agents.base import create_agent, run_agent
from src.agents_config import AgentsConfigFile, PromptsConfigFile
from src.logging import setup_logging
from src.schemas import PageSchema

logger = setup_logging("ingestion_agent")


def create_ingestion_agent(
    agents_config: AgentsConfigFile, prompts: PromptsConfigFile
) -> Agent[None, PageSchema]:
    return create_agent(
        "ingestion",
        agents_config,
        prompts,
        output_type=PageSchema,
        deps_type=None,
    )


async def ingest_page(agent: Agent[None, PageSchema], page_input: dict) -> PageSchema:
    """Run ingestion agent on a single page to extract semantic metadata."""
    page_num = page_input["page_num"]
    text = page_input["text"]
    prompt = (
        f"Page number: {page_num}\n"
        f"Character count: {page_input['char_count']}\n"
        f"Word count: {page_input['word_count']}\n"
        f"Has tables: {page_input['has_tables']}\n"
        f"Has images: {page_input['has_images']}\n\n"
        f"Text:\n{text}"
    )
    logger.info("ingesting page=%d chars=%d", page_num, len(text))
    result = await run_agent(agent, prompt, label=f"ingestion-p{page_num}")
    return result.output
