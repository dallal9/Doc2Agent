from __future__ import annotations

from pydantic_ai import Agent

from src.agents_config import PersonalInfo
from src.logging import setup_logging
from src.schemas import StructuredDocument
from src.tools import (
    extract_tables,
    extract_text_full,
    get_pdf_metadata,
    parse_pdf_to_document,
    search_chunks,
    search_spans_with_patterns,
    validate_personal_info,
)

logger = setup_logging("agent_tools")


def register_reader_tools(agent: Agent) -> None:
    @agent.tool
    async def search_document(ctx, query: str) -> list[dict]:
        logger.info("tool=search_document query=%r", query)
        doc: StructuredDocument | None = getattr(ctx.deps, "document", None)
        if not doc:
            return []
        spans = await search_chunks(query, doc.citable_spans)
        return [s.model_dump() for s in spans]

    @agent.tool
    async def search_with_alternatives(ctx, queries: list[str]) -> list[dict]:
        logger.info("tool=search_with_alternatives queries=%s", [q[:60] for q in queries])
        doc: StructuredDocument | None = getattr(ctx.deps, "document", None)
        if not doc:
            return []
        seen: set[tuple[int, int, int]] = set()
        out: list[dict] = []
        for q in queries:
            spans = await search_chunks(q, doc.citable_spans)
            for s in spans:
                key = (s.page, s.start, s.end)
                if key in seen:
                    continue
                seen.add(key)
                out.append(s.model_dump())
        return out

    @agent.tool
    async def get_section(ctx, section_name: str) -> str:
        logger.info("tool=get_section section_name=%r", section_name)
        doc: StructuredDocument | None = getattr(ctx.deps, "document", None)
        if not doc:
            return ""
        parts = [
            s.text for s in doc.citable_spans if (s.section or "").lower() == section_name.lower()
        ]
        return "\n\n".join(parts)

    @agent.tool
    async def validate_against_personal_info(ctx, claim: str) -> dict:
        logger.info("tool=validate_against_personal_info claim=%r", claim[:200])
        pi: PersonalInfo | None = getattr(ctx.deps, "personal_info", None)
        if not pi:
            return {"error": "No personal info available"}
        return await validate_personal_info(claim, pi)


def register_ingestion_tools(agent: Agent) -> None:
    @agent.tool
    async def parse_pdf(ctx, file_path: str) -> dict:
        logger.info("tool=parse_pdf file_path=%r", file_path)
        return parse_pdf_to_document(file_path).model_dump()

    @agent.tool
    async def read_pdf_text(ctx, file_path: str) -> str:
        logger.info("tool=read_pdf_text file_path=%r", file_path)
        return extract_text_full(file_path)

    @agent.tool
    async def pdf_metadata(ctx, file_path: str) -> dict:
        logger.info("tool=pdf_metadata file_path=%r", file_path)
        return get_pdf_metadata(file_path)

    @agent.tool
    async def pdf_tables(ctx, file_path: str) -> list[dict]:
        logger.info("tool=pdf_tables file_path=%r", file_path)
        return [t.model_dump() for t in extract_tables(file_path)]


def register_extraction_tools(agent: Agent) -> None:
    @agent.tool
    async def find_matches_in_document(
        ctx, patterns: list[str], max_results: int = 50
    ) -> list[dict]:
        logger.info(
            "tool=find_matches_in_document patterns=%s max_results=%s",
            patterns,
            max_results,
        )
        doc: StructuredDocument | None = getattr(ctx.deps, "document", None)
        if not doc:
            return []
        return await search_spans_with_patterns(
            doc.citable_spans,
            patterns,
            max_results=max_results,
        )
