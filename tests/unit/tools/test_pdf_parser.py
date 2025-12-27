from pathlib import Path

from src.tools.pdf_parser import PDFParser


def test_pdf_parser_context_manager(tmp_path):
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
    with PDFParser(pdf_path) as parser:
        assert parser.file_path == str(pdf_path)
        assert parser.doc is not None
    assert parser.doc.is_closed


def test_pdf_parser_extract_metadata(tmp_path):
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
    with PDFParser(pdf_path) as parser:
        meta = parser.extract_metadata()
        assert meta.doc_id is not None
        assert meta.file_path == str(pdf_path)
        assert meta.file_name == pdf_path.name
        assert meta.file_size_bytes > 0
        assert meta.page_count > 0


def test_pdf_parser_parse_pages(tmp_path):
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
    with PDFParser(pdf_path) as parser:
        pages = parser.parse_pages()
        assert len(pages) > 0
        for page in pages:
            assert page.page_num > 0
            assert page.char_count >= 0
            assert page.word_count >= 0
            assert isinstance(page.has_tables, bool)
            assert isinstance(page.has_images, bool)


def test_pdf_parser_parse_document(tmp_path):
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
    with PDFParser(pdf_path) as parser:
        doc = parser.parse_document()
        assert doc.metadata is not None
        assert len(doc.pages) > 0
        assert doc.metadata.page_count == len(doc.pages)
