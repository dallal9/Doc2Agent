from pydantic import BaseModel, Field


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
    doc_type: str | None = None


# New schemas for refactored ingestion pipeline


class DocumentMetadata(BaseModel):
    doc_id: str
    file_path: str
    file_name: str
    file_size_bytes: int
    page_count: int
    title: str | None = None
    author: str | None = None
    subject: str | None = None
    file_mod_time: float | None = None  # Unix timestamp for cache invalidation
    file_hash: str | None = None  # MD5 hash of file content


class Heading(BaseModel):
    text: str
    level: int  # 1 = H1, 2 = H2, 3 = H3
    start_pos: int | None = None


class PageSchema(BaseModel):
    page_num: int
    char_count: int
    word_count: int
    has_tables: bool
    has_images: bool
    contains_names: bool = False
    contains_dates: bool = False
    contains_locations: bool = False
    contains_signatures: bool = False
    contains_personal_info: bool = False
    headings: list[Heading] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    text: str


class DocumentSchema(BaseModel):
    metadata: DocumentMetadata
    pages: list[PageSchema]

    def total_chars(self) -> int:
        return sum(p.char_count for p in self.pages)
