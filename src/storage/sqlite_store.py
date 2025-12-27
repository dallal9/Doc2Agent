"""SQLite storage for documents and pages with FTS support."""

import json
import sqlite3
import uuid
from typing import Iterator

from src.schemas import DocumentMetadata, DocumentSchema, Heading, PageSchema

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_size_bytes INTEGER NOT NULL,
    page_count INTEGER NOT NULL,
    title TEXT,
    author TEXT,
    subject TEXT,
    file_mod_time REAL,
    file_hash TEXT,
    ingestion_ts TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS pages (
    doc_id TEXT NOT NULL,
    page_num INTEGER NOT NULL,
    char_count INTEGER,
    word_count INTEGER,
    has_tables INTEGER,
    has_images INTEGER,
    contains_names INTEGER,
    contains_dates INTEGER,
    contains_locations INTEGER,
    contains_signatures INTEGER,
    contains_personal_info INTEGER,
    headings_json TEXT,
    languages_json TEXT,
    keywords_json TEXT,
    text TEXT,
    PRIMARY KEY (doc_id, page_num),
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
);

CREATE VIRTUAL TABLE IF NOT EXISTS pages_fts USING fts5(
    doc_id,
    page_num,
    text,
    content='pages',
    content_rowid='rowid'
);

CREATE TRIGGER IF NOT EXISTS pages_ai AFTER INSERT ON pages BEGIN
    INSERT INTO pages_fts(rowid, doc_id, page_num, text)
    VALUES (new.rowid, new.doc_id, new.page_num, new.text);
END;

CREATE TRIGGER IF NOT EXISTS pages_ad AFTER DELETE ON pages BEGIN
    INSERT INTO pages_fts(pages_fts, rowid, doc_id, page_num, text)
    VALUES('delete', old.rowid, old.doc_id, old.page_num, old.text);
END;

CREATE TABLE IF NOT EXISTS query_cache (
    query_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    query_text TEXT NOT NULL,
    query_text_original TEXT,
    final_output TEXT NOT NULL,
    traces_json TEXT,
    logs_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_query_cache_doc_query ON query_cache(doc_id, query_text);
"""


class SQLiteStore:
    def __init__(self, db_path: str = "pdf_data.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript(SCHEMA_SQL)
        self._migrate_schema()
        self.conn.commit()

    def _migrate_schema(self):
        """Add new columns if they don't exist (backward compat)."""
        cur = self.conn.execute("PRAGMA table_info(documents)")
        columns = {row[1] for row in cur.fetchall()}
        if "file_mod_time" not in columns:
            self.conn.execute("ALTER TABLE documents ADD COLUMN file_mod_time REAL")
        if "file_hash" not in columns:
            self.conn.execute("ALTER TABLE documents ADD COLUMN file_hash TEXT")

        # Create query_cache table if it doesn't exist
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='query_cache'"
        )
        if not cur.fetchone():
            self.conn.execute(
                """
                CREATE TABLE query_cache (
                    query_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    query_text TEXT NOT NULL,
                    query_text_original TEXT,
                    final_output TEXT NOT NULL,
                    traces_json TEXT,
                    logs_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
                )
            """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_query_cache_doc_query ON query_cache(doc_id, query_text)"
            )

    def insert_document(self, doc: DocumentSchema):
        cur = self.conn.cursor()
        m = doc.metadata
        cur.execute(
            """INSERT OR REPLACE INTO documents
               (doc_id, file_path, file_name, file_size_bytes, page_count, title, author, subject, file_mod_time, file_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                m.doc_id,
                m.file_path,
                m.file_name,
                m.file_size_bytes,
                m.page_count,
                m.title,
                m.author,
                m.subject,
                m.file_mod_time,
                m.file_hash,
            ),
        )
        for p in doc.pages:
            cur.execute(
                """INSERT OR REPLACE INTO pages
                   (doc_id, page_num, char_count, word_count, has_tables, has_images,
                    contains_names, contains_dates, contains_locations, contains_signatures,
                    contains_personal_info, headings_json, languages_json, keywords_json, text)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    m.doc_id,
                    p.page_num,
                    p.char_count,
                    p.word_count,
                    int(p.has_tables),
                    int(p.has_images),
                    int(p.contains_names),
                    int(p.contains_dates),
                    int(p.contains_locations),
                    int(p.contains_signatures),
                    int(p.contains_personal_info),
                    json.dumps([h.model_dump() for h in p.headings]),
                    json.dumps(p.languages),
                    json.dumps(p.keywords),
                    p.text,
                ),
            )
        self.conn.commit()

    def get_document_metadata(self, doc_id: str) -> DocumentMetadata | None:
        row = self.conn.execute("SELECT * FROM documents WHERE doc_id = ?", (doc_id,)).fetchone()
        return self._row_to_metadata(row) if row else None

    def _row_to_metadata(self, row: sqlite3.Row) -> DocumentMetadata:
        return DocumentMetadata(
            doc_id=row["doc_id"],
            file_path=row["file_path"],
            file_name=row["file_name"],
            file_size_bytes=row["file_size_bytes"],
            page_count=row["page_count"],
            title=row["title"],
            author=row["author"],
            subject=row["subject"],
            file_mod_time=row["file_mod_time"],
            file_hash=row["file_hash"],
        )

    def _row_to_page(self, row: sqlite3.Row) -> PageSchema:
        return PageSchema(
            page_num=row["page_num"],
            char_count=row["char_count"],
            word_count=row["word_count"],
            has_tables=bool(row["has_tables"]),
            has_images=bool(row["has_images"]),
            contains_names=bool(row["contains_names"]),
            contains_dates=bool(row["contains_dates"]),
            contains_locations=bool(row["contains_locations"]),
            contains_signatures=bool(row["contains_signatures"]),
            contains_personal_info=bool(row["contains_personal_info"]),
            headings=[Heading(**h) for h in json.loads(row["headings_json"] or "[]")],
            languages=json.loads(row["languages_json"] or "[]"),
            keywords=json.loads(row["keywords_json"] or "[]"),
            text=row["text"],
        )

    def query_pages(
        self,
        doc_id: str,
        *,
        contains_names: bool | None = None,
        contains_personal: bool | None = None,
        has_images: bool | None = None,
        language: str | None = None,
        limit: int = 10,
    ) -> Iterator[PageSchema]:
        sql = "SELECT * FROM pages WHERE doc_id = ?"
        params: list = [doc_id]
        if contains_names is not None:
            sql += " AND contains_names = ?"
            params.append(int(contains_names))
        if contains_personal is not None:
            sql += " AND contains_personal_info = ?"
            params.append(int(contains_personal))
        if has_images is not None:
            sql += " AND has_images = ?"
            params.append(int(has_images))
        if language:
            sql += " AND languages_json LIKE ?"
            params.append(f'%"{language}"%')
        sql += " ORDER BY page_num"
        if limit > 0:
            sql += " LIMIT ?"
            params.append(limit)
        for row in self.conn.execute(sql, params):
            yield self._row_to_page(row)

    def get_all_pages(self, doc_id: str) -> list[PageSchema]:
        return list(self.query_pages(doc_id, limit=-1))

    def search_text(self, doc_id: str, query: str, limit: int = 10) -> list[PageSchema]:
        """Full-text search using FTS5."""
        sql = """SELECT p.* FROM pages p
                 JOIN pages_fts f ON p.rowid = f.rowid
                 WHERE f.doc_id = ? AND pages_fts MATCH ?
                 ORDER BY rank LIMIT ?"""
        pages = []
        for row in self.conn.execute(sql, (doc_id, query, limit)):
            pages.append(self._row_to_page(row))
        return pages

    def get_document_by_path(self, file_path: str) -> DocumentMetadata | None:
        """Look up document by file path for cache checking."""
        row = self.conn.execute(
            "SELECT * FROM documents WHERE file_path = ?", (file_path,)
        ).fetchone()
        return self._row_to_metadata(row) if row else None

    def list_documents(self) -> list[DocumentMetadata]:
        """List all cached documents, most recent first."""
        rows = self.conn.execute("SELECT * FROM documents ORDER BY ingestion_ts DESC").fetchall()
        return [self._row_to_metadata(row) for row in rows]

    def load_document(self, doc_id: str) -> DocumentSchema | None:
        """Reconstruct full DocumentSchema from DB."""
        meta = self.get_document_metadata(doc_id)
        if not meta:
            return None
        pages = self.get_all_pages(doc_id)
        return DocumentSchema(metadata=meta, pages=pages)

    def delete_document(self, doc_id: str) -> bool:
        """Delete a document and its pages from cache."""
        self.delete_queries_for_document(doc_id)
        self.conn.execute("DELETE FROM pages WHERE doc_id = ?", (doc_id,))
        result = self.conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        self.conn.commit()
        return result.rowcount > 0

    def get_cached_query(self, doc_id: str, query_text: str) -> dict | None:
        """Get cached query result. Query text should be normalized."""
        row = self.conn.execute(
            "SELECT * FROM query_cache WHERE doc_id = ? AND query_text = ? ORDER BY created_at DESC LIMIT 1",
            (doc_id, query_text),
        ).fetchone()
        if not row:
            return None
        return {
            "query_id": row["query_id"],
            "doc_id": row["doc_id"],
            "query_text": row["query_text"],
            "query_text_original": row["query_text_original"],
            "final_output": row["final_output"],
            "traces_json": row["traces_json"],
            "logs_json": row["logs_json"],
            "created_at": row["created_at"],
        }

    def save_query_cache(
        self,
        doc_id: str,
        query_text: str,
        query_text_original: str,
        output: str,
        traces: list,
        logs: dict,
        max_per_file: int,
    ) -> None:
        """Save query cache entry and enforce max_per_file limit."""
        query_id = str(uuid.uuid4())
        traces_json = json.dumps(traces) if traces else None
        logs_json = json.dumps(logs) if logs else None

        self.conn.execute(
            """INSERT INTO query_cache
               (query_id, doc_id, query_text, query_text_original, final_output, traces_json, logs_json)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (query_id, doc_id, query_text, query_text_original, output, traces_json, logs_json),
        )

        # Enforce max_per_file limit
        count = self.conn.execute(
            "SELECT COUNT(*) FROM query_cache WHERE doc_id = ?", (doc_id,)
        ).fetchone()[0]
        if count > max_per_file:
            excess = count - max_per_file
            self.conn.execute(
                """DELETE FROM query_cache
                   WHERE doc_id = ? AND query_id IN (
                       SELECT query_id FROM query_cache
                       WHERE doc_id = ?
                       ORDER BY created_at ASC
                       LIMIT ?
                   )""",
                (doc_id, doc_id, excess),
            )

        self.conn.commit()

    def flush_query_cache(self, doc_id: str | None = None) -> int:
        """Delete all cached queries or queries for a specific document."""
        if doc_id:
            result = self.conn.execute("DELETE FROM query_cache WHERE doc_id = ?", (doc_id,))
        else:
            result = self.conn.execute("DELETE FROM query_cache")
        self.conn.commit()
        return result.rowcount

    def delete_queries_for_document(self, doc_id: str) -> None:
        """Delete all queries for a document."""
        self.conn.execute("DELETE FROM query_cache WHERE doc_id = ?", (doc_id,))
        self.conn.commit()

    def get_query_count_for_document(self, doc_id: str) -> int:
        """Get count of cached queries for a document."""
        row = self.conn.execute(
            "SELECT COUNT(*) FROM query_cache WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        return row[0] if row else 0

    def close(self):
        self.conn.close()
