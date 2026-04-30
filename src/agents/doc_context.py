"""Shared doc-context helpers used by chat and eval prompt builders.

Centralizes when to inline the full document into the prompt vs. give the
agent a compact page manifest and let it use its tools to fetch content.
"""

from __future__ import annotations

from src.schemas.document import DocumentSchema

_PAGE_INLINE_MAX_CHARS = 500
_MANIFEST_SNIPPET_CHARS = 80
_MANIFEST_MAX_KEYWORDS = 3


def should_inline(doc: DocumentSchema | None, max_pages: int) -> bool:
    """Inline the full doc only when we have an enriched doc with few pages."""
    if doc is None or max_pages <= 0:
        return False
    return len(doc.pages) <= max_pages


def inline_pages_block(doc: DocumentSchema) -> str:
    """Per-page inline render. Each page truncated at 500 chars."""
    lines: list[str] = []
    for p in doc.pages:
        text = p.text or ""
        if len(text) > _PAGE_INLINE_MAX_CHARS:
            lines.append(f"[Page {p.page_num}] {text[:_PAGE_INLINE_MAX_CHARS]}...")
        else:
            lines.append(f"[Page {p.page_num}] {text}")
    return "\n".join(lines)


def manifest_block(doc: DocumentSchema | None, fallback_text: str | None) -> str:
    """Compact page manifest used when the doc is too large to inline.

    Per-page summary picks the first non-empty signal in this order:
        1. first heading text
        2. up to three keywords joined
        3. first ~80 chars of page text
    Falls back to a bare hint when there's no enriched doc.
    """
    if doc is None or not doc.pages:
        if fallback_text:
            return (
                f"Document is large (~{len(fallback_text)} chars). "
                "Use the available tools to search and fetch pages."
            )
        return "No document context provided. Use the available tools if needed."

    lines = [f"Document overview ({len(doc.pages)} pages — use tools to fetch content):"]
    for p in doc.pages:
        summary = ""
        if p.headings:
            summary = (p.headings[0].text or "").strip()
        if not summary and p.keywords:
            summary = ", ".join(p.keywords[:_MANIFEST_MAX_KEYWORDS])
        if not summary:
            text = (p.text or "").strip().replace("\n", " ")
            if text:
                snippet = text[:_MANIFEST_SNIPPET_CHARS]
                if len(text) > _MANIFEST_SNIPPET_CHARS:
                    snippet += "…"
                summary = f'"{snippet}"'
        if not summary:
            summary = "(empty page)"
        lines.append(f"- Page {p.page_num}: {summary}")
    return "\n".join(lines)
