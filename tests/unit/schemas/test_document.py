from src.schemas import CitableSpan, DocumentPage, StructuredDocument, TableData


def test_citable_span_basic():
    span = CitableSpan(text="Hello", page=1, start=0, end=5)
    assert span.text == "Hello"
    assert span.page == 1
    assert span.section is None


def test_citable_span_with_section():
    span = CitableSpan(text="Content", page=2, start=10, end=17, section="Introduction")
    assert span.section == "Introduction"


def test_table_data():
    table = TableData(headers=["A", "B"], rows=[["1", "2"], ["3", "4"]], page=1)
    assert len(table.headers) == 2
    assert len(table.rows) == 2
    assert table.caption is None


def test_document_page():
    page = DocumentPage(page_num=1, text="Page content")
    assert page.page_num == 1
    assert page.tables == []
    assert page.needs_ocr is False


def test_structured_document():
    doc = StructuredDocument(
        pages=[DocumentPage(page_num=1, text="Hello")],
        sections=["Intro"],
        citable_spans=[CitableSpan(text="Hello", page=1, start=0, end=5)],
    )
    assert len(doc.pages) == 1
    assert len(doc.sections) == 1
    assert len(doc.citable_spans) == 1
    assert doc.doc_type is None
