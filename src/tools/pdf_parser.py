"""PDF parser using PyMuPDF for text, table, and image extraction."""

import hashlib
from pathlib import Path

import fitz  # PyMuPDF

from src.schemas import DocumentMetadata, DocumentSchema, PageSchema


class PDFParser:
    def __init__(self, file_path: str | Path):
        self.file_path = str(file_path)
        self.doc = fitz.open(self.file_path)

    def _generate_doc_id(self) -> str:
        return hashlib.md5((self.file_path + str(self.doc.page_count)).encode()).hexdigest()

    def extract_metadata(self) -> DocumentMetadata:
        info = self.doc.metadata or {}
        file_size = Path(self.file_path).stat().st_size
        return DocumentMetadata(
            doc_id=self._generate_doc_id(),
            file_path=self.file_path,
            file_name=Path(self.file_path).name,
            file_size_bytes=file_size,
            page_count=self.doc.page_count,
            title=info.get("title") or None,
            author=info.get("author") or None,
            subject=info.get("subject") or None,
        )

    def parse_pages(self) -> list[PageSchema]:
        pages: list[PageSchema] = []
        for i in range(self.doc.page_count):
            page = self.doc.load_page(i)
            text = page.get_text("text")
            char_count = len(text)
            word_count = len(text.split())
            has_images = bool(page.get_images(full=True))
            # Table detection (PyMuPDF >= 1.23)
            has_tables = False
            if hasattr(page, "find_tables"):
                table_finder = page.find_tables()
                has_tables = (
                    len(table_finder.tables) > 0 if hasattr(table_finder, "tables") else False
                )
            pages.append(
                PageSchema(
                    page_num=i + 1,
                    char_count=char_count,
                    word_count=word_count,
                    has_tables=has_tables,
                    has_images=has_images,
                    text=text,
                )
            )
        return pages

    def parse_document(self) -> DocumentSchema:
        return DocumentSchema(metadata=self.extract_metadata(), pages=self.parse_pages())

    def close(self):
        self.doc.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
