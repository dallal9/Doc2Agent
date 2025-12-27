from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic_ai import Agent

from src.logging import setup_logging
from src.schemas import StructuredDocument
from src.tools import search_chunks, search_spans_with_patterns

if TYPE_CHECKING:
    from src.storage import SQLiteStore

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


def register_database_tools(agent: Agent) -> None:
    """Register SQLite query tools for the main agent."""

    @agent.tool
    async def query_pages(
        ctx,
        contains_names: bool | None = None,
        contains_personal: bool | None = None,
        has_images: bool | None = None,
        language: str | None = None,
        limit: int = 10,
    ) -> list[dict]:
        """Query pages from SQLite with optional filters."""
        logger.info(
            "tool=query_pages names=%s personal=%s images=%s lang=%s limit=%s",
            contains_names,
            contains_personal,
            has_images,
            language,
            limit,
        )
        store: "SQLiteStore | None" = getattr(ctx.deps, "store", None)
        doc_id: str | None = getattr(ctx.deps, "document_id", None)
        if not store or not doc_id:
            return []
        return [
            p.model_dump()
            for p in store.query_pages(
                doc_id,
                contains_names=contains_names,
                contains_personal=contains_personal,
                has_images=has_images,
                language=language,
                limit=limit,
            )
        ]

    @agent.tool
    async def get_all_pages(ctx) -> list[dict]:
        """Get all pages for the current document."""
        logger.info("tool=get_all_pages")
        store: "SQLiteStore | None" = getattr(ctx.deps, "store", None)
        doc_id: str | None = getattr(ctx.deps, "document_id", None)
        if not store or not doc_id:
            return []
        return [p.model_dump() for p in store.get_all_pages(doc_id)]

    @agent.tool
    async def search_pages_fts(ctx, query: str, limit: int = 10) -> list[dict]:
        """Full-text search across pages."""
        logger.info("tool=search_pages_fts query=%r limit=%s", query, limit)
        store: "SQLiteStore | None" = getattr(ctx.deps, "store", None)
        doc_id: str | None = getattr(ctx.deps, "document_id", None)
        if not store or not doc_id:
            return []
        return [p.model_dump() for p in store.search_text(doc_id, query, limit)]
