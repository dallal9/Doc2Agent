"""PDF processing tools using PyMuPDF (via PDFParser)."""

from pathlib import Path

from src.schemas import CitableSpan, DocumentPage, DocumentSchema, StructuredDocument, TableData
from src.tools.pdf_parser import PDFParser


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


def _infer_sections(pages: list[DocumentPage]) -> list[str]:
    sections: list[str] = []
    for page in pages:
        for line in page.text.split("\n"):
            line = line.strip()
            if line.endswith(":") and len(line) < 60:
                sections.append(line[:-1])
            elif line.isupper() and 3 < len(line) < 50:
                sections.append(line)
    # dedupe preserving order
    seen = set()
    ordered: list[str] = []
    for section in sections:
        if section in seen:
            continue
        seen.add(section)
        ordered.append(section)
    return ordered


def document_schema_to_structured(doc: DocumentSchema) -> StructuredDocument:
    """Convert parsed DocumentSchema into a StructuredDocument with spans."""
    pages = [
        DocumentPage(page_num=p.page_num, text=p.text, needs_ocr=p.word_count < 10, tables=[])
        for p in doc.pages
    ]
    spans = build_citable_spans(pages)
    sections = _infer_sections(pages)
    return StructuredDocument(
        pages=pages, sections=sections, citable_spans=spans, doc_type=doc.metadata.subject
    )


def parse_pdf_to_document(file_path: str | Path) -> StructuredDocument:
    """Parse PDF into a StructuredDocument using PyMuPDF."""
    with PDFParser(file_path) as parser:
        doc = parser.parse_document()
    return document_schema_to_structured(doc)


def get_pdf_metadata(file_path: str | Path) -> dict:
    """Extract PDF metadata via PDFParser."""
    with PDFParser(file_path) as parser:
        meta = parser.extract_metadata()
    return meta.model_dump()


def extract_text_full(file_path: str | Path) -> str:
    """Extract all text from PDF as single string via PyMuPDF."""
    with PDFParser(file_path) as parser:
        doc = parser.parse_document()
    return "\n\n".join(p.text for p in doc.pages)


# Placeholder - requires additional deps like camelot-py
def extract_tables(file_path: str | Path) -> list[TableData]:
    """Extract tables from PDF. Placeholder - needs camelot or tabula."""
    return []
