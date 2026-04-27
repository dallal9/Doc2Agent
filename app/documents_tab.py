"""Documents page: browse cached documents with PDF preview and enrichment metadata."""

from __future__ import annotations

import os

import gradio as gr

from src.chat import ChatAssistant
from src.logging import setup_logging

logger = setup_logging("documents_tab")


def _doc_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    return [
        (f"{d.file_name} ({d.page_count} pages)", d.doc_id)
        for d in assistant.list_cached_documents()
    ]


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


async def on_documents_tab_load(assistant: ChatAssistant | None):
    if assistant is None:
        assistant = ChatAssistant()
    return assistant, gr.update(choices=_doc_choices(assistant), value=None)


def build_documents_tab(assistant_state: gr.State):
    with gr.Row():
        with gr.Column(scale=1, min_width=280):
            gr.Markdown("### Documents")
            doc_dd = gr.Dropdown(label="Cached Documents", choices=[], interactive=True)
            metadata_md = gr.Markdown("_Select a document._")
        with gr.Column(scale=2):
            pdf_html = gr.HTML(_pdf_iframe(None))
            enrichment_md = gr.Markdown("")

    doc_dd.change(
        fn=_on_select_doc,
        inputs=[doc_dd, assistant_state],
        outputs=[pdf_html, metadata_md, enrichment_md],
    )
    return doc_dd, metadata_md, pdf_html, enrichment_md
