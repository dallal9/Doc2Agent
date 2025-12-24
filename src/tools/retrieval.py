"""Retrieval and search tools - placeholders for implementation."""

import re

from src.schemas import CitableSpan


async def search_chunks(query: str, chunks: list[CitableSpan], top_k: int = 5) -> list[CitableSpan]:
    """Search document chunks for relevant content.

    TODO: Implement with embeddings:
        - Use sentence-transformers for embedding
        - Compute cosine similarity
        - Return top_k most similar chunks
    """
    # Simple keyword fallback
    query_lower = query.lower()
    return [c for c in chunks if query_lower in c.text.lower()][:top_k]


async def search_with_patterns(text: str, patterns: list[str]) -> list[dict]:
    """Search text using regex patterns.

    Useful for finding dates, obligations, etc.
    """
    results = []
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            results.append(
                {
                    "pattern": pattern,
                    "match": match.group(),
                    "start": match.start(),
                    "end": match.end(),
                }
            )
    return results


async def search_spans_with_patterns(
    spans: list[CitableSpan], patterns: list[str], max_results: int = 50
) -> list[dict]:
    results: list[dict] = []
    for span in spans:
        for pattern in patterns:
            for match in re.finditer(pattern, span.text, re.IGNORECASE):
                results.append(
                    {
                        "pattern": pattern,
                        "match": match.group(),
                        "page": span.page,
                        "section": span.section,
                        "text_snippet": span.text[:300],
                    }
                )
                if len(results) >= max_results:
                    return results
    return results


# Common patterns for document analysis
DATE_PATTERNS = [
    r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b",
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{1,2},? \d{4}\b",
    r"\b\d{1,2} (?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]* \d{4}\b",
]

OBLIGATION_PATTERNS = [
    r"\b(?:must|shall|will|agrees? to|required to|obligated to)\b",
    r"\b(?:responsible for|is to|has to|needs to)\b",
]

DEADLINE_PATTERNS = [
    r"\b(?:by|before|no later than|due|deadline)\b[^.]*\d",
    r"\b\d+\s*(?:days?|weeks?|months?|years?)\s*(?:from|after|before)\b",
]
