"""Datasets tab: build evaluation datasets from live chat sessions.

Milestone 2 of docs/local_doc2agent_part2_blueprint.md.
"""

from __future__ import annotations

import json

import gradio as gr

from src.chat import ChatAssistant
from src.logging import setup_logging

logger = setup_logging("datasets_tab")


# ---- choice builders ------------------------------------------------------


def _dataset_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    return [
        (f"{d['name']} ({d['annotation_count']} items)", d["dataset_id"])
        for d in assistant.store.list_datasets()
    ]


def _session_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    out = []
    for s in assistant.list_chat_sessions(limit=50):
        title = s.get("title", "Chat")
        out.append((f"{title} ({s.get('message_count', 0)} msgs)", s["session_id"]))
    return out


def _message_choices(
    assistant: ChatAssistant | None, session_id: str | None
) -> list[tuple[str, str]]:
    if assistant is None or not session_id:
        return []
    out = []
    for m in assistant.store.get_chat_messages(session_id):
        if m["role"] != "user":
            continue
        preview = m["content"].replace("\n", " ")
        if len(preview) > 80:
            preview = preview[:77] + "..."
        out.append((f"[{m['seq']}] {preview}", m["message_id"]))
    return out


def _format_dataset_preview(assistant: ChatAssistant | None, dataset_id: str | None) -> str:
    if assistant is None or not dataset_id:
        return "_Select a dataset to preview its annotations._"
    ds = assistant.store.get_dataset(dataset_id)
    if not ds:
        return "_Dataset not found._"
    anns = assistant.store.list_dataset_annotations(dataset_id)
    lines = [f"### {ds['name']}", ds.get("description") or "_No description_", ""]
    lines.append(f"**{len(anns)} annotation(s)**")
    for idx, a in enumerate(anns, 1):
        lines.append("")
        lines.append(f"**{idx}. Q:** {a['question']}")
        ans = a["answer"]
        lines.append(f"**A:** {ans[:400]}{'...' if len(ans) > 400 else ''}")
        doc_label = a.get("doc_name") or a.get("doc_id") or "—"
        lines.append(
            f"_doc: {doc_label} · set: {a.get('set_label', '—')} · spans: {len(a['spans'])}_"
        )
    return "\n".join(lines)


def _dataset_export_json(assistant: ChatAssistant | None, dataset_id: str | None) -> str:
    if assistant is None or not dataset_id:
        return ""
    ds = assistant.store.get_dataset(dataset_id)
    if not ds:
        return ""
    anns = assistant.store.list_dataset_annotations(dataset_id)
    payload = {
        "dataset_id": ds["dataset_id"],
        "name": ds["name"],
        "description": ds.get("description"),
        "annotations": [
            {
                "annotation_id": a["annotation_id"],
                "doc_id": a.get("doc_id"),
                "doc_name": a.get("doc_name"),
                "set_label": a.get("set_label"),
                "question": a["question"],
                "answer": a["answer"],
                "spans": [
                    {"kind": s["kind"], "page_num": s["page_num"], "text": s["quoted_text"]}
                    for s in a["spans"]
                ],
            }
            for a in anns
        ],
    }
    return json.dumps(payload, indent=2)


# ---- handlers -------------------------------------------------------------


def on_tab_load(assistant):
    if assistant is None:
        assistant = ChatAssistant()
    return (
        assistant,
        gr.update(choices=_dataset_choices(assistant), value=None),
        gr.update(choices=_session_choices(assistant), value=None),
        gr.update(choices=[], value=[]),
        "",
        "_Select a dataset to preview its annotations._",
    )


def on_refresh(assistant):
    if assistant is None:
        assistant = ChatAssistant()
    return (
        assistant,
        gr.update(choices=_dataset_choices(assistant)),
        gr.update(choices=_session_choices(assistant)),
    )


def on_create_dataset(name, description, assistant):
    if assistant is None:
        assistant = ChatAssistant()
    name = (name or "").strip()
    if not name:
        return (assistant, gr.update(), "Please enter a dataset name.", name, description)
    desc = (description or "").strip() or None
    dataset_id = assistant.store.create_dataset(name=name, description=desc)
    logger.info("created dataset name=%s id=%s", name, dataset_id)
    return (
        assistant,
        gr.update(choices=_dataset_choices(assistant), value=dataset_id),
        f"Created dataset **{name}**.",
        "",
        "",
    )


def on_delete_dataset(dataset_id, assistant):
    if assistant is None or not dataset_id:
        return (
            assistant,
            gr.update(),
            "No dataset selected.",
            "_Select a dataset to preview its annotations._",
        )
    ds = assistant.store.get_dataset(dataset_id)
    assistant.store.delete_dataset(dataset_id)
    name = ds["name"] if ds else dataset_id
    return (
        assistant,
        gr.update(choices=_dataset_choices(assistant), value=None),
        f"Deleted dataset **{name}**.",
        "_Select a dataset to preview its annotations._",
    )


def on_session_change(session_id, assistant):
    return gr.update(choices=_message_choices(assistant, session_id), value=[])


def on_mode_change(mode):
    return gr.update()


def on_export(session_id, dataset_id, mode, selected_messages, assistant):
    if assistant is None:
        return assistant, gr.update(), "No assistant.", gr.update()
    if not session_id:
        return assistant, gr.update(), "Select a session to export.", gr.update()
    if not dataset_id:
        return assistant, gr.update(), "Select or create a target dataset.", gr.update()
    if mode == "manual" and not selected_messages:
        return assistant, gr.update(), "Select at least one message (manual mode).", gr.update()
    result = assistant.export_session_to_dataset(
        session_id=session_id,
        dataset_id=dataset_id,
        mode=mode,
        selected_user_message_ids=list(selected_messages or []),
    )
    created, skipped = result["created"], result["skipped_no_doc"]
    logger.info("exported created=%d skipped_no_doc=%d dataset=%s", created, skipped, dataset_id)
    msg = f"Exported **{created}** annotation(s)."
    if skipped:
        msg += f" Skipped {skipped} turn(s) — no document attached to the session."
    return (
        assistant,
        gr.update(choices=_dataset_choices(assistant), value=dataset_id),
        msg,
        _format_dataset_preview(assistant, dataset_id),
    )


def on_dataset_change(dataset_id, assistant):
    return _format_dataset_preview(assistant, dataset_id), _dataset_export_json(
        assistant, dataset_id
    )


# ---- UI -------------------------------------------------------------------


def build_datasets_tab(assistant_state: gr.State | None = None):
    if assistant_state is None:
        assistant_state = gr.State(value=None)
    gr.Markdown("## Datasets — build evaluation sets from live chat sessions")

    with gr.Row():
        # left: dataset management
        with gr.Column(scale=1, min_width=280):
            gr.Markdown("### Datasets")
            dataset_dropdown = gr.Dropdown(label="Dataset", choices=[], interactive=True)
            with gr.Row():
                refresh_btn = gr.Button("Refresh", size="sm")
                delete_dataset_btn = gr.Button("Delete", variant="stop", size="sm")
            gr.Markdown("#### New dataset")
            new_name = gr.Textbox(label="Name", placeholder="e.g. policy-eval-v1")
            new_desc = gr.Textbox(label="Description (optional)", lines=2)
            create_btn = gr.Button("Create dataset", variant="primary")

        # middle: session export
        with gr.Column(scale=1, min_width=320):
            gr.Markdown("### Export chat session")
            session_dropdown = gr.Dropdown(label="Session", choices=[], interactive=True)
            mode_radio = gr.Radio(
                label="Export mode",
                choices=[("Auto (all turns)", "auto"), ("Manual (pick messages)", "manual")],
                value="auto",
            )
            message_checkboxes = gr.CheckboxGroup(
                label="User messages (used only in manual mode)",
                choices=[],
            )
            export_btn = gr.Button("Export to dataset", variant="primary")
            status_md = gr.Markdown("")

        # right: preview
        with gr.Column(scale=2, min_width=360):
            gr.Markdown("### Dataset preview")
            preview_md = gr.Markdown("_Select a dataset to preview its annotations._")
            export_json = gr.Textbox(
                label="Export JSON",
                value="",
                lines=10,
                max_lines=20,
                interactive=False,
            )

    # wiring
    refresh_btn.click(
        fn=on_refresh,
        inputs=[assistant_state],
        outputs=[assistant_state, dataset_dropdown, session_dropdown],
    )
    create_btn.click(
        fn=on_create_dataset,
        inputs=[new_name, new_desc, assistant_state],
        outputs=[assistant_state, dataset_dropdown, status_md, new_name, new_desc],
    )
    delete_dataset_btn.click(
        fn=on_delete_dataset,
        inputs=[dataset_dropdown, assistant_state],
        outputs=[assistant_state, dataset_dropdown, status_md, preview_md],
    )
    session_dropdown.change(
        fn=on_session_change,
        inputs=[session_dropdown, assistant_state],
        outputs=[message_checkboxes],
    )
    mode_radio.change(fn=on_mode_change, inputs=[mode_radio], outputs=[message_checkboxes])
    export_btn.click(
        fn=on_export,
        inputs=[
            session_dropdown,
            dataset_dropdown,
            mode_radio,
            message_checkboxes,
            assistant_state,
        ],
        outputs=[assistant_state, dataset_dropdown, status_md, preview_md],
    )
    dataset_dropdown.change(
        fn=on_dataset_change,
        inputs=[dataset_dropdown, assistant_state],
        outputs=[preview_md, export_json],
    )

    return (
        assistant_state,
        dataset_dropdown,
        session_dropdown,
        message_checkboxes,
        preview_md,
        export_json,
    )
