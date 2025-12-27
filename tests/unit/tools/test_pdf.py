from pathlib import Path

from src.schemas import DocumentMetadata, DocumentPage, DocumentSchema, PageSchema
from src.tools.pdf import (
    build_citable_spans,
    document_schema_to_structured,
    extract_text_full,
    get_pdf_metadata,
    parse_pdf_to_document,
)


def test_document_schema_to_structured_builds_spans_and_sections():
    doc = DocumentSchema(
        metadata=DocumentMetadata(
            doc_id="doc1",
            file_path="/tmp/doc.pdf",
            file_name="doc.pdf",
            file_size_bytes=10,
            page_count=1,
            subject="NDA",
        ),
        pages=[
            PageSchema(
                page_num=1,
                char_count=20,
                word_count=4,
                has_tables=False,
                has_images=False,
                text="INTRO:\n\nThis is a test paragraph.",
            )
        ],
    )

    structured = document_schema_to_structured(doc)

    assert structured.doc_type == "NDA"
    assert structured.sections == ["INTRO"]
    assert structured.citable_spans
    assert structured.citable_spans[0].page == 1


def test_build_citable_spans_creates_spans_with_sections():
    pages = [
        DocumentPage(page_num=1, text="SECTION ONE:\n\nFirst paragraph.\n\nSecond paragraph."),
        DocumentPage(page_num=2, text="SECTION TWO:\n\nThird paragraph."),
    ]
    spans = build_citable_spans(pages)
    assert len(spans) >= 2
    assert all(span.page in [1, 2] for span in spans)
    section_one_spans = [s for s in spans if s.section == "SECTION ONE"]
    assert len(section_one_spans) > 0


def test_build_citable_spans_handles_empty_pages():
    pages = [DocumentPage(page_num=1, text="   \n\n  ")]
    spans = build_citable_spans(pages)
    assert len(spans) == 0


def test_get_pdf_metadata_returns_dict():
    pdf_path = Path(__file__).parent.parent.parent.parent / "uploads" / "NDA2.pdf"
    if not pdf_path.exists():
        pdf_path = (
            Path(__file__).parent.parent.parent.parent
            / "data"
            / "pdfs"
            / "7061475258d60ac26af960167460bdf4.pdf"
        )
    if not pdf_path.exists():
        return
    meta = get_pdf_metadata(pdf_path)
    assert isinstance(meta, dict)
    assert "doc_id" in meta
    assert "file_name" in meta
    assert "page_count" in meta


def test_extract_text_full_concatenates_pages():
    pdf_path = Path(__file__).parent.parent.parent.parent / "uploads" / "NDA2.pdf"
    if not pdf_path.exists():
        pdf_path = (
            Path(__file__).parent.parent.parent.parent
            / "data"
            / "pdfs"
            / "7061475258d60ac26af960167460bdf4.pdf"
        )
    if not pdf_path.exists():
        return
    text = extract_text_full(pdf_path)
    assert isinstance(text, str)
    assert len(text) > 0


def test_parse_pdf_to_document_integration():
    pdf_path = Path(__file__).parent.parent.parent.parent / "uploads" / "NDA2.pdf"
    if not pdf_path.exists():
        pdf_path = (
            Path(__file__).parent.parent.parent.parent
            / "data"
            / "pdfs"
            / "7061475258d60ac26af960167460bdf4.pdf"
        )
    if not pdf_path.exists():
        return
    doc = parse_pdf_to_document(pdf_path)
    assert doc.pages
    assert doc.citable_spans
    assert all(span.page > 0 for span in doc.citable_spans)
