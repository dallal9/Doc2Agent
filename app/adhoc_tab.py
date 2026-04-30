"""Ad-hoc page: quick experimental utilities. No validation — for fast iteration only.

Tabs:
  - Switch File ID — given a dataset that may reference multiple documents,
    optionally pick a replacement for any/all of them. Generates a NEW dataset
    where annotations on swapped docs are re-cloned onto their replacement;
    annotations on un-swapped docs are carried over as-is. Each source doc
    can be swapped at most once per operation.
"""

from __future__ import annotations

import uuid

import gradio as gr

from src.chat import ChatAssistant
from src.logging import setup_logging
from src.schemas.annotation import Span

logger = setup_logging("adhoc_tab")

MAX_SWAP_ROWS = 10


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
) -> list[tuple[str, str, int]]:
    """Distinct documents referenced by a dataset's annotations.

    Returns a list of (doc_id, doc_name, annotation_count).
    """
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
    return [(doc_id, name, count) for doc_id, (name, count) in seen.items()]


def _clone_dataset_swapping_docs(
    assistant: ChatAssistant,
    source_dataset_id: str,
    swaps: dict[str, str],
    new_dataset_name: str | None,
) -> tuple[str, str]:
    """Clone a dataset, applying multiple `old_doc_id -> new_doc_id` swaps in one pass.

    Annotations on a swapped source doc are deep-cloned onto the replacement;
    annotations on un-swapped docs are linked into the new dataset by reference.
    """
    if not swaps:
        raise ValueError("No swaps selected")

    source = assistant.store.get_dataset(source_dataset_id)
    if not source:
        raise ValueError("Source dataset not found")

    swap_meta: dict[str, tuple] = {}  # old_doc_id -> (old_meta, new_meta)
    for old_doc_id, new_doc_id in swaps.items():
        old_doc = assistant.store.get_document_metadata(old_doc_id)
        if not old_doc:
            raise ValueError(f"Source document not found: {old_doc_id}")
        new_doc = assistant.store.get_document_metadata(new_doc_id)
        if not new_doc:
            raise ValueError(f"Replacement document not found: {new_doc_id}")
        swap_meta[old_doc_id] = (old_doc, new_doc)

    annotations = assistant.store.list_dataset_annotations(source_dataset_id)
    if new_dataset_name:
        name = new_dataset_name
    else:
        parts = [f"{old.file_name}→{new.file_name}" for old, new in swap_meta.values()]
        name = f"{source['name']} [{'; '.join(parts)}]"
    suffix = uuid.uuid4().hex[:6]
    description_parts = [
        f"'{old.file_name}' ({old_id}) → '{new.file_name}' ({new.doc_id})"
        for old_id, (old, new) in swap_meta.items()
    ]
    description = (
        f"Ad-hoc clone of dataset '{source['name']}' with swaps: "
        + "; ".join(description_parts)
        + "."
    )
    new_dataset_id = assistant.store.create_dataset(name=name, description=description)

    set_id_cache: dict[tuple[str, str], str] = {}  # (old_set_id, new_doc_id) -> new_set_id
    cloned = 0
    carried = 0
    for a in annotations:
        doc_id = a.get("doc_id")
        if doc_id in swap_meta:
            new_doc_id = swaps[doc_id]
            old_set_id = a["set_id"]
            cache_key = (old_set_id, new_doc_id)
            if cache_key not in set_id_cache:
                label = f"{a.get('set_label') or 'set'}-clone-{suffix}"
                set_id_cache[cache_key] = assistant.store.get_or_create_annotation_set(
                    new_doc_id, label, description=f"Cloned from set {old_set_id}"
                )
            new_set_id = set_id_cache[cache_key]
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
        f"Created dataset '{name}' — {cloned} annotation(s) re-cloned across "
        f"{len(swaps)} swap(s), {carried} carried over unchanged."
    )
    return new_dataset_id, msg


def on_source_dataset_change(assistant: ChatAssistant | None, dataset_id: str | None):
    """Populate up to MAX_SWAP_ROWS rows for the docs in the chosen dataset.

    Each row outputs: (row visibility, label markdown, hidden source-doc-id,
    replacement dropdown reset). Returns 4 * MAX_SWAP_ROWS gr.update objects.
    """
    docs = _docs_in_dataset(assistant, dataset_id)
    updates: list = []
    for i in range(MAX_SWAP_ROWS):
        if i < len(docs):
            doc_id, name, count = docs[i]
            updates.append(gr.update(visible=True))
            updates.append(gr.update(value=f"**{name}** — {count} annotation(s)  \n`{doc_id}`"))
            updates.append(gr.update(value=doc_id))
            updates.append(gr.update(value=None))
        else:
            updates.append(gr.update(visible=False))
            updates.append(gr.update(value=""))
            updates.append(gr.update(value=""))
            updates.append(gr.update(value=None))
    if dataset_id and not docs:
        warning = "_Source dataset has no annotations linked to documents._"
    elif len(docs) > MAX_SWAP_ROWS:
        warning = (
            f"_Dataset references {len(docs)} documents; only the first "
            f"{MAX_SWAP_ROWS} are shown. Increase `MAX_SWAP_ROWS` to handle more._"
        )
    else:
        warning = ""
    updates.append(gr.update(value=warning))
    return updates


def on_apply(
    assistant: ChatAssistant | None,
    source_dataset_id: str | None,
    new_dataset_name: str | None,
    *row_values,
):
    """row_values is interleaved [src_id_0, repl_id_0, src_id_1, repl_id_1, ...]."""
    if assistant is None:
        return "_No assistant available._", gr.update()
    if not source_dataset_id:
        return "_Pick a source dataset._", gr.update()

    swaps: dict[str, str] = {}
    for i in range(MAX_SWAP_ROWS):
        src = (row_values[2 * i] or "").strip() if 2 * i < len(row_values) else ""
        repl = row_values[2 * i + 1] if 2 * i + 1 < len(row_values) else None
        if src and repl:
            if src in swaps:
                return (
                    f"_Source document `{src}` listed twice — each can be swapped only once._",
                    gr.update(),
                )
            swaps[src] = repl

    if not swaps:
        return "_Pick at least one replacement document._", gr.update()

    try:
        _, msg = _clone_dataset_swapping_docs(
            assistant,
            source_dataset_id,
            swaps,
            (new_dataset_name or "").strip() or None,
        )
    except Exception as e:
        logger.exception("ad-hoc multi-swap failed")
        return f"**Error:** {e}", gr.update()
    return f"**Done.** {msg}", gr.update(choices=_dataset_choices(assistant))


async def on_adhoc_tab_load(assistant: ChatAssistant | None):
    if assistant is None:
        assistant = ChatAssistant()
    doc_choices = _doc_choices(assistant)
    repl_updates = [gr.update(choices=doc_choices, value=None) for _ in range(MAX_SWAP_ROWS)]
    return (
        assistant,
        gr.update(choices=_dataset_choices(assistant), value=None),
        *repl_updates,
    )


def build_switch_file_tab(assistant_state: gr.State):
    gr.Markdown(
        "### Switch File ID\n"
        "A dataset can reference multiple documents. Pick the source dataset, "
        "then for any document listed below choose a replacement (leave blank "
        "to keep it). A new dataset is created with all selected swaps applied "
        f"in one pass — up to {MAX_SWAP_ROWS} swaps. **No validation — ad-hoc only.**"
    )
    source_dd = gr.Dropdown(label="Source dataset", choices=[], interactive=True)
    info_md = gr.Markdown("")

    rows: list[gr.Row] = []
    labels: list[gr.Markdown] = []
    src_ids: list[gr.Textbox] = []
    repls: list[gr.Dropdown] = []
    for i in range(MAX_SWAP_ROWS):
        with gr.Row(visible=False) as row:
            label_md = gr.Markdown("", elem_id=f"adhoc-src-label-{i}")
            src_id_tb = gr.Textbox(value="", visible=False)
            repl_dd = gr.Dropdown(
                label="Replace with…",
                choices=[],
                interactive=True,
                value=None,
            )
        rows.append(row)
        labels.append(label_md)
        src_ids.append(src_id_tb)
        repls.append(repl_dd)

    new_name = gr.Textbox(
        label="New dataset name (optional)",
        placeholder="Leave empty to auto-generate",
    )
    run_btn = gr.Button("Create new dataset with swaps", variant="primary")
    status_md = gr.Markdown("")

    change_outputs: list = []
    for row, label_md, src_id_tb, repl_dd in zip(rows, labels, src_ids, repls):
        change_outputs.extend([row, label_md, src_id_tb, repl_dd])
    change_outputs.append(info_md)

    source_dd.change(
        fn=on_source_dataset_change,
        inputs=[assistant_state, source_dd],
        outputs=change_outputs,
    )

    apply_inputs: list = [assistant_state, source_dd, new_name]
    for src_id_tb, repl_dd in zip(src_ids, repls):
        apply_inputs.extend([src_id_tb, repl_dd])
    run_btn.click(
        fn=on_apply,
        inputs=apply_inputs,
        outputs=[status_md, source_dd],
    )
    return source_dd, repls
