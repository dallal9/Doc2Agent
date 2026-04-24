"""Tests for dataset storage (Milestone 2)."""

import tempfile
from pathlib import Path

from src.schemas import DocumentMetadata, DocumentSchema, PageSchema, Span
from src.storage.sqlite_store import SQLiteStore


def _store():
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    return SQLiteStore(f.name), f.name


def _seed_doc(store, doc_id="doc-x"):
    store.insert_document(
        DocumentSchema(
            metadata=DocumentMetadata(
                doc_id=doc_id,
                file_path=f"/tmp/{doc_id}.pdf",
                file_name=f"{doc_id}.pdf",
                file_size_bytes=10,
                page_count=1,
            ),
            pages=[
                PageSchema(
                    page_num=1,
                    char_count=1,
                    word_count=1,
                    has_tables=False,
                    has_images=False,
                    text="hi",
                )
            ],
        )
    )


def test_create_and_list_datasets():
    store, path = _store()
    try:
        ds_id = store.create_dataset(name="eval-v1", description="first")
        ds = store.list_datasets()
        assert len(ds) == 1
        assert ds[0]["dataset_id"] == ds_id
        assert ds[0]["annotation_count"] == 0
    finally:
        store.close()
        Path(path).unlink(missing_ok=True)


def test_get_or_create_annotation_set_idempotent():
    store, path = _store()
    try:
        _seed_doc(store)
        a = store.get_or_create_annotation_set("doc-x", "chat:abcd")
        b = store.get_or_create_annotation_set("doc-x", "chat:abcd")
        assert a == b
    finally:
        store.close()
        Path(path).unlink(missing_ok=True)


def test_dataset_join_returns_annotations_with_spans_and_doc():
    store, path = _store()
    try:
        _seed_doc(store)
        set_id = store.get_or_create_annotation_set("doc-x", "chat:s1")
        ds_id = store.create_dataset(name="eval")
        ann_id = store.add_annotation(
            set_id, "Q?", "A.", [Span(kind="text", page_num=0, quoted_text="evidence")]
        )
        store.add_annotation_to_dataset(ds_id, ann_id)

        anns = store.list_dataset_annotations(ds_id)
        assert len(anns) == 1
        a = anns[0]
        assert a["question"] == "Q?"
        assert a["doc_id"] == "doc-x"
        assert a["doc_name"] == "doc-x.pdf"
        assert a["set_label"] == "chat:s1"
        assert [s["quoted_text"] for s in a["spans"]] == ["evidence"]
        assert store.list_datasets()[0]["annotation_count"] == 1
    finally:
        store.close()
        Path(path).unlink(missing_ok=True)


def test_delete_dataset_keeps_underlying_annotation():
    store, path = _store()
    try:
        _seed_doc(store)
        set_id = store.get_or_create_annotation_set("doc-x", "chat:s1")
        ds_id = store.create_dataset(name="eval")
        ann_id = store.add_annotation(set_id, "Q?", "A.", [])
        store.add_annotation_to_dataset(ds_id, ann_id)

        assert store.delete_dataset(ds_id) is True
        row = store.conn.execute(
            "SELECT 1 FROM annotations WHERE annotation_id = ?", (ann_id,)
        ).fetchone()
        assert row is not None
    finally:
        store.close()
        Path(path).unlink(missing_ok=True)


def test_datasets_persist_across_store_init():
    """Regression: legacy-drop list must NOT include datasets/dataset_annotations."""
    f = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    f.close()
    try:
        s1 = SQLiteStore(f.name)
        ds_id = s1.create_dataset(name="keep-me")
        s1.close()
        s2 = SQLiteStore(f.name)
        assert any(d["dataset_id"] == ds_id for d in s2.list_datasets())
        s2.close()
    finally:
        Path(f.name).unlink(missing_ok=True)
