"""PDF parser using PyMuPDF for text, table, and image extraction."""

import hashlib
from pathlib import Path

import fitz  # PyMuPDF

from src.schemas import DocumentMetadata, DocumentSchema, PageSchema


class PDFParser:
    def __init__(self, file_path: str | Path):
        self.file_path = str(file_path)
        self.doc = fitz.open(self.file_path)
        # Flatten interactive content (AcroForm + XFA widgets, annotations) so
        # filled-in form values become part of get_text() output. Without this,
        # XFA-based forms (common in gov / legal PDFs) yield empty widgets() and
        # the filled values are invisible. Done in-memory; the source file is
        # not modified.
        if hasattr(self.doc, "bake"):
            try:
                self.doc.bake()
            except Exception:
                pass

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

    @staticmethod
    def _extract_form_fields(page) -> str:
        # AcroForm widget values are not part of page.get_text("text") output;
        # surface them so filled-in PDF forms are visible to the agents.
        if not hasattr(page, "widgets"):
            return ""
        lines: list[str] = []
        try:
            widgets = list(page.widgets() or [])
        except Exception:
            return ""
        for w in widgets:
            value = getattr(w, "field_value", None)
            if value is None or value == "":
                continue
            if isinstance(value, bool):
                value = "Yes" if value else "No"
            name = getattr(w, "field_name", None) or getattr(w, "field_label", None) or "field"
            lines.append(f"{name}: {value}")
        if not lines:
            return ""
        return "\n\n[Form fields]\n" + "\n".join(lines)

    @staticmethod
    def _extract_tables(table_finder) -> tuple[bool, str]:
        # Render each detected table as a pipe-separated grid so the agent
        # can read cell-level content (find_tables only sets has_tables).
        if table_finder is None or not hasattr(table_finder, "tables"):
            return False, ""
        tables = list(table_finder.tables or [])
        if not tables:
            return False, ""
        blocks: list[str] = []
        for idx, t in enumerate(tables, 1):
            try:
                rows = t.extract() or []
            except Exception:
                continue
            rendered = [
                " | ".join("" if c is None else str(c).strip() for c in row)
                for row in rows
                if any(c not in (None, "") for c in row)
            ]
            if rendered:
                blocks.append(f"[Table {idx}]\n" + "\n".join(rendered))
        if not blocks:
            return True, ""
        return True, "\n\n" + "\n\n".join(blocks)

    @staticmethod
    def _extract_annotations(page) -> str:
        # PDF annotations (highlights, sticky notes, free-text comments) are
        # separate from page text and from form widgets — pull their content
        # so reviewer notes are visible to the agents.
        if not hasattr(page, "annots"):
            return ""
        try:
            annots = list(page.annots() or [])
        except Exception:
            return ""
        lines: list[str] = []
        for a in annots:
            info = {}
            try:
                info = a.info or {}
            except Exception:
                pass
            content = (info.get("content") or "").strip()
            atype = ""
            try:
                atype = (a.type[1] if a.type else "") or ""
            except Exception:
                pass
            # For highlights, also capture the underlying selected text.
            quoted = ""
            if atype.lower() in {"highlight", "underline", "squiggly", "strikeout"}:
                try:
                    quads = a.vertices or []
                    if quads:
                        # PyMuPDF returns quads as flat list of points; group by 4.
                        rects = []
                        for j in range(0, len(quads), 4):
                            quad = quads[j : j + 4]
                            if len(quad) == 4:
                                xs = [p[0] for p in quad]
                                ys = [p[1] for p in quad]
                                rects.append(fitz.Rect(min(xs), min(ys), max(xs), max(ys)))
                        parts = [page.get_textbox(r).strip() for r in rects]
                        quoted = " ".join(p for p in parts if p)
                except Exception:
                    pass
            pieces = []
            if quoted:
                pieces.append(f'"{quoted}"')
            if content:
                pieces.append(content)
            if not pieces:
                continue
            label = atype or "annotation"
            lines.append(f"[{label}] " + " — ".join(pieces))
        if not lines:
            return ""
        return "\n\n[Annotations]\n" + "\n".join(lines)

    def parse_pages(self) -> list[PageSchema]:
        pages: list[PageSchema] = []
        for i in range(self.doc.page_count):
            page = self.doc.load_page(i)
            text = page.get_text("text")

            has_images = bool(page.get_images(full=True))
            has_tables = False
            table_block = ""
            if hasattr(page, "find_tables"):
                table_finder = page.find_tables()
                has_tables, table_block = self._extract_tables(table_finder)

            form_text = self._extract_form_fields(page)
            annot_text = self._extract_annotations(page)

            for extra in (table_block, form_text, annot_text):
                if extra:
                    text = (text + extra) if text else extra.lstrip()

            char_count = len(text)
            word_count = len(text.split())
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
