from pydantic import BaseModel


class CitableSpan(BaseModel):
    text: str
    page: int
    start: int
    end: int
    section: str | None = None


class TableData(BaseModel):
    headers: list[str]
    rows: list[list[str]]
    page: int
    caption: str | None = None


class DocumentPage(BaseModel):
    page_num: int
    text: str
    tables: list[TableData] = []
    needs_ocr: bool = False


class StructuredDocument(BaseModel):
    pages: list[DocumentPage]
    sections: list[str]
    citable_spans: list[CitableSpan] = []
    doc_type: str | None = None  # contract, form, resume, application, etc.
