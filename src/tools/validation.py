"""Validation tools."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from src.agents.base import create_agent, run_agent
from src.agents_config import (
    AgentsConfigFile,
    PersonalInfo,
    PromptsConfigFile,
    load_agents_config,
    load_prompts_config,
)
from src.schemas import StructuredDocument
from src.tools.retrieval import search_chunks

_validator_agent: Agent | None = None
_validator_cfg: tuple[AgentsConfigFile, PromptsConfigFile] | None = None


class _ValidatorDeps:
    def __init__(
        self,
        *,
        document: StructuredDocument | None = None,
        text: str = "",
    ):
        self.document = document
        self.text = text


class _FieldMatch(BaseModel):
    field: str
    value: Any


class _FieldMismatch(BaseModel):
    field: str
    expected: Any
    found_in_claim: bool = True


class PersonalInfoValidationResult(BaseModel):
    claim: str
    matches: list[_FieldMatch] = Field(default_factory=list)
    mismatches: list[_FieldMismatch] = Field(default_factory=list)
    unknown: list[str] = Field(default_factory=list)


def _get_validator_agent() -> Agent[_ValidatorDeps, PersonalInfoValidationResult]:
    global _validator_agent, _validator_cfg
    if _validator_agent is not None:
        return _validator_agent

    if _validator_cfg is None:
        _validator_cfg = (load_agents_config(), load_prompts_config())
    agents_config, prompts = _validator_cfg

    agent: Agent[_ValidatorDeps, PersonalInfoValidationResult] = create_agent(
        "validator",
        agents_config,
        prompts,
        output_type=PersonalInfoValidationResult,
        deps_type=_ValidatorDeps,
    )

    @agent.tool
    async def get_document_text(ctx, max_chars: int = 12000) -> str:
        return (ctx.deps.text or "")[:max_chars]

    @agent.tool
    async def search_document(ctx, query: str, top_k: int = 5) -> list[dict]:
        doc: StructuredDocument | None = ctx.deps.document
        if not doc:
            return []
        spans = await search_chunks(query, doc.citable_spans, top_k=top_k)
        return [s.model_dump() for s in spans]

    _validator_agent = agent
    return agent


async def validate_personal_info(
    claim: str,
    personal_info: PersonalInfo,
    *,
    document: StructuredDocument | None = None,
    text: str = "",
) -> dict:
    """Validate a claim against user's personal information using a sub-agent."""
    agent = _get_validator_agent()
    deps = _ValidatorDeps(document=document, text=text)
    pi_ctx = personal_info.to_prompt_context() or "User's personal information: (none provided)"
    prompt = f"{pi_ctx}\n\nClaim:\n{claim}"
    result = await run_agent(agent, prompt, deps=deps, label="validator")
    return result.output.model_dump()


async def validate_dates(dates: list[dict], reference_date: str | None = None) -> list[dict]:
    """Validate extracted dates for consistency and reasonableness.

    TODO: Implement date parsing and validation:
        - Check if dates are in the past/future as expected
        - Check if date ranges make sense (start < end)
        - Flag suspicious dates (too far in past/future)
    """
    return dates
