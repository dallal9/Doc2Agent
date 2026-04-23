import tempfile
from pathlib import Path

import pytest

from src.schemas import DocumentMetadata, DocumentSchema, Span
from src.storage.sqlite_store import SQLiteStore


def _make_store():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    store = SQLiteStore(f.name)
    doc = DocumentSchema(
        metadata=DocumentMetadata(
            doc_id="doc-1",
            file_path="/tmp/a.pdf",
            file_name="a.pdf",
            file_size_bytes=10,
            page_count=3,
        ),
        pages=[],
    )
    store.insert_document(doc)
    return store, f.name


def test_create_and_list_sets():
    store, path = _make_store()
    try:
        sid = store.create_annotation_set("doc-1", "v1", "first pass")
        sets = store.list_annotation_sets("doc-1")
        assert len(sets) == 1 and sets[0].set_id == sid and sets[0].label == "v1"
    finally:
        store.close()
        Path(path).unlink(missing_ok=True)


def test_unique_label_per_doc():
    store, path = _make_store()
    try:
        store.create_annotation_set("doc-1", "v1")
        with pytest.raises(Exception):
            store.create_annotation_set("doc-1", "v1")
    finally:
        store.close()
        Path(path).unlink(missing_ok=True)


def test_add_list_delete_annotation():
    store, path = _make_store()
    try:
        sid = store.create_annotation_set("doc-1", "v1")
        aid = store.add_annotation(
            sid,
            "Q?",
            "A.",
            [
                Span(kind="text", page_num=1, quoted_text="hello"),
                Span(kind="page", page_num=2),
            ],
        )
        anns = store.list_annotations(sid)
        assert len(anns) == 1
        assert anns[0].annotation_id == aid
        assert len(anns[0].spans) == 2
        kinds = {s.kind for s in anns[0].spans}
        assert kinds == {"text", "page"}

        assert store.delete_annotation(aid)
        assert store.list_annotations(sid) == []
    finally:
        store.close()
        Path(path).unlink(missing_ok=True)


def test_export_annotation_set():
    store, path = _make_store()
    try:
        sid = store.create_annotation_set("doc-1", "gold", "desc")
        store.add_annotation(
            sid, "What?", "This.", [Span(kind="text", page_num=1, quoted_text="foo")]
        )
        payload = store.export_annotation_set(sid)
        assert payload["label"] == "gold"
        assert payload["document"]["file_name"] == "a.pdf"
        assert payload["annotations"][0]["question"] == "What?"
        assert payload["annotations"][0]["spans"][0]["quoted_text"] == "foo"
    finally:
        store.close()
        Path(path).unlink(missing_ok=True)


def test_cascade_delete_on_document():
    store, path = _make_store()
    try:
        sid = store.create_annotation_set("doc-1", "v1")
        store.add_annotation(sid, "Q", "A", [Span(kind="page", page_num=1)])
        store.delete_document("doc-1")
        assert store.list_annotation_sets("doc-1") == []
        # spans table should be empty too
        n = store.conn.execute("SELECT COUNT(*) FROM annotation_spans").fetchone()[0]
        assert n == 0
    finally:
        store.close()
        Path(path).unlink(missing_ok=True)


def test_cascade_delete_on_set():
    store, path = _make_store()
    try:
        sid = store.create_annotation_set("doc-1", "v1")
        store.add_annotation(sid, "Q", "A", [Span(kind="page", page_num=1)])
        store.delete_annotation_set(sid)
        n = store.conn.execute("SELECT COUNT(*) FROM annotations").fetchone()[0]
        assert n == 0
        m = store.conn.execute("SELECT COUNT(*) FROM annotation_spans").fetchone()[0]
        assert m == 0
    finally:
        store.close()
        Path(path).unlink(missing_ok=True)
