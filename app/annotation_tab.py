"""Annotate tab: PDF viewer + Q&A span annotations."""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import gradio as gr

from app.ui_components import render_table
from src.chat import ChatAssistant
from src.logging import setup_logging
from src.schemas import Span

logger = setup_logging("annotation_tab")

_ANNOTATOR_JS = Path(__file__).parent / "static" / "annotator.js"


def annotator_head_script() -> str:
    """Return the annotator JS wrapped in a <script> for one-time injection."""
    return f"<script>{_ANNOTATOR_JS.read_text(encoding='utf-8')}</script>"


def _doc_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    return [
        (f"{d.file_name} ({d.page_count} pages)", d.doc_id)
        for d in assistant.list_cached_documents()
    ]


def _set_choices(assistant: ChatAssistant | None, doc_id: str | None) -> list[tuple[str, str]]:
    if assistant is None or not doc_id:
        return []
    return [(f"{s.label}", s.set_id) for s in assistant.store.list_annotation_sets(doc_id)]


def _pdf_url(assistant: ChatAssistant | None, doc_id: str | None) -> str:
    if assistant is None or not doc_id:
        return ""
    meta = assistant.store.get_document_metadata(doc_id)
    if not meta or not meta.file_path:
        return ""
    abs_path = os.path.abspath(meta.file_path)
    return f"/gradio_api/file={abs_path}"


def _annotations_html(assistant: ChatAssistant | None, set_id: str | None) -> str:
    if assistant is None or not set_id:
        return "<em>Select a set to see annotations.</em>"
    anns = assistant.store.list_annotations(set_id)
    if not anns:
        return "<em>No annotations yet.</em>"
    rows: list[list[object]] = []
    for a in anns:
        spans = "; ".join(
            (
                f"[p.{s.page_num}]"
                if s.kind == "page"
                else f"p.{s.page_num}: {(s.quoted_text or '')[:80]}"
            )
            for s in a.spans
        )
        rows.append([a.question, a.answer, spans or "—"])
    return render_table(
        ["Question", "Answer", "Spans"],
        rows,
        empty_msg="No annotations yet.",
        max_height=420,
    )


def _annotation_id_choices(
    assistant: ChatAssistant | None, set_id: str | None
) -> list[tuple[str, str]]:
    if assistant is None or not set_id:
        return []
    return [
        (f"{a.annotation_id[:8]} — {a.question[:50]}", a.annotation_id)
        for a in assistant.store.list_annotations(set_id)
    ]


# ---- handlers -------------------------------------------------------------


async def on_upload(file_path, assistant):
    if file_path is None:
        yield assistant, gr.update(), gr.update(), "", "", "No file uploaded."
        return
    if assistant is None:
        assistant = ChatAssistant()
    original_name = os.path.basename(file_path)
    logger.info("annotation upload start name=%s path=%s", original_name, file_path)
    yield (
        assistant,
        gr.update(),
        gr.update(),
        "",
        "",
        f"Parsing {original_name}...",
    )
    t0 = time.perf_counter()
    result = await assistant.ingest_pdf(file_path, enrich=False, original_filename=original_name)
    elapsed = time.perf_counter() - t0
    doc_id = assistant.document_id
    url = _pdf_url(assistant, doc_id)
    logger.info(
        "annotation upload done name=%s doc_id=%s elapsed=%.2fs url=%s result=%s",
        original_name,
        doc_id,
        elapsed,
        url,
        result,
    )
    yield (
        assistant,
        gr.update(choices=_doc_choices(assistant), value=doc_id),
        gr.update(choices=_set_choices(assistant, doc_id), value=None),
        "<em>Select a set to see annotations.</em>",
        url,
        f"Ingested {original_name} in {elapsed:.1f}s.",
    )


def on_doc_change(doc_id, assistant):
    url = _pdf_url(assistant, doc_id)
    set_choices = _set_choices(assistant, doc_id)
    logger.info("doc change doc_id=%s url=%s sets=%d", doc_id, url, len(set_choices))
    return (
        url,
        gr.update(choices=set_choices, value=None),
        "<em>Select a set to see annotations.</em>",
        gr.update(choices=[], value=None),
    )


def on_new_set(doc_id, label, description, assistant):
    logger.info(
        "on_new_set called doc_id=%r label=%r desc=%r has_assistant=%s",
        doc_id,
        label,
        description,
        assistant is not None,
    )
    if not doc_id or not (label or "").strip() or assistant is None:
        return gr.update(), "Pick a document and enter a label."
    try:
        set_id = assistant.store.create_annotation_set(
            doc_id, label.strip(), (description or "").strip() or None
        )
    except Exception as exc:  # e.g. UNIQUE constraint
        logger.warning("create set failed doc_id=%s label=%s err=%s", doc_id, label, exc)
        return gr.update(), f"Could not create set: {exc}"
    logger.info("created set doc_id=%s set_id=%s label=%s", doc_id, set_id, label)
    choices = _set_choices(assistant, doc_id)
    return gr.update(choices=choices, value=set_id), f"Created set '{label}'."


def on_set_change(set_id, assistant):
    html = _annotations_html(assistant, set_id)
    ids = _annotation_id_choices(assistant, set_id)
    return html, gr.update(choices=ids, value=None)


def on_save_annotation(set_id, question, answer, spans_json, assistant):
    logger.info(
        "on_save_annotation called set_id=%r q_len=%d a_len=%d spans_json=%r has_assistant=%s",
        set_id,
        len(question or ""),
        len(answer or ""),
        (spans_json or "")[:200],
        assistant is not None,
    )
    if not set_id or assistant is None:
        return gr.update(), gr.update(), "Select a set first.", "", "", ""
    if not (question or "").strip() or not (answer or "").strip():
        return (
            gr.update(),
            gr.update(),
            "Question and answer required.",
            question,
            answer,
            spans_json,
        )
    try:
        raw = json.loads(spans_json or "[]")
    except json.JSONDecodeError:
        raw = []
    if not raw:
        return (
            gr.update(),
            gr.update(),
            "Add at least one span (text selection or page).",
            question,
            answer,
            spans_json,
        )
    spans = [
        Span(
            kind=s.get("kind", "text"),
            page_num=int(s["page_num"]),
            quoted_text=s.get("quoted_text"),
        )
        for s in raw
        if "page_num" in s
    ]
    aid = assistant.store.add_annotation(set_id, question.strip(), answer.strip(), spans)
    logger.info(
        "saved annotation set_id=%s ann_id=%s spans=%d q_len=%d a_len=%d",
        set_id,
        aid,
        len(spans),
        len(question),
        len(answer),
    )
    html = _annotations_html(assistant, set_id)
    ids = _annotation_id_choices(assistant, set_id)
    return html, gr.update(choices=ids, value=None), "Saved.", "", "", "[]"


def on_delete_annotation(annotation_id, set_id, assistant):
    if not annotation_id or assistant is None:
        return gr.update(), gr.update(), "Select an annotation to delete."
    logger.info("delete annotation ann_id=%s set_id=%s", annotation_id, set_id)
    assistant.store.delete_annotation(annotation_id)
    html = _annotations_html(assistant, set_id)
    ids = _annotation_id_choices(assistant, set_id)
    return html, gr.update(choices=ids, value=None), "Deleted."


def on_export(set_id, assistant):
    if not set_id or assistant is None:
        return None, "Select a set first."
    payload = assistant.store.export_annotation_set(set_id)
    if payload is None:
        return None, "Set not found."
    doc_name = (payload.get("document") or {}).get("file_name") or "document"
    safe_doc = Path(doc_name).stem.replace(" ", "_")
    safe_label = (payload.get("label") or "set").replace(" ", "_")
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix=f"{safe_doc}__{safe_label}__",
        delete=False,
        encoding="utf-8",
    )
    json.dump(payload, tmp, indent=2, ensure_ascii=False)
    tmp.close()
    logger.info(
        "exported set_id=%s file=%s annotations=%d",
        set_id,
        tmp.name,
        len(payload["annotations"]),
    )
    return tmp.name, f"Exported {len(payload['annotations'])} annotations."


def on_refresh_docs(assistant):
    return gr.update(choices=_doc_choices(assistant))


def _dataset_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    return [
        (f"{d['name']} ({d['annotation_count']} items)", d["dataset_id"])
        for d in assistant.store.list_datasets()
    ]


def on_refresh_datasets(assistant):
    return gr.update(choices=_dataset_choices(assistant))


def on_create_and_add_dataset(set_id, new_dataset_name, assistant):
    if assistant is None or not set_id:
        return gr.update(), "Select an annotation set first.", new_dataset_name
    name = (new_dataset_name or "").strip()
    if not name:
        return gr.update(), "Enter a name for the new dataset.", new_dataset_name
    dataset_id = assistant.store.create_dataset(name=name)
    count = assistant.store.add_annotation_set_to_dataset(dataset_id, set_id)
    logger.info(
        "created dataset %s and linked %d annotations from set %s", dataset_id, count, set_id
    )
    return (
        gr.update(choices=_dataset_choices(assistant), value=dataset_id),
        f"Created dataset **{name}** and added {count} annotation(s).",
        "",
    )


def on_add_set_to_dataset(set_id, dataset_id, assistant):
    if assistant is None or not set_id:
        return gr.update(), "Select an annotation set first."
    if not dataset_id:
        return gr.update(), "Select a target dataset."
    count = assistant.store.add_annotation_set_to_dataset(dataset_id, set_id)
    logger.info("linked %d annotations from set %s to dataset %s", count, set_id, dataset_id)
    return (
        gr.update(choices=_dataset_choices(assistant), value=dataset_id),
        f"Added {count} annotation(s) to dataset.",
    )


# ---- UI -------------------------------------------------------------------


def on_tab_load(assistant):
    """Populate doc dropdown when the annotation tab mounts."""
    choices = _doc_choices(assistant)
    logger.info("annotation tab load: docs=%d", len(choices))
    return gr.update(choices=choices, value=None)


def build_annotation_tab(assistant_state: gr.State):
    with gr.Row():
        with gr.Column(scale=1, min_width=280):
            gr.Markdown("### Document")
            upload = gr.File(label="Upload PDF", file_types=[".pdf"], type="filepath")
            doc_dd = gr.Dropdown(label="Document", choices=[], interactive=True)
            refresh_btn = gr.Button("Refresh documents", size="sm")

            gr.Markdown("### Annotation Set")
            set_dd = gr.Dropdown(label="Set", choices=[], interactive=True)
            new_set_label = gr.Textbox(label="New set label", placeholder="e.g. v1-gold")
            new_set_desc = gr.Textbox(label="Description (optional)")
            new_set_btn = gr.Button("Create set", size="sm")
            export_btn = gr.Button("Export JSON", size="sm", variant="primary")
            export_file = gr.File(label="Download", interactive=False)
            status_md = gr.Markdown("")

            gr.Markdown("### Add to dataset")
            dataset_dd = gr.Dropdown(label="Target dataset", choices=[], interactive=True)
            with gr.Row():
                refresh_datasets_btn = gr.Button("Refresh", size="sm")
                add_to_dataset_btn = gr.Button("Add set → dataset", variant="primary", size="sm")
            new_dataset_name = gr.Textbox(
                label="Or create new dataset", placeholder="name for a new dataset"
            )
            create_and_add_btn = gr.Button("Create & add set", size="sm")

        with gr.Column(scale=3):
            gr.HTML('<div id="d2a-viewer">Upload or pick a PDF to begin.</div>')

        with gr.Column(scale=2, min_width=320):
            gr.Markdown("### New annotation")
            question = gr.Textbox(label="Question", lines=2)
            answer = gr.Textbox(label="Answer", lines=2)
            gr.HTML(
                """
                <div id="d2a-span-controls"
                     style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:6px;">
                  <button type="button" data-d2a="add-text" style="padding:6px 10px;">
                    Add selection as text span(s)
                  </button>
                  <input id="d2a-page-input" type="number" min="1" placeholder="page #"
                         style="width:80px;padding:6px;"/>
                  <button type="button" data-d2a="add-page" style="padding:6px 10px;">
                    Add page span
                  </button>
                  <button type="button" data-d2a="clear" style="padding:6px 10px;">
                    Clear
                  </button>
                </div>
                <div id="d2a-staged"></div>
                """
            )
            spans_buffer = gr.Textbox(
                value="[]",
                elem_id="d2a-spans-buffer",
                elem_classes=["d2a-hidden"],
                interactive=True,
                label="staged spans (internal)",
            )
            save_btn = gr.Button("Save annotation", variant="primary")

            gr.Markdown("### Annotations in set")
            ann_table = gr.HTML(value="<em>Select a set to see annotations.</em>")
            delete_dd = gr.Dropdown(label="Select annotation to delete", choices=[])
            delete_btn = gr.Button("Delete selected annotation", variant="stop", size="sm")

    pdf_url_state = gr.Textbox(
        value="",
        elem_id="d2a-pdf-url",
        elem_classes=["d2a-hidden"],
        label="pdf url (internal)",
    )
    gr.HTML("<style>.d2a-hidden { display: none !important; }</style>")

    # wiring
    upload.upload(
        fn=on_upload,
        inputs=[upload, assistant_state],
        outputs=[assistant_state, doc_dd, set_dd, ann_table, pdf_url_state, status_md],
    ).then(
        fn=None,
        inputs=[pdf_url_state],
        js="(url) => { console.log('[d2a] upload.then loadPdf', url); if (url && window.doc2agent) window.doc2agent.loadPdf(url); }",
    )
    refresh_btn.click(fn=on_refresh_docs, inputs=[assistant_state], outputs=[doc_dd])

    doc_dd.change(
        fn=on_doc_change,
        inputs=[doc_dd, assistant_state],
        outputs=[pdf_url_state, set_dd, ann_table, delete_dd],
    ).then(
        fn=None,
        inputs=[pdf_url_state],
        js="(url) => { if (url && window.doc2agent) window.doc2agent.loadPdf(url); }",
    )

    new_set_btn.click(
        fn=on_new_set,
        inputs=[doc_dd, new_set_label, new_set_desc, assistant_state],
        outputs=[set_dd, status_md],
    )

    set_dd.change(
        fn=on_set_change,
        inputs=[set_dd, assistant_state],
        outputs=[ann_table, delete_dd],
    )

    save_btn.click(
        fn=on_save_annotation,
        inputs=[set_dd, question, answer, spans_buffer, assistant_state],
        outputs=[ann_table, delete_dd, status_md, question, answer, spans_buffer],
    ).then(
        fn=None,
        js="() => { if (window.doc2agent) window.doc2agent.clearStaged(); }",
    )

    delete_btn.click(
        fn=on_delete_annotation,
        inputs=[delete_dd, set_dd, assistant_state],
        outputs=[ann_table, delete_dd, status_md],
    )

    export_btn.click(
        fn=on_export,
        inputs=[set_dd, assistant_state],
        outputs=[export_file, status_md],
    )

    refresh_datasets_btn.click(
        fn=on_refresh_datasets,
        inputs=[assistant_state],
        outputs=[dataset_dd],
    )
    add_to_dataset_btn.click(
        fn=on_add_set_to_dataset,
        inputs=[set_dd, dataset_dd, assistant_state],
        outputs=[dataset_dd, status_md],
    )
    create_and_add_btn.click(
        fn=on_create_and_add_dataset,
        inputs=[set_dd, new_dataset_name, assistant_state],
        outputs=[dataset_dd, status_md, new_dataset_name],
    )

    return doc_dd, dataset_dd
