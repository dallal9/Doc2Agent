"""Tests for src.agents.doc_context — inline-vs-manifest decision and renderers."""

from __future__ import annotations

from src.agents.doc_context import inline_pages_block, manifest_block, should_inline
from src.schemas.document import DocumentMetadata, DocumentSchema, Heading, PageSchema


def _meta(pages: int) -> DocumentMetadata:
    return DocumentMetadata(
        doc_id="d",
        file_path="/tmp/d.pdf",
        file_name="d.pdf",
        file_size_bytes=10,
        page_count=pages,
    )


def _page(num: int, *, text: str = "", headings=None, keywords=None) -> PageSchema:
    return PageSchema(
        page_num=num,
        char_count=len(text),
        word_count=len(text.split()),
        has_tables=False,
        has_images=False,
        headings=headings or [],
        keywords=keywords or [],
        text=text,
    )


def _doc(n_pages: int, **page_kwargs) -> DocumentSchema:
    pages = [_page(i + 1, text=f"page {i + 1} body", **page_kwargs) for i in range(n_pages)]
    return DocumentSchema(metadata=_meta(n_pages), pages=pages)


# ---- should_inline ---------------------------------------------------------


def test_should_inline_true_when_pages_under_limit():
    assert should_inline(_doc(3), max_pages=3) is True
    assert should_inline(_doc(1), max_pages=3) is True


def test_should_inline_false_when_pages_over_limit():
    assert should_inline(_doc(4), max_pages=3) is False
    assert should_inline(_doc(50), max_pages=3) is False


def test_should_inline_false_when_doc_missing():
    assert should_inline(None, max_pages=3) is False


def test_should_inline_false_when_max_pages_zero_or_negative():
    assert should_inline(_doc(1), max_pages=0) is False
    assert should_inline(_doc(1), max_pages=-1) is False


# ---- inline_pages_block ----------------------------------------------------


def test_inline_pages_block_includes_every_page():
    doc = _doc(3)
    out = inline_pages_block(doc)
    assert "[Page 1]" in out
    assert "[Page 2]" in out
    assert "[Page 3]" in out


def test_inline_pages_block_truncates_long_pages():
    long_text = "x" * 1500
    doc = DocumentSchema(metadata=_meta(1), pages=[_page(1, text=long_text)])
    out = inline_pages_block(doc)
    assert out.endswith("...")
    # 500 chars + the [Page N] prefix + trailing "..." marker
    assert len(out) < len(long_text)


def test_inline_pages_block_keeps_short_pages_intact():
    doc = DocumentSchema(metadata=_meta(1), pages=[_page(1, text="hi")])
    out = inline_pages_block(doc)
    assert out == "[Page 1] hi"


# ---- manifest_block --------------------------------------------------------


def test_manifest_uses_first_heading_when_present():
    pages = [
        _page(1, text="x", headings=[Heading(text="Introduction", level=1)]),
        _page(2, text="y", headings=[Heading(text="Methods", level=2)]),
    ]
    doc = DocumentSchema(metadata=_meta(2), pages=pages)
    out = manifest_block(doc, fallback_text=None)
    assert "Document overview (2 pages" in out
    assert "Page 1: Introduction" in out
    assert "Page 2: Methods" in out


def test_manifest_falls_back_to_keywords_then_text_snippet():
    pages = [
        _page(1, text="some body", keywords=["alpha", "beta", "gamma", "delta"]),
        _page(2, text="this is a fairly normal sentence describing things"),
    ]
    doc = DocumentSchema(metadata=_meta(2), pages=pages)
    out = manifest_block(doc, fallback_text=None)
    # First page: keywords (capped to 3)
    assert "Page 1: alpha, beta, gamma" in out
    assert "delta" not in out
    # Second page: text snippet quoted
    assert "Page 2:" in out and "this is a fairly normal sentence" in out


def test_manifest_pages_are_ordered():
    pages = [_page(1, text="a"), _page(2, text="b"), _page(3, text="c")]
    doc = DocumentSchema(metadata=_meta(3), pages=pages)
    out = manifest_block(doc, fallback_text=None)
    p1 = out.index("Page 1:")
    p2 = out.index("Page 2:")
    p3 = out.index("Page 3:")
    assert p1 < p2 < p3


def test_manifest_bare_hint_when_no_enriched_doc():
    out = manifest_block(None, fallback_text="x" * 100)
    assert "Use the available tools" in out
    assert "100" in out  # length surfaced for the agent


def test_manifest_returns_no_context_message_when_nothing_available():
    out = manifest_block(None, fallback_text=None)
    assert "No document context" in out
