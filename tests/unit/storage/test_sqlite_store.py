import json
import tempfile
from pathlib import Path

from src.schemas import DocumentMetadata, DocumentSchema, Heading, PageSchema
from src.storage.sqlite_store import SQLiteStore


def test_sqlite_store_initialization():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        store = SQLiteStore(db_path)
        assert store.db_path == db_path
        assert store.conn is not None
        store.close()
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_insert_and_get_document_metadata():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        store = SQLiteStore(db_path)
        doc = DocumentSchema(
            metadata=DocumentMetadata(
                doc_id="test1",
                file_path="/tmp/test.pdf",
                file_name="test.pdf",
                file_size_bytes=1000,
                page_count=2,
                title="Test Doc",
                subject="Test",
            ),
            pages=[
                PageSchema(
                    page_num=1,
                    char_count=100,
                    word_count=20,
                    has_tables=False,
                    has_images=False,
                    text="Page 1 content",
                ),
                PageSchema(
                    page_num=2,
                    char_count=200,
                    word_count=40,
                    has_tables=True,
                    has_images=False,
                    text="Page 2 content",
                ),
            ],
        )
        store.insert_document(doc)
        meta = store.get_document_metadata("test1")
        assert meta is not None
        assert meta.doc_id == "test1"
        assert meta.file_name == "test.pdf"
        assert meta.page_count == 2
        store.close()
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_load_document():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        store = SQLiteStore(db_path)
        doc = DocumentSchema(
            metadata=DocumentMetadata(
                doc_id="test2",
                file_path="/tmp/test2.pdf",
                file_name="test2.pdf",
                file_size_bytes=2000,
                page_count=1,
            ),
            pages=[
                PageSchema(
                    page_num=1,
                    char_count=50,
                    word_count=10,
                    has_tables=False,
                    has_images=False,
                    text="Loaded content",
                )
            ],
        )
        store.insert_document(doc)
        loaded = store.load_document("test2")
        assert loaded is not None
        assert loaded.metadata.doc_id == "test2"
        assert len(loaded.pages) == 1
        assert loaded.pages[0].text == "Loaded content"
        store.close()
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_delete_document():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        store = SQLiteStore(db_path)
        doc = DocumentSchema(
            metadata=DocumentMetadata(
                doc_id="test3",
                file_path="/tmp/test3.pdf",
                file_name="test3.pdf",
                file_size_bytes=500,
                page_count=1,
            ),
            pages=[
                PageSchema(
                    page_num=1,
                    char_count=30,
                    word_count=5,
                    has_tables=False,
                    has_images=False,
                    text="Delete me",
                )
            ],
        )
        store.insert_document(doc)
        assert store.get_document_metadata("test3") is not None
        deleted = store.delete_document("test3")
        assert deleted is True
        assert store.get_document_metadata("test3") is None
        store.close()
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_query_pages_with_filters():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        store = SQLiteStore(db_path)
        doc = DocumentSchema(
            metadata=DocumentMetadata(
                doc_id="test4",
                file_path="/tmp/test4.pdf",
                file_name="test4.pdf",
                file_size_bytes=1000,
                page_count=3,
            ),
            pages=[
                PageSchema(
                    page_num=1,
                    char_count=100,
                    word_count=20,
                    has_tables=False,
                    has_images=True,
                    contains_names=True,
                    text="Page with images",
                ),
                PageSchema(
                    page_num=2,
                    char_count=100,
                    word_count=20,
                    has_tables=False,
                    has_images=False,
                    contains_names=False,
                    text="Page without images",
                ),
                PageSchema(
                    page_num=3,
                    char_count=100,
                    word_count=20,
                    has_tables=False,
                    has_images=True,
                    contains_personal_info=True,
                    text="Page with personal info",
                ),
            ],
        )
        store.insert_document(doc)
        pages_with_images = list(store.query_pages("test4", has_images=True))
        assert len(pages_with_images) == 2
        pages_with_names = list(store.query_pages("test4", contains_names=True))
        assert len(pages_with_names) == 1
        pages_with_personal = list(store.query_pages("test4", contains_personal=True))
        assert len(pages_with_personal) == 1
        store.close()
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_search_text_fts():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        store = SQLiteStore(db_path)
        doc = DocumentSchema(
            metadata=DocumentMetadata(
                doc_id="test5",
                file_path="/tmp/test5.pdf",
                file_name="test5.pdf",
                file_size_bytes=1000,
                page_count=2,
            ),
            pages=[
                PageSchema(
                    page_num=1,
                    char_count=100,
                    word_count=20,
                    has_tables=False,
                    has_images=False,
                    text="This is a test document",
                ),
                PageSchema(
                    page_num=2,
                    char_count=100,
                    word_count=20,
                    has_tables=False,
                    has_images=False,
                    text="Another page with different content",
                ),
            ],
        )
        store.insert_document(doc)
        results = store.search_text("test5", "test document")
        assert len(results) >= 1
        assert any("test document" in p.text for p in results)
        store.close()
    finally:
        Path(db_path).unlink(missing_ok=True)


def test_query_cache_operations():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    try:
        store = SQLiteStore(db_path)
        doc = DocumentSchema(
            metadata=DocumentMetadata(
                doc_id="test6",
                file_path="/tmp/test6.pdf",
                file_name="test6.pdf",
                file_size_bytes=500,
                page_count=1,
            ),
            pages=[
                PageSchema(
                    page_num=1,
                    char_count=50,
                    word_count=10,
                    has_tables=False,
                    has_images=False,
                    text="Cache test",
                )
            ],
        )
        store.insert_document(doc)
        query_text = "test query"
        query_text_original = "Test Query"
        output = "test output"
        traces = [{"step": 1}]
        logs = {"log": "test"}
        store.save_query_cache(
            "test6", query_text, query_text_original, output, traces, logs, max_per_file=10
        )
        cached = store.get_cached_query("test6", query_text)
        assert cached is not None
        assert cached["query_text"] == query_text
        assert cached["query_text_original"] == query_text_original
        assert cached["final_output"] == output
        assert json.loads(cached["traces_json"]) == traces
        count = store.get_query_count_for_document("test6")
        assert count == 1
        flushed = store.flush_query_cache("test6")
        assert flushed == 1
        assert store.get_cached_query("test6", query_text) is None
        store.close()
    finally:
        Path(db_path).unlink(missing_ok=True)
