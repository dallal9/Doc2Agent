from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent

from src.agents.base import create_agent, run_agent
from src.agents.reviewer import create_reviewer_agent
from src.agents.tooling import (
    register_database_tools,
    register_extraction_tools,
    register_reader_tools,
)
from src.agents_config import AgentsConfigFile, PersonalInfo, PromptsConfigFile
from src.logging import setup_logging
from src.schemas import StructuredDocument

if TYPE_CHECKING:
    from src.storage import SQLiteStore

logger = setup_logging("main_agent")


def _build_review_prompt(user_message: str, draft: str) -> str:
    return f"User question:\n{user_message}\n\nDraft answer:\n{draft}"


class MainDeps:
    def __init__(
        self,
        *,
        document: StructuredDocument | None = None,
        text: str = "",
        personal_info: PersonalInfo | None = None,
        document_id: str | None = None,
        store: "SQLiteStore | None" = None,
    ):
        self.document = document
        self.text = text
        self.personal_info = personal_info
        self.document_id = document_id
        self.store = store


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
    reviewer = create_reviewer_agent(agents_config, prompts)
    validator: Agent[MainDeps, str] = create_agent(
        "validator",
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

    @agent.tool
    async def review_draft(_ctx, user_message: str, draft: str) -> str:
        logger.info(
            "tool=review_draft invoked user_msg_len=%d draft_len=%d", len(user_message), len(draft)
        )
        prompt = _build_review_prompt(user_message, draft)
        logger.info("tool=review_draft calling reviewer agent")
        result = await run_agent(reviewer, prompt, label="reviewer")
        output = result.output or ""
        logger.info("tool=review_draft completed output_len=%d", len(output))
        return output

    @agent.tool
    async def validate_against_personal_info(ctx, claim: str) -> str:
        """Compare a claim from the document with the user's personal info."""
        logger.info(
            "tool=validate_against_personal_info invoked claim_len=%d claim_preview=%r",
            len(claim),
            claim[:200],
        )
        pi: PersonalInfo | None = getattr(ctx.deps, "personal_info", None)
        if not pi:
            logger.warning("tool=validate_against_personal_info no personal_info available")
            return "No personal info available to validate against."
        pi_ctx = pi.to_prompt_context() or "(no personal info)"
        prompt = f"User's personal info:\n{pi_ctx}\n\nDocument text to verify:\n{claim}"
        logger.info("tool=validate_against_personal_info calling validator agent")
        result = await run_agent(validator, prompt, deps=ctx.deps, label="validator")
        output = result.output or ""
        logger.info("tool=validate_against_personal_info completed output_len=%d", len(output))
        return output

    register_reader_tools(agent)
    register_extraction_tools(agent)
    register_database_tools(agent)
    return agent
