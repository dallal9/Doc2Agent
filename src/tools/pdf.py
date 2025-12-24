"""PDF processing tools using pypdf."""

from pathlib import Path

from pypdf import PdfReader

from src.schemas import CitableSpan, DocumentPage, StructuredDocument, TableData


def parse_pdf(file_path: str | Path) -> list[DocumentPage]:
    """Parse PDF and extract text per page."""
    reader = PdfReader(file_path)
    pages = []
    for i, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        needs_ocr = len(text.strip()) < 50  # likely scanned if very little text
        pages.append(DocumentPage(page_num=i + 1, text=text, needs_ocr=needs_ocr))
    return pages


def get_pdf_metadata(file_path: str | Path) -> dict:
    """Extract PDF metadata."""
    reader = PdfReader(file_path)
    meta = reader.metadata or {}
    return {
        "title": meta.get("/Title", ""),
        "author": meta.get("/Author", ""),
        "subject": meta.get("/Subject", ""),
        "creator": meta.get("/Creator", ""),
        "pages": len(reader.pages),
    }


def extract_text_full(file_path: str | Path) -> str:
    """Extract all text from PDF as single string."""
    reader = PdfReader(file_path)
    return "\n\n".join(p.extract_text() or "" for p in reader.pages)


def build_citable_spans(pages: list[DocumentPage]) -> list[CitableSpan]:
    """Build citable spans from pages for citation tracking."""
    spans = []
    for page in pages:
        if not page.text.strip():
            continue
        paragraphs = [p.strip() for p in page.text.split("\n\n") if p.strip()]
        pos = 0
        current_section: str | None = None
        for para in paragraphs:
            if (para.endswith(":") and len(para) < 60) or (para.isupper() and 3 < len(para) < 50):
                current_section = para[:-1] if para.endswith(":") else para
                continue
            start = page.text.find(para, pos)
            if start >= 0:
                spans.append(
                    CitableSpan(
                        text=para,
                        page=page.page_num,
                        start=start,
                        end=start + len(para),
                        section=current_section,
                    )
                )
                pos = start + len(para)
    return spans


def parse_pdf_to_document(file_path: str | Path) -> StructuredDocument:
    """Parse PDF into a full StructuredDocument."""
    pages = parse_pdf(file_path)
    spans = build_citable_spans(pages)
    meta = get_pdf_metadata(file_path)

    # Simple section detection (lines ending with colon or all caps)
    sections = []
    for page in pages:
        for line in page.text.split("\n"):
            line = line.strip()
            if line.endswith(":") and len(line) < 60:
                sections.append(line[:-1])
            elif line.isupper() and 3 < len(line) < 50:
                sections.append(line)

    return StructuredDocument(
        pages=pages,
        sections=list(dict.fromkeys(sections)),  # dedupe preserving order
        citable_spans=spans,
        doc_type=meta.get("subject") or None,
    )


# Placeholder - requires additional deps like camelot-py
def extract_tables(file_path: str | Path) -> list[TableData]:
    """Extract tables from PDF. Placeholder - needs camelot or tabula."""
    return []
