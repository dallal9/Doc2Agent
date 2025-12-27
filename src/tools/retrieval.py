"""Retrieval and search tools - placeholders for implementation."""

import re

from src.schemas import CitableSpan


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", text.lower())


async def search_chunks(query: str, chunks: list[CitableSpan], top_k: int = 5) -> list[CitableSpan]:
    """Token-overlap search for citable spans."""
    q_tokens = _tokenize(query)
    if not q_tokens or not chunks or top_k <= 0:
        return []

    q_set = set(q_tokens)
    scored: list[tuple[float, float, int, int, CitableSpan]] = []
    for idx, span in enumerate(chunks):
        t_tokens = _tokenize(span.text)
        if not t_tokens:
            continue
        overlap = q_set.intersection(t_tokens)
        if not overlap:
            continue
        coverage = len(overlap) / len(q_set)
        density = len(overlap) / len(t_tokens)
        score = 0.7 * coverage + 0.3 * density
        scored.append((score, coverage, -len(span.text), idx, span))

    scored.sort(key=lambda x: (x[0], x[1], x[2], -x[3]), reverse=True)
    return [entry[4] for entry in scored[:top_k]]


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
                        "start": match.start(),
                        "end": match.end(),
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
