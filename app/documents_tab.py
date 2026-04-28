"""Documents page: browse cached documents with PDF preview and enrichment metadata."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile

import gradio as gr

from app.pdf_ingest import ingest_upload_pdf_stream
from src.chat import ChatAssistant

USE_ENRICHMENT = os.getenv("USE_ENRICHMENT", "true").lower() == "true"
SHOW_INGESTION_LOGS = os.getenv("SHOW_INGESTION_LOGS", "false").lower() == "true"


def _doc_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    choices = []
    for doc in assistant.list_cached_documents():
        cache_count = assistant.store.get_query_count_for_document(doc.doc_id)
        cache_label = f" ({cache_count} cached)" if cache_count > 0 else ""
        label = f"{doc.file_name} ({doc.page_count} pages){cache_label}"
        choices.append((label, doc.doc_id))
    return choices


def _pdf_iframe(path: str | None) -> str:
    if not path or not os.path.exists(path):
        return "<div style='padding:1em; opacity:0.7'>No PDF available.</div>"
    abs_path = os.path.abspath(path)
    url = f"/gradio_api/file={abs_path}"
    return (
        f"<iframe src='{url}' style='width:100%; height:720px; border:1px solid "
        f"var(--border-color-primary, #ccc); border-radius:6px;'></iframe>"
    )


def _format_metadata(assistant: ChatAssistant | None, doc_id: str | None) -> str:
    if assistant is None or not doc_id:
        return "_Select a document._"
    meta = assistant.store.get_document_metadata(doc_id)
    if not meta:
        return "_Document not found._"
    size_kb = (meta.file_size_bytes or 0) / 1024
    rows = [
        f"### {meta.file_name}",
        "",
        f"- **Doc ID:** `{meta.doc_id}`",
        f"- **Pages:** {meta.page_count}",
        f"- **Size:** {size_kb:,.1f} KB",
        f"- **Title:** {meta.title or '—'}",
        f"- **Author:** {meta.author or '—'}",
        f"- **Subject:** {meta.subject or '—'}",
        f"- **Modified:** {meta.file_mod_time or '—'}",
        f"- **Hash:** `{(meta.file_hash or '')[:16]}…`",
        f"- **Path:** `{meta.file_path}`",
    ]
    return "\n".join(rows)


def _format_enrichment(assistant: ChatAssistant | None, doc_id: str | None) -> str:
    if assistant is None or not doc_id:
        return ""
    pages = assistant.store.get_all_pages(doc_id)
    if not pages:
        return "_No pages stored._"

    total = len(pages)
    flag_counts = {
        "names": sum(p.contains_names for p in pages),
        "dates": sum(p.contains_dates for p in pages),
        "locations": sum(p.contains_locations for p in pages),
        "signatures": sum(p.contains_signatures for p in pages),
        "personal_info": sum(p.contains_personal_info for p in pages),
        "tables": sum(p.has_tables for p in pages),
        "images": sum(p.has_images for p in pages),
    }
    languages: dict[str, int] = {}
    keywords: dict[str, int] = {}
    for p in pages:
        for lang in p.languages or []:
            languages[lang] = languages.get(lang, 0) + 1
        for kw in p.keywords or []:
            keywords[kw] = keywords.get(kw, 0) + 1
    top_keywords = sorted(keywords.items(), key=lambda x: -x[1])[:15]

    out = ["### Enrichment Summary", ""]
    out.append(f"**Pages:** {total}")
    out.append("")
    out.append("**Flag counts (pages):**")
    for k, v in flag_counts.items():
        out.append(f"- {k}: {v}")
    if languages:
        out.append("")
        lang_str = ", ".join(f"{l} ({c})" for l, c in languages.items())
        out.append(f"**Languages:** {lang_str}")
    if top_keywords:
        out.append("")
        out.append("**Top keywords:** " + ", ".join(f"{k} ({c})" for k, c in top_keywords))

    out.append("")
    out.append("### Per-page details")
    for p in pages[:50]:
        flags = []
        if p.contains_names:
            flags.append("names")
        if p.contains_dates:
            flags.append("dates")
        if p.contains_locations:
            flags.append("locations")
        if p.contains_signatures:
            flags.append("signatures")
        if p.contains_personal_info:
            flags.append("personal_info")
        if p.has_tables:
            flags.append("tables")
        if p.has_images:
            flags.append("images")
        flag_str = ", ".join(flags) if flags else "—"
        heading_str = "; ".join(h.text for h in (p.headings or [])[:3]) or "—"
        kw_str = ", ".join((p.keywords or [])[:6]) or "—"
        out.append(
            f"- **p.{p.page_num}** · {p.word_count} words · flags: {flag_str} · "
            f"headings: {heading_str} · keywords: {kw_str}"
        )
    if total > 50:
        out.append(f"_…and {total - 50} more pages._")
    return "\n".join(out)


def _on_select_doc(doc_id: str | None, assistant: ChatAssistant | None):
    if assistant is None or not doc_id:
        return _pdf_iframe(None), _format_metadata(None, None), ""
    meta = assistant.store.get_document_metadata(doc_id)
    pdf_html = _pdf_iframe(meta.file_path if meta else None)
    return pdf_html, _format_metadata(assistant, doc_id), _format_enrichment(assistant, doc_id)


async def on_documents_upload(file_paths, assistant: ChatAssistant | None):
    """Upload one or many PDFs.

    Files are ingested in parallel up to `DOC_INGESTION_CONCURRENCY`; pages
    within each document up to `PAGE_INGESTION_CONCURRENCY`. Both are set in
    System config.
    """
    if not file_paths or assistant is None:
        yield (
            assistant,
            "No file uploaded.",
            gr.update(),
            _pdf_iframe(None),
            _format_metadata(None, None),
            "",
        )
        return

    if isinstance(file_paths, str):
        file_paths = [file_paths]

    total = len(file_paths)
    multi = total > 1
    file_concurrency = max(1, int(os.getenv("DOC_INGESTION_CONCURRENCY", "1") or "1"))
    file_sem = asyncio.Semaphore(file_concurrency)
    counter = {"done": 0}
    last_doc_id = None

    async def _ingest_one(path: str) -> tuple[str, str]:
        nonlocal last_doc_id
        name = os.path.basename(path)
        async with file_sem:
            result = ""
            async for event in ingest_upload_pdf_stream(
                assistant,
                path,
                name,
                use_enrichment=USE_ENRICHMENT,
                show_ingestion_logs=SHOW_INGESTION_LOGS,
                # When uploading a batch, don't race on the assistant's
                # active-document state — set only the last completed one.
                set_active=not multi,
            ):
                kind, *rest = event
                if kind == "done":
                    result = str(rest[0])
            counter["done"] += 1
            if not multi:
                last_doc_id = assistant.document_id
            else:
                meta = assistant.store.get_document_by_path(path)
                if meta:
                    last_doc_id = meta.doc_id
            return name, result

    yield (
        assistant,
        f"Ingesting {total} file(s) (up to {file_concurrency} in parallel)...",
        gr.update(),
        _pdf_iframe(None),
        _format_metadata(None, None),
        "",
    )

    tasks = [asyncio.create_task(_ingest_one(p)) for p in file_paths]
    summaries: list[str] = []
    for coro in asyncio.as_completed(tasks):
        name, result = await coro
        summaries.append(f"- **{name}**: {result}")
        yield (
            assistant,
            f"Ingested {counter['done']}/{total} file(s)...",
            gr.update(choices=_doc_choices(assistant)),
            _pdf_iframe(None),
            _format_metadata(None, None),
            "",
        )

    choices = _doc_choices(assistant)
    pdf_html, meta_md, enrich_md = _on_select_doc(last_doc_id, assistant)
    summary_md = f"✅ Ingested {total} file(s).\n\n" + "\n".join(summaries)
    yield (
        assistant,
        summary_md,
        gr.update(choices=choices, value=last_doc_id),
        pdf_html,
        meta_md,
        enrich_md,
    )


def on_documents_delete(doc_id: str | None, assistant: ChatAssistant | None):
    if not doc_id or assistant is None:
        return (
            assistant,
            "No document selected.",
            gr.update(),
            _pdf_iframe(None),
            _format_metadata(None, None),
            "",
        )
    meta = assistant.store.get_document_metadata(doc_id)
    fname = meta.file_name if meta else doc_id
    result_msg = assistant.delete_cached_document(doc_id)
    choices = _doc_choices(assistant)
    return (
        assistant,
        f"Deleted **{fname}**. {result_msg}",
        gr.update(choices=choices, value=None),
        _pdf_iframe(None),
        _format_metadata(None, None),
        "",
    )


def on_documents_flush_doc(doc_id: str | None, assistant: ChatAssistant | None):
    if assistant is None or not doc_id:
        return assistant, "No document selected.", gr.update()
    count = assistant.store.flush_query_cache(doc_id)
    meta = assistant.store.get_document_metadata(doc_id)
    fname = meta.file_name if meta else doc_id
    choices = _doc_choices(assistant)
    return (
        assistant,
        f"Flushed {count} cached queries for **{fname}**.",
        gr.update(choices=choices, value=doc_id),
    )


def on_documents_flush_all(assistant: ChatAssistant | None):
    if assistant is None:
        return assistant, "", gr.update()
    count = assistant.store.flush_query_cache(None)
    choices = _doc_choices(assistant)
    return (
        assistant,
        f"Flushed {count} cached queries (all documents).",
        gr.update(choices=choices),
    )


def on_documents_export_json(doc_id: str | None, assistant: ChatAssistant | None):
    """Dump the full DocumentSchema (metadata + enriched pages) — i.e. what
    the agents see when this document is referenced — to a temp JSON file
    and return its path for download."""
    if assistant is None or not doc_id:
        return None
    doc = assistant.store.load_document(doc_id)
    if doc is None:
        return None
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", doc.metadata.file_name or doc_id)
    base = safe_name.rsplit(".", 1)[0] or doc_id
    tmp_dir = tempfile.mkdtemp(prefix="d2a_export_")
    out_path = os.path.join(tmp_dir, f"{base}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(doc.model_dump_json(indent=2))
    return out_path


async def on_documents_tab_load(assistant: ChatAssistant | None):
    if assistant is None:
        assistant = ChatAssistant()
    return assistant, gr.update(choices=_doc_choices(assistant), value=None)


def build_documents_tab(assistant_state: gr.State):
    with gr.Row():
        with gr.Column(scale=1, min_width=280):
            gr.Markdown("### Documents")
            file_upload = gr.File(
                label="Upload PDF(s)",
                file_types=[".pdf"],
                type="filepath",
                file_count="multiple",
            )
            ops_status_md = gr.Markdown("")
            doc_dd = gr.Dropdown(label="Cached Documents", choices=[], interactive=True)
            with gr.Row():
                delete_btn = gr.Button("Delete", variant="stop", size="sm")
                download_json_btn = gr.DownloadButton(
                    "Download JSON", size="sm", visible=True
                )
            with gr.Row():
                flush_btn = gr.Button("Clear Cached Replies (Selected Doc)", size="sm")
                flush_all_btn = gr.Button(
                    "Clear Cached Replies (All Docs)", variant="stop", size="sm"
                )
            metadata_md = gr.Markdown("_Select a document._")
        with gr.Column(scale=2):
            pdf_html = gr.HTML(_pdf_iframe(None))
            enrichment_md = gr.Markdown("")

    doc_dd.change(
        fn=_on_select_doc,
        inputs=[doc_dd, assistant_state],
        outputs=[pdf_html, metadata_md, enrichment_md],
    )

    file_upload.upload(
        fn=on_documents_upload,
        inputs=[file_upload, assistant_state],
        outputs=[
            assistant_state,
            ops_status_md,
            doc_dd,
            pdf_html,
            metadata_md,
            enrichment_md,
        ],
    )

    delete_btn.click(
        fn=on_documents_delete,
        inputs=[doc_dd, assistant_state],
        outputs=[
            assistant_state,
            ops_status_md,
            doc_dd,
            pdf_html,
            metadata_md,
            enrichment_md,
        ],
    )

    download_json_btn.click(
        fn=on_documents_export_json,
        inputs=[doc_dd, assistant_state],
        outputs=[download_json_btn],
    )

    flush_btn.click(
        fn=on_documents_flush_doc,
        inputs=[doc_dd, assistant_state],
        outputs=[assistant_state, ops_status_md, doc_dd],
    )

    flush_all_btn.click(
        fn=on_documents_flush_all,
        inputs=[assistant_state],
        outputs=[assistant_state, ops_status_md, doc_dd],
    )

    return doc_dd, metadata_md, pdf_html, enrichment_md
