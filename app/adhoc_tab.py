"""Ad-hoc page: quick experimental utilities. No validation — for fast iteration only.

Tabs:
  - Switch File ID — given a dataset that may reference multiple documents,
    pick one of those documents and replace it with another. Generates a NEW
    dataset where annotations on the chosen source doc are re-cloned onto the
    replacement doc; annotations on every other doc are carried over as-is.
"""

from __future__ import annotations

import uuid

import gradio as gr

from src.chat import ChatAssistant
from src.logging import setup_logging
from src.schemas.annotation import Span

logger = setup_logging("adhoc_tab")


def _dataset_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    return [
        (f"{d['name']} ({d['annotation_count']} items)", d["dataset_id"])
        for d in assistant.store.list_datasets()
    ]


def _doc_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    return [
        (f"{d.file_name} ({d.page_count} pages)", d.doc_id)
        for d in assistant.list_cached_documents()
    ]


def _docs_in_dataset(
    assistant: ChatAssistant | None, dataset_id: str | None
) -> list[tuple[str, str]]:
    """Distinct documents referenced by a dataset's annotations."""
    if assistant is None or not dataset_id:
        return []
    annotations = assistant.store.list_dataset_annotations(dataset_id)
    seen: dict[str, tuple[str, int]] = {}
    for a in annotations:
        doc_id = a.get("doc_id")
        if not doc_id:
            continue
        name = a.get("doc_name") or doc_id
        cur = seen.get(doc_id)
        seen[doc_id] = (name, (cur[1] if cur else 0) + 1)
    return [(f"{name} ({count} items)", doc_id) for doc_id, (name, count) in seen.items()]


def _clone_dataset_replacing_doc(
    assistant: ChatAssistant,
    source_dataset_id: str,
    old_doc_id: str,
    new_doc_id: str,
    new_dataset_name: str | None,
) -> tuple[str, str]:
    """Clone a dataset, swapping `old_doc_id` for `new_doc_id`.

    Annotations on `old_doc_id` are deep-cloned onto `new_doc_id`; annotations
    on any other document are linked into the new dataset by reference (same
    annotation_id). Returns (new_dataset_id, message).
    """
    source = assistant.store.get_dataset(source_dataset_id)
    if not source:
        raise ValueError("Source dataset not found")
    old_doc = assistant.store.get_document_metadata(old_doc_id)
    if not old_doc:
        raise ValueError("Source document not found")
    new_doc = assistant.store.get_document_metadata(new_doc_id)
    if not new_doc:
        raise ValueError("Replacement document not found")

    annotations = assistant.store.list_dataset_annotations(source_dataset_id)
    name = new_dataset_name or f"{source['name']} [{old_doc.file_name}→{new_doc.file_name}]"
    suffix = uuid.uuid4().hex[:6]
    description = (
        f"Ad-hoc clone of dataset '{source['name']}' with doc "
        f"'{old_doc.file_name}' ({old_doc_id}) replaced by "
        f"'{new_doc.file_name}' ({new_doc_id})."
    )
    new_dataset_id = assistant.store.create_dataset(name=name, description=description)

    set_id_cache: dict[str, str] = {}
    cloned = 0
    carried = 0
    for a in annotations:
        if a.get("doc_id") == old_doc_id:
            old_set_id = a["set_id"]
            if old_set_id not in set_id_cache:
                label = f"{a.get('set_label') or 'set'}-clone-{suffix}"
                set_id_cache[old_set_id] = assistant.store.get_or_create_annotation_set(
                    new_doc_id, label, description=f"Cloned from set {old_set_id}"
                )
            new_set_id = set_id_cache[old_set_id]
            spans = [
                Span(
                    kind=s["kind"],
                    page_num=s["page_num"],
                    quoted_text=s.get("quoted_text"),
                )
                for s in a.get("spans", [])
            ]
            new_annotation_id = assistant.store.add_annotation(
                new_set_id, a["question"], a["answer"], spans
            )
            assistant.store.add_annotation_to_dataset(new_dataset_id, new_annotation_id)
            cloned += 1
        else:
            assistant.store.add_annotation_to_dataset(new_dataset_id, a["annotation_id"])
            carried += 1

    msg = (
        f"Created dataset '{name}' — {cloned} annotation(s) re-cloned onto "
        f"'{new_doc.file_name}', {carried} carried over unchanged."
    )
    return new_dataset_id, msg


def on_source_dataset_change(assistant: ChatAssistant | None, dataset_id: str | None):
    return gr.update(choices=_docs_in_dataset(assistant, dataset_id), value=None)


def on_switch(
    assistant: ChatAssistant | None,
    source_dataset_id: str | None,
    old_doc_id: str | None,
    new_doc_id: str | None,
    new_dataset_name: str | None,
):
    if assistant is None:
        return "_No assistant available._", gr.update()
    if not source_dataset_id:
        return "_Pick a source dataset._", gr.update()
    if not old_doc_id:
        return "_Pick the document to replace._", gr.update()
    if not new_doc_id:
        return "_Pick a replacement document._", gr.update()
    try:
        _, msg = _clone_dataset_replacing_doc(
            assistant,
            source_dataset_id,
            old_doc_id,
            new_doc_id,
            (new_dataset_name or "").strip() or None,
        )
    except Exception as e:
        logger.exception("ad-hoc swap failed")
        return f"**Error:** {e}", gr.update()
    return f"**Done.** {msg}", gr.update(choices=_dataset_choices(assistant))


async def on_adhoc_tab_load(assistant: ChatAssistant | None):
    if assistant is None:
        assistant = ChatAssistant()
    return (
        assistant,
        gr.update(choices=_dataset_choices(assistant), value=None),
        gr.update(choices=[], value=None),
        gr.update(choices=_doc_choices(assistant), value=None),
    )


def build_switch_file_tab(assistant_state: gr.State):
    gr.Markdown(
        "### Switch File ID\n"
        "A dataset can reference multiple documents. Pick one document inside "
        "the source dataset and replace it with another cached document — a "
        "new dataset is created where annotations on the chosen doc are "
        "re-pointed at the replacement, and all other annotations are carried "
        "over unchanged. **No validation — ad-hoc only.**"
    )
    with gr.Row():
        source_dd = gr.Dropdown(label="Source dataset", choices=[], interactive=True)
        old_doc_dd = gr.Dropdown(
            label="Document to replace (from dataset)", choices=[], interactive=True
        )
        new_doc_dd = gr.Dropdown(label="Replacement document", choices=[], interactive=True)
    new_name = gr.Textbox(
        label="New dataset name (optional)",
        placeholder="Leave empty to auto-generate",
    )
    run_btn = gr.Button("Create new dataset with swapped document", variant="primary")
    status_md = gr.Markdown("")

    source_dd.change(
        fn=on_source_dataset_change,
        inputs=[assistant_state, source_dd],
        outputs=[old_doc_dd],
    )
    run_btn.click(
        fn=on_switch,
        inputs=[assistant_state, source_dd, old_doc_dd, new_doc_dd, new_name],
        outputs=[status_md, source_dd],
    )
    return source_dd, old_doc_dd, new_doc_dd, new_name, status_md
