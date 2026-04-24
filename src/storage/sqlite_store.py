"""SQLite storage for documents and pages with FTS support."""

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Iterator

from src.schemas import (
    Annotation,
    AnnotationSet,
    DocumentMetadata,
    DocumentSchema,
    Heading,
    PageSchema,
    Span,
)

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

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id TEXT PRIMARY KEY,
    doc_id TEXT,
    title TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS chat_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    seq INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at ON chat_sessions(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_doc_id ON chat_sessions(doc_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session_seq ON chat_messages(session_id, seq);

CREATE TABLE IF NOT EXISTS annotation_sets (
    set_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    label TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(doc_id, label),
    FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS annotations (
    annotation_id TEXT PRIMARY KEY,
    set_id TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (set_id) REFERENCES annotation_sets(set_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS annotation_spans (
    span_id TEXT PRIMARY KEY,
    annotation_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK(kind IN ('text','page')),
    page_num INTEGER NOT NULL,
    quoted_text TEXT,
    FOREIGN KEY (annotation_id) REFERENCES annotations(annotation_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_annotation_sets_doc ON annotation_sets(doc_id);
CREATE INDEX IF NOT EXISTS idx_annotations_set ON annotations(set_id);
CREATE INDEX IF NOT EXISTS idx_spans_ann ON annotation_spans(annotation_id);

CREATE TABLE IF NOT EXISTS datasets (
    dataset_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS dataset_annotations (
    dataset_id TEXT NOT NULL,
    annotation_id TEXT NOT NULL,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (dataset_id, annotation_id),
    FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id) ON DELETE CASCADE,
    FOREIGN KEY (annotation_id) REFERENCES annotations(annotation_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_datasets_created_at ON datasets(created_at DESC);
"""


class SQLiteStore:
    def __init__(self, db_path: str = "pdf_data.db"):
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        self._drop_stale_annotation_tables()
        self.conn.executescript(SCHEMA_SQL)
        self._migrate_schema()
        self.conn.commit()

    def _drop_stale_annotation_tables(self):
        """Drop annotation/dataset/evaluation tables from earlier abandoned
        attempts. Their FKs reference columns that no longer match, which
        causes 'foreign key mismatch' on every write. Safe: no shipped feature
        reads these."""
        expected = {
            "annotation_sets": {"set_id", "doc_id", "label", "description", "created_at"},
            "annotations": {"annotation_id", "set_id", "question", "answer", "created_at"},
            "annotation_spans": {
                "span_id",
                "annotation_id",
                "kind",
                "page_num",
                "quoted_text",
            },
        }
        # Always-drop legacy tables (never used by current code)
        legacy = [
            "evaluation_results",
            "evaluations",
            "metrics",
            "predictions",
            "annotation_documents",
        ]
        for name in legacy:
            self.conn.execute(f"DROP TABLE IF EXISTS {name}")
        # Conditionally drop annotation tables whose columns don't match
        for name in ("annotation_spans", "annotations", "annotation_sets"):
            row = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
            ).fetchone()
            if not row:
                continue
            cols = {r[1] for r in self.conn.execute(f"PRAGMA table_info({name})").fetchall()}
            if cols != expected[name]:
                self.conn.execute(f"DROP TABLE IF EXISTS {name}")
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

        # Create chat_sessions table if it doesn't exist
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_sessions'"
        )
        if not cur.fetchone():
            self.conn.execute(
                """
                CREATE TABLE chat_sessions (
                    session_id TEXT PRIMARY KEY,
                    doc_id TEXT,
                    title TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (doc_id) REFERENCES documents(doc_id) ON DELETE SET NULL
                )
            """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_sessions_updated_at ON chat_sessions(updated_at DESC)"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_sessions_doc_id ON chat_sessions(doc_id, updated_at DESC)"
            )

        # Create chat_messages table if it doesn't exist
        cur = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='chat_messages'"
        )
        if not cur.fetchone():
            self.conn.execute(
                """
                CREATE TABLE chat_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    seq INTEGER NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE
                )
            """
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chat_messages_session_seq ON chat_messages(session_id, seq)"
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

    def create_chat_session(self, *, title: str, doc_id: str | None = None) -> str:
        session_id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO chat_sessions (session_id, doc_id, title, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (session_id, doc_id, title, datetime.utcnow().isoformat()),
        )
        self.conn.commit()
        return session_id

    def get_chat_session(self, session_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT session_id, doc_id, title, created_at, updated_at FROM chat_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        return dict(row)

    def list_chat_sessions(self, *, limit: int = 30) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT s.session_id, s.doc_id, s.title, s.created_at, s.updated_at,
                   COUNT(m.message_id) AS message_count
            FROM chat_sessions s
            LEFT JOIN chat_messages m ON m.session_id = s.session_id
            GROUP BY s.session_id
            ORDER BY s.updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]

    def save_chat_message(self, *, session_id: str, role: str, content: str) -> str:
        message_id = str(uuid.uuid4())
        row = self.conn.execute(
            "SELECT COALESCE(MAX(seq), -1) + 1 AS next_seq FROM chat_messages WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        next_seq = row["next_seq"] if row else 0
        self.conn.execute(
            """
            INSERT INTO chat_messages (message_id, session_id, role, content, seq)
            VALUES (?, ?, ?, ?, ?)
            """,
            (message_id, session_id, role, content, next_seq),
        )
        self.conn.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
            (datetime.utcnow().isoformat(), session_id),
        )
        self.conn.commit()
        return message_id

    def update_chat_session_doc(self, session_id: str, doc_id: str | None) -> None:
        self.conn.execute(
            "UPDATE chat_sessions SET doc_id = ?, updated_at = ? WHERE session_id = ?",
            (doc_id, datetime.utcnow().isoformat(), session_id),
        )
        self.conn.commit()

    def get_chat_messages(self, session_id: str) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT message_id, session_id, role, content, seq, created_at
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY seq ASC
            """,
            (session_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def clear_chat_messages(self, session_id: str) -> int:
        result = self.conn.execute("DELETE FROM chat_messages WHERE session_id = ?", (session_id,))
        self.conn.execute(
            "UPDATE chat_sessions SET updated_at = ? WHERE session_id = ?",
            (datetime.utcnow().isoformat(), session_id),
        )
        self.conn.commit()
        return result.rowcount

    def clear_all_chat_sessions(self) -> int:
        result = self.conn.execute("DELETE FROM chat_sessions")
        self.conn.commit()
        return result.rowcount

    def delete_empty_chat_sessions(self, except_session_id: str | None = None) -> int:
        """Delete chat sessions that have zero messages, optionally excluding one."""
        sql = """
            DELETE FROM chat_sessions
            WHERE session_id NOT IN (SELECT DISTINCT session_id FROM chat_messages)
        """
        params: tuple = ()
        if except_session_id:
            sql += " AND session_id != ?"
            params = (except_session_id,)
        result = self.conn.execute(sql, params)
        self.conn.commit()
        return result.rowcount

    # -- Annotations --------------------------------------------------------

    def create_annotation_set(self, doc_id: str, label: str, description: str | None = None) -> str:
        set_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO annotation_sets (set_id, doc_id, label, description) VALUES (?, ?, ?, ?)",
            (set_id, doc_id, label, description),
        )
        self.conn.commit()
        return set_id

    def list_annotation_sets(self, doc_id: str) -> list[AnnotationSet]:
        rows = self.conn.execute(
            "SELECT * FROM annotation_sets WHERE doc_id = ? ORDER BY created_at DESC",
            (doc_id,),
        ).fetchall()
        return [AnnotationSet(**dict(r)) for r in rows]

    def get_annotation_set(self, set_id: str) -> AnnotationSet | None:
        row = self.conn.execute(
            "SELECT * FROM annotation_sets WHERE set_id = ?", (set_id,)
        ).fetchone()
        return AnnotationSet(**dict(row)) if row else None

    def delete_annotation_set(self, set_id: str) -> bool:
        result = self.conn.execute("DELETE FROM annotation_sets WHERE set_id = ?", (set_id,))
        self.conn.commit()
        return result.rowcount > 0

    def add_annotation(self, set_id: str, question: str, answer: str, spans: list[Span]) -> str:
        annotation_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO annotations (annotation_id, set_id, question, answer) VALUES (?, ?, ?, ?)",
            (annotation_id, set_id, question, answer),
        )
        for s in spans:
            self.conn.execute(
                "INSERT INTO annotation_spans (span_id, annotation_id, kind, page_num, quoted_text) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), annotation_id, s.kind, s.page_num, s.quoted_text),
            )
        self.conn.commit()
        return annotation_id

    def list_annotations(self, set_id: str) -> list[Annotation]:
        rows = self.conn.execute(
            "SELECT * FROM annotations WHERE set_id = ? ORDER BY created_at ASC",
            (set_id,),
        ).fetchall()
        annotations = []
        for r in rows:
            span_rows = self.conn.execute(
                "SELECT * FROM annotation_spans WHERE annotation_id = ? ORDER BY page_num",
                (r["annotation_id"],),
            ).fetchall()
            spans = [Span(**dict(sr)) for sr in span_rows]
            annotations.append(
                Annotation(
                    annotation_id=r["annotation_id"],
                    set_id=r["set_id"],
                    question=r["question"],
                    answer=r["answer"],
                    created_at=r["created_at"],
                    spans=spans,
                )
            )
        return annotations

    def delete_annotation(self, annotation_id: str) -> bool:
        result = self.conn.execute(
            "DELETE FROM annotations WHERE annotation_id = ?", (annotation_id,)
        )
        self.conn.commit()
        return result.rowcount > 0

    def export_annotation_set(self, set_id: str) -> dict | None:
        aset = self.get_annotation_set(set_id)
        if not aset:
            return None
        doc = self.get_document_metadata(aset.doc_id)
        annotations = self.list_annotations(set_id)
        return {
            "document": {
                "doc_id": aset.doc_id,
                "file_name": doc.file_name if doc else None,
            },
            "label": aset.label,
            "description": aset.description,
            "annotations": [
                {
                    "question": a.question,
                    "answer": a.answer,
                    "spans": [
                        {"kind": s.kind, "page_num": s.page_num, "quoted_text": s.quoted_text}
                        for s in a.spans
                    ],
                }
                for a in annotations
            ],
        }

    # -- Datasets (Milestone 2: live chat → evaluation data) ----------------

    def create_dataset(self, *, name: str, description: str | None = None) -> str:
        dataset_id = str(uuid.uuid4())
        self.conn.execute(
            "INSERT INTO datasets (dataset_id, name, description) VALUES (?, ?, ?)",
            (dataset_id, name, description),
        )
        self.conn.commit()
        return dataset_id

    def list_datasets(self) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT d.dataset_id, d.name, d.description, d.created_at,
                   COUNT(da.annotation_id) AS annotation_count
            FROM datasets d
            LEFT JOIN dataset_annotations da ON da.dataset_id = d.dataset_id
            GROUP BY d.dataset_id
            ORDER BY d.created_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def get_dataset(self, dataset_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT dataset_id, name, description, created_at FROM datasets WHERE dataset_id = ?",
            (dataset_id,),
        ).fetchone()
        return dict(row) if row else None

    def delete_dataset(self, dataset_id: str) -> bool:
        result = self.conn.execute("DELETE FROM datasets WHERE dataset_id = ?", (dataset_id,))
        self.conn.commit()
        return result.rowcount > 0

    def get_or_create_annotation_set(
        self, doc_id: str, label: str, description: str | None = None
    ) -> str:
        row = self.conn.execute(
            "SELECT set_id FROM annotation_sets WHERE doc_id = ? AND label = ?",
            (doc_id, label),
        ).fetchone()
        if row:
            return row["set_id"]
        return self.create_annotation_set(doc_id, label, description)

    def add_annotation_to_dataset(self, dataset_id: str, annotation_id: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO dataset_annotations (dataset_id, annotation_id) VALUES (?, ?)",
            (dataset_id, annotation_id),
        )
        self.conn.commit()

    def list_dataset_annotations(self, dataset_id: str) -> list[dict]:
        rows = self.conn.execute(
            """
            SELECT a.annotation_id, a.set_id, a.question, a.answer, a.created_at,
                   s.doc_id, s.label AS set_label,
                   d.file_name AS doc_name
            FROM dataset_annotations da
            JOIN annotations a ON a.annotation_id = da.annotation_id
            JOIN annotation_sets s ON s.set_id = a.set_id
            LEFT JOIN documents d ON d.doc_id = s.doc_id
            WHERE da.dataset_id = ?
            ORDER BY da.added_at ASC
            """,
            (dataset_id,),
        ).fetchall()
        result = []
        for row in rows:
            r = dict(row)
            span_rows = self.conn.execute(
                "SELECT span_id, kind, page_num, quoted_text FROM annotation_spans WHERE annotation_id = ? ORDER BY page_num",
                (r["annotation_id"],),
            ).fetchall()
            r["spans"] = [dict(sr) for sr in span_rows]
            result.append(r)
        return result

    def close(self):
        self.conn.close()
