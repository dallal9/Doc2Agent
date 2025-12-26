import asyncio

from src.schemas import CitableSpan
from src.tools.retrieval import search_chunks, search_spans_with_patterns, search_with_patterns


def test_search_chunks_keyword_match():
    chunks = [
        CitableSpan(text="Hello world", page=1, start=0, end=11),
        CitableSpan(text="Goodbye world", page=1, start=12, end=25),
        CitableSpan(text="Something else", page=2, start=0, end=14),
    ]
    results = asyncio.run(search_chunks("world", chunks))
    assert len(results) == 2
    assert all("world" in c.text.lower() for c in results)


def test_search_chunks_case_insensitive():
    chunks = [CitableSpan(text="HELLO WORLD", page=1, start=0, end=11)]
    results = asyncio.run(search_chunks("hello", chunks))
    assert len(results) == 1


def test_search_chunks_respects_top_k():
    chunks = [
        CitableSpan(text=f"match {i}", page=1, start=i * 10, end=i * 10 + 5) for i in range(10)
    ]
    results = asyncio.run(search_chunks("match", chunks, top_k=3))
    assert len(results) == 3


def test_search_with_patterns():
    text = "Meeting on 12/25/2025 and again on Jan 1, 2026"
    results = asyncio.run(search_with_patterns(text, [r"\d{1,2}/\d{1,2}/\d{4}"]))
    assert len(results) == 1
    assert results[0]["match"] == "12/25/2025"


def test_search_spans_with_patterns():
    spans = [
        CitableSpan(text="Due by 12/25/2025", page=1, start=0, end=17, section="Dates"),
        CitableSpan(text="No date here", page=2, start=0, end=12),
    ]
    results = asyncio.run(search_spans_with_patterns(spans, [r"\d{1,2}/\d{1,2}/\d{4}"]))
    assert len(results) == 1
    assert results[0]["page"] == 1
    assert results[0]["section"] == "Dates"
