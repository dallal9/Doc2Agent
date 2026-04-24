"""Tests for ChatAssistant.export_session_to_dataset (Milestone 2)."""

import os
import tempfile
from pathlib import Path

import pytest

from src.schemas import DocumentMetadata, DocumentSchema, PageSchema


@pytest.fixture
def assistant(monkeypatch):
    tmpdir = tempfile.mkdtemp()
    monkeypatch.setenv("PDF_SQLITE_DIR", tmpdir)
    monkeypatch.setenv("PDF_STORAGE_DIR", os.path.join(tmpdir, "pdfs"))
    monkeypatch.setenv("PDF_JSON_DIR", os.path.join(tmpdir, "json"))
    from src.chat import assistant as assistant_mod

    monkeypatch.setattr(assistant_mod, "create_main_agent", lambda *a, **k: None)
    a = assistant_mod.ChatAssistant()
    yield a
    a.store.close()


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


def test_export_auto_includes_all_turns_with_trace_and_reasoning_spans(assistant):
    _seed_doc(assistant.store)
    sid = assistant.store.create_chat_session(title="t", doc_id="doc-x")
    assistant.store.save_chat_message(session_id=sid, role="user", content="What is X?")
    assistant.store.save_chat_message(
        session_id=sid,
        role="assistant",
        content="<think>looked it up</think>X is 42.",
    )
    traces = [
        {
            "role": "tool",
            "parts": [
                {
                    "part_kind": "tool-return",
                    "tool_name": "search",
                    "tool_call_id": "1",
                    "content": "Page 3 says X is 42.",
                }
            ],
        }
    ]
    assistant.store.save_query_cache(
        "doc-x", "what is x?", "What is X?", "X is 42.", traces, {}, 10
    )
    ds_id = assistant.store.create_dataset(name="eval-1")

    result = assistant.export_session_to_dataset(
        session_id=sid, dataset_id=ds_id, mode="auto"
    )
    assert result == {"created": 1, "skipped_no_doc": 0}

    anns = assistant.store.list_dataset_annotations(ds_id)
    assert len(anns) == 1
    a = anns[0]
    assert a["question"] == "What is X?"
    assert a["answer"] == "X is 42."
    span_texts = [s["quoted_text"] for s in a["spans"]]
    assert "Page 3 says X is 42." in span_texts
    assert any("[reasoning]" in t for t in span_texts)


def test_export_manual_only_picks_selected(assistant):
    _seed_doc(assistant.store)
    sid = assistant.store.create_chat_session(title="t", doc_id="doc-x")
    assistant.store.save_chat_message(session_id=sid, role="user", content="Q1?")
    assistant.store.save_chat_message(session_id=sid, role="assistant", content="A1.")
    msg_b = assistant.store.save_chat_message(
        session_id=sid, role="user", content="Q2?"
    )
    assistant.store.save_chat_message(session_id=sid, role="assistant", content="A2.")
    ds_id = assistant.store.create_dataset(name="eval-2")

    result = assistant.export_session_to_dataset(
        session_id=sid,
        dataset_id=ds_id,
        mode="manual",
        selected_user_message_ids=[msg_b],
    )
    assert result["created"] == 1
    anns = assistant.store.list_dataset_annotations(ds_id)
    assert [a["question"] for a in anns] == ["Q2?"]


def test_export_skips_session_without_document(assistant):
    sid = assistant.store.create_chat_session(title="t", doc_id=None)
    assistant.store.save_chat_message(session_id=sid, role="user", content="Q?")
    assistant.store.save_chat_message(session_id=sid, role="assistant", content="A.")
    ds_id = assistant.store.create_dataset(name="eval-3")

    result = assistant.export_session_to_dataset(
        session_id=sid, dataset_id=ds_id, mode="auto"
    )
    assert result == {"created": 0, "skipped_no_doc": 1}
    assert assistant.store.list_dataset_annotations(ds_id) == []


def test_one_dataset_aggregates_multiple_sessions(assistant):
    _seed_doc(assistant.store)
    ds_id = assistant.store.create_dataset(name="eval-multi")
    for i in range(2):
        sid = assistant.store.create_chat_session(title=f"s{i}", doc_id="doc-x")
        assistant.store.save_chat_message(session_id=sid, role="user", content=f"Q{i}?")
        assistant.store.save_chat_message(session_id=sid, role="assistant", content=f"A{i}.")
        assistant.export_session_to_dataset(session_id=sid, dataset_id=ds_id, mode="auto")
    anns = assistant.store.list_dataset_annotations(ds_id)
    assert sorted(a["question"] for a in anns) == ["Q0?", "Q1?"]
