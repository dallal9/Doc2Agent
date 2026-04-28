import asyncio
import os

import gradio as gr

from src.bootstrap import init_app

init_app()

from app.adhoc_tab import build_switch_file_tab, on_adhoc_tab_load
from app.agent_config_tab import build_agent_config_tab
from app.annotation_tab import annotator_head_script, build_annotation_tab, on_tab_load
from app.dashboard_tab import (
    build_data_dashboard_tab,
    build_evaluation_dashboard_tab,
    on_dashboard_load,
)
from app.datasets_tab import build_datasets_tab
from app.datasets_tab import on_tab_load as on_datasets_tab_load
from app.documents_tab import build_documents_tab, on_documents_tab_load
from app.evaluation_tab import (
    build_execution_run_tab,
    build_judge_run_tab,
    build_metrics_tab,
    on_judge_tab_load,
    on_metrics_tab_load,
)
from app.evaluation_tab import on_tab_load as on_evaluation_tab_load
from app.pdf_ingest import ingest_upload_pdf_stream
from app.system_tab import build_system_tab
from app.utils import ChatResult, render_chat_with_cache
from src.agents import run_agent
from src.chat import ChatAssistant
from src.logging import setup_logging

logger = setup_logging("gradio_app")

SHOW_REASONING = os.getenv("SHOW_REASONING", "true").lower() == "true"
USE_ENRICHMENT = os.getenv("USE_ENRICHMENT", "true").lower() == "true"
SHOW_INGESTION_LOGS = os.getenv("SHOW_INGESTION_LOGS", "false").lower() == "true"
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Doc2Agent")
LOGO_DARK_PATH = "public/logo_dark.png"
LOGO_LIGHT_PATH = "public/logo_light.png"

_LOGO_THEME_STYLE = """
<style>
    .logo-dark { display: none; }
    .dark .logo-dark { display: block; }
    .dark .logo-light { display: none; }
    .doc2agent-hero-logo { max-width: 360px; margin: 0 auto; }
</style>
"""


def _doc2agent_logo_imgs() -> None:
    gr.Image(
        value=LOGO_LIGHT_PATH,
        show_label=False,
        container=False,
        interactive=False,
        buttons=[],
        elem_classes="doc2agent-logo logo-light",
        width="100%",
    )
    gr.Image(
        value=LOGO_DARK_PATH,
        show_label=False,
        container=False,
        interactive=False,
        buttons=[],
        elem_classes="doc2agent-logo logo-dark",
        width="100%",
    )


def _doc2agent_logo_block(*, hero: bool = False) -> None:
    """Light/dark theme-aware logos; use hero=True on the landing page for a centered max width."""
    gr.HTML(_LOGO_THEME_STYLE)
    if hero:
        with gr.Column(elem_classes="doc2agent-hero-logo"):
            _doc2agent_logo_imgs()
    else:
        _doc2agent_logo_imgs()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_bot_message(result: ChatResult) -> str:
    """Format a ChatResult into a markdown message with optional collapsible thinking."""
    parts = []
    has_details = result.reasoning or result.tool_lines
    if has_details:
        inner_parts = []
        if result.is_cached:
            inner_parts.append("**Cached Result**")
        if result.reasoning:
            inner_parts.append(result.reasoning)
        for line in result.tool_lines:
            inner_parts.append(line)
        if inner_parts:
            inner = "\n\n".join(inner_parts)
            parts.append(f"<details><summary>Thinking...</summary>\n\n{inner}\n\n</details>")
    elif result.is_cached:
        parts.append("*Cached Result*")
    elif result.usage_summary:
        parts.append(f"*{result.usage_summary}*")
    parts.append(result.reply)
    return "\n\n".join(parts)


def _doc_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    """Build (label, doc_id) pairs for the document dropdown."""
    if assistant is None:
        return []
    docs = assistant.list_cached_documents()
    choices = []
    for doc in docs:
        cache_count = assistant.store.get_query_count_for_document(doc.doc_id)
        cache_label = f" ({cache_count} cached)" if cache_count > 0 else ""
        label = f"{doc.file_name} ({doc.page_count} pages){cache_label}"
        choices.append((label, doc.doc_id))
    return choices


def _upsert_last_assistant(history, content: str):
    if history and history[-1].get("role") == "assistant":
        history[-1] = {"role": "assistant", "content": content}
        return history
    return history + [{"role": "assistant", "content": content}]


def _session_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    sessions = assistant.list_chat_sessions(limit=30)
    choices = []
    for session in sessions:
        title = session.get("title", "Chat")
        msg_count = session.get("message_count", 0)
        label = f"{title} ({msg_count} msgs)"
        choices.append((label, session["session_id"]))
    return choices


def _input_update(enabled: bool):
    return gr.update(value="", interactive=enabled)


def _button_update(enabled: bool):
    return gr.update(interactive=enabled)


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


async def on_app_load():
    """Initialise a ChatAssistant when the page loads."""
    import time as _t

    t0 = _t.perf_counter()
    assistant = ChatAssistant()
    t1 = _t.perf_counter()
    session_id = assistant.create_chat_session()
    choices = _doc_choices(assistant)
    sessions = _session_choices(assistant)
    logger.info(
        "on_app_load: assistant_init=%.2fs session+choices=%.2fs total=%.2fs",
        t1 - t0,
        _t.perf_counter() - t1,
        _t.perf_counter() - t0,
    )
    welcome = [
        {
            "role": "assistant",
            "content": f"Hi! Upload a PDF or select a cached document to get started.",
        }
    ]
    return (
        assistant,
        welcome,
        gr.update(choices=choices, value=None),
        "No file attached.",
        session_id,
        gr.update(choices=sessions, value=session_id),
    )


async def on_upload(file_path, assistant, history):
    if file_path is None or assistant is None:
        yield assistant, None, None, "No file uploaded.", history, gr.update()
        return

    original_name = os.path.basename(file_path)
    history = history + [
        {"role": "assistant", "content": f"Ingesting **{original_name}**..."},
    ]
    yield assistant, original_name, file_path, f"Ingesting {original_name}...", history, gr.update()

    result = ""
    async for event in ingest_upload_pdf_stream(
        assistant,
        file_path,
        original_name,
        use_enrichment=USE_ENRICHMENT,
        show_ingestion_logs=SHOW_INGESTION_LOGS,
    ):
        kind, *rest = event
        if kind == "progress":
            current, total = rest[0], rest[1]
            history = _upsert_last_assistant(
                history, f"Ingesting **{original_name}**... ({current}/{total})"
            )
            yield assistant, original_name, file_path, f"Ingesting {original_name}...", history, gr.update()
        else:
            result = str(rest[0])

    history[-1] = {"role": "assistant", "content": f"**{original_name}** loaded. {result}"}
    choices = _doc_choices(assistant)
    yield (
        assistant,
        original_name,
        file_path,
        f"**Attached:** {original_name}",
        history,
        gr.update(choices=choices, value=assistant.document_id),
    )


async def on_send(message, history, assistant, file_name, file_path, session_id):
    if not message or not message.strip() or assistant is None:
        yield (
            _input_update(True),
            history,
            assistant,
            file_name,
            file_path,
            session_id,
            _button_update(True),
        )
        return

    if not session_id:
        session_id = assistant.create_chat_session()
    assistant.session_id = session_id

    history = history + [{"role": "user", "content": message}]
    assistant.save_chat_message("user", message)
    history = _upsert_last_assistant(history, "*Checking cache...*")
    yield (
        _input_update(False),
        history,
        assistant,
        file_name,
        file_path,
        session_id,
        _button_update(False),
    )

    cached = assistant.get_cached_query(message)
    if cached is None:
        history = _upsert_last_assistant(history, "*Running main agent...*")
    else:
        history = _upsert_last_assistant(history, "*Cache hit. Preparing response...*")
    yield (
        _input_update(False),
        history,
        assistant,
        file_name,
        file_path,
        session_id,
        _button_update(False),
    )

    result = await render_chat_with_cache(
        assistant=assistant,
        user_message=message,
        run_agent=run_agent,
        show_reasoning=SHOW_REASONING,
    )
    assistant.finalize_turn(result.reply)
    formatted = _format_bot_message(result)
    assistant.save_chat_message("assistant", formatted)
    history = _upsert_last_assistant(history, formatted)
    yield (
        _input_update(True),
        history,
        assistant,
        file_name,
        file_path,
        session_id,
        _button_update(True),
    )


async def on_load_doc(doc_id, assistant, history):
    if not doc_id or assistant is None:
        return assistant, None, None, "No document selected.", history

    result_msg = assistant.load_cached_document(doc_id)
    assistant.sync_session_document()
    meta = assistant.store.get_document_metadata(doc_id)
    file_name = meta.file_name if meta else doc_id
    file_path = meta.file_path if meta else None
    history = history + [{"role": "assistant", "content": result_msg}]
    return assistant, file_name, file_path, f"**Attached:** {file_name}", history


async def on_clean_empty_sessions(assistant, session_id, history):
    if assistant is None:
        return history, gr.update()
    count = assistant.store.delete_empty_chat_sessions(except_session_id=session_id)
    history = history + [{"role": "assistant", "content": f"Deleted {count} empty session(s)."}]
    return history, gr.update(choices=_session_choices(assistant), value=session_id)


async def on_detach(assistant):
    if assistant is None:
        return assistant, None, None, "No file attached."
    assistant.text = ""
    assistant.document = None
    assistant.enriched_doc = None
    assistant.document_id = None
    assistant.sync_session_document()
    return assistant, None, None, "No file attached."


async def on_new_session(assistant, current_file_name):
    if assistant is None:
        assistant = ChatAssistant()
    session_id = assistant.create_chat_session()
    assistant.history = []
    sessions = _session_choices(assistant)
    status = "Started a new session."
    if current_file_name:
        status += f" **Attached:** {current_file_name}"
    return assistant, session_id, [], status, gr.update(choices=sessions, value=session_id)


async def on_load_session(session_id, assistant):
    if not session_id or assistant is None:
        return assistant, None, None, "No session selected.", [], None, gr.update(), gr.update()

    session = assistant.store.get_chat_session(session_id)
    if not session:
        return assistant, None, None, "Session not found.", [], None, gr.update(), gr.update()

    messages = assistant.load_chat_session(session_id)
    file_name = None
    file_path = None
    status = "No file attached."
    doc_id = session.get("doc_id")
    if doc_id:
        assistant.load_cached_document(doc_id)
        meta = assistant.store.get_document_metadata(doc_id)
        if meta:
            file_name = meta.file_name
            file_path = meta.file_path
            status = f"**Attached:** {file_name}"
    sessions = _session_choices(assistant)
    docs = _doc_choices(assistant)
    return (
        assistant,
        file_name,
        file_path,
        status,
        messages,
        session_id,
        gr.update(choices=sessions, value=session_id),
        gr.update(choices=docs, value=doc_id),
    )


async def on_clear_session_history(assistant, session_id, current_file_name):
    if assistant is None or not session_id:
        return assistant, [], "No session selected."
    cleared = assistant.clear_current_session_messages()
    status = f"Cleared {cleared} messages from current session."
    if current_file_name:
        status += f" **Attached:** {current_file_name}"
    return assistant, [], status


async def on_clear_all_sessions(assistant, current_file_name):
    if assistant is None:
        return assistant, None, [], gr.update(), "No active assistant."
    cleared = assistant.clear_all_sessions()
    session_id = assistant.create_chat_session()
    sessions = _session_choices(assistant)
    status = f"Cleared {cleared} sessions."
    if current_file_name:
        status += f" **Attached:** {current_file_name}"
    return assistant, session_id, [], gr.update(choices=sessions, value=session_id), status


# ---------------------------------------------------------------------------
# Build UI
# ---------------------------------------------------------------------------


def build_chat_tab():
    """Build the 'Chat with Documents' tab contents. Returns components needed for wiring."""
    # -- State --
    assistant_state = gr.State(value=None)
    file_name_state = gr.State(value=None)
    file_path_state = gr.State(value=None)
    session_id_state = gr.State(value=None)

    with gr.Row():
        # -- Sidebar --
        with gr.Column(scale=1, min_width=260):
            _doc2agent_logo_block(hero=False)
            gr.Markdown(f"### {ASSISTANT_NAME}")
            file_upload = gr.File(label="Upload PDF", file_types=[".pdf"], type="filepath")
            status_md = gr.Markdown("No file attached.")
            doc_dropdown = gr.Dropdown(label="Cached Documents", choices=[], interactive=True)
            load_btn = gr.Button("Load", size="sm")
            detach_btn = gr.Button("Detach File", size="sm")
            gr.Markdown("### Sessions")
            session_dropdown = gr.Dropdown(label="Recent Sessions", choices=[], interactive=True)
            with gr.Row():
                new_session_btn = gr.Button("New Session", size="sm")
                clear_session_btn = gr.Button("Clear Session Messages", size="sm")
            with gr.Row():
                clean_empty_sessions_btn = gr.Button(
                    "Clean Empty Sessions (Except Current)", size="sm"
                )
                clear_all_sessions_btn = gr.Button("Clear All Sessions", variant="stop", size="sm")

        # -- Chat area --
        with gr.Column(scale=3):
            chatbot = gr.Chatbot(
                height=600,
                buttons=["copy"],
            )
            with gr.Row():
                msg_input = gr.Textbox(
                    placeholder="Ask about your document...",
                    show_label=False,
                    scale=9,
                )
                send_btn = gr.Button("Send", variant="primary", scale=1)

    # -- Wiring --

    # Page load
    chatbot.change(
        fn=None,
        js="() => { const el = document.querySelector('.chatbot'); if(el) el.scrollTop = el.scrollHeight; }",
    )

    load_event = gr.on(
        triggers=[msg_input.submit, send_btn.click],
        fn=on_send,
        inputs=[
            msg_input,
            chatbot,
            assistant_state,
            file_name_state,
            file_path_state,
            session_id_state,
        ],
        outputs=[
            msg_input,
            chatbot,
            assistant_state,
            file_name_state,
            file_path_state,
            session_id_state,
            send_btn,
        ],
    )

    file_upload.upload(
        fn=on_upload,
        inputs=[file_upload, assistant_state, chatbot],
        outputs=[
            assistant_state,
            file_name_state,
            file_path_state,
            status_md,
            chatbot,
            doc_dropdown,
        ],
    )

    load_btn.click(
        fn=on_load_doc,
        inputs=[doc_dropdown, assistant_state, chatbot],
        outputs=[assistant_state, file_name_state, file_path_state, status_md, chatbot],
    )
    doc_dropdown.change(
        fn=on_load_doc,
        inputs=[doc_dropdown, assistant_state, chatbot],
        outputs=[assistant_state, file_name_state, file_path_state, status_md, chatbot],
    )

    detach_btn.click(
        fn=on_detach,
        inputs=[assistant_state],
        outputs=[assistant_state, file_name_state, file_path_state, status_md],
    )
    new_session_btn.click(
        fn=on_new_session,
        inputs=[assistant_state, file_name_state],
        outputs=[assistant_state, session_id_state, chatbot, status_md, session_dropdown],
    )
    session_dropdown.change(
        fn=on_load_session,
        inputs=[session_dropdown, assistant_state],
        outputs=[
            assistant_state,
            file_name_state,
            file_path_state,
            status_md,
            chatbot,
            session_id_state,
            session_dropdown,
            doc_dropdown,
        ],
    )
    clear_session_btn.click(
        fn=on_clear_session_history,
        inputs=[assistant_state, session_id_state, file_name_state],
        outputs=[assistant_state, chatbot, status_md],
    )
    clear_all_sessions_btn.click(
        fn=on_clear_all_sessions,
        inputs=[assistant_state, file_name_state],
        outputs=[assistant_state, session_id_state, chatbot, session_dropdown, status_md],
    )
    clean_empty_sessions_btn.click(
        fn=on_clean_empty_sessions,
        inputs=[assistant_state, session_id_state, chatbot],
        outputs=[chatbot, session_dropdown],
    )

    return assistant_state, chatbot, doc_dropdown, status_md, session_id_state, session_dropdown


def _build_homepage():
    _doc2agent_logo_block(hero=True)
    gr.Markdown(
        f'<div style="text-align:center">'
        f"<h1>{ASSISTANT_NAME}</h1>"
        "<p>Intelligent PDF assistant with a multi-agent architecture — local-first, "
        "privacy-preserving Q&A over your documents.</p></div>"
    )
    gr.Markdown(
        '<p style="text-align:center; opacity:0.85; font-size:0.95em">'
        "Use the top bar or the buttons below to open a workspace.</p>"
    )
    with gr.Row():
        gr.Button("Chat", link="./chat", variant="primary", size="lg", scale=1)
        gr.Button("Documents", link="./documents", size="lg", scale=1)
        gr.Button("Datasets", link="./datasets", size="lg", scale=1)
    with gr.Row():
        gr.Button("Evaluation", link="./evaluation", size="lg", scale=1)
        gr.Button("Dashboard", link="./dashboard", size="lg", scale=1)
        gr.Button("Metrics", link="./metrics", size="lg", scale=1)
    with gr.Row():
        gr.Button("Config", link="./_config", size="lg", scale=1)
        gr.Button("Ad-hoc", link="./ad-hoc", size="lg", scale=1)
    gr.Markdown(
        '<div style="text-align:center; margin-top:0.5em; font-size:0.9em; opacity:0.8">'
        "<strong>Chat</strong> — Q&amp;A with your PDFs. "
        "<strong>Datasets</strong> — build evaluation sets from live chat sessions "
        "or from manually annotated documents."
        "</div>"
    )


def create_app() -> gr.Blocks:
    # Homepage (default route)
    with gr.Blocks(title=ASSISTANT_NAME) as demo:
        _build_homepage()

    # Chat page
    with demo.route("Chat") as chat_page:
        with gr.Tabs():
            with gr.Tab("Chat with Documents"):
                (
                    assistant_state,
                    chatbot,
                    doc_dropdown,
                    status_md,
                    session_id_state,
                    session_dropdown,
                ) = build_chat_tab()
        chat_page.load(
            fn=on_app_load,
            outputs=[
                assistant_state,
                chatbot,
                doc_dropdown,
                status_md,
                session_id_state,
                session_dropdown,
            ],
        )

    # Documents page — browse cached documents with PDF preview + enrichment
    with demo.route("Documents") as documents_page:
        docs_assistant_state = gr.State(value=None)
        with gr.Tabs():
            with gr.Tab("Browse Documents"):
                (
                    docs_dd,
                    docs_bulk_dd,
                    docs_meta_md,
                    docs_pdf_html,
                    docs_enrichment_md,
                ) = build_documents_tab(docs_assistant_state)
        documents_page.load(
            fn=on_documents_tab_load,
            inputs=[docs_assistant_state],
            outputs=[docs_assistant_state, docs_dd, docs_bulk_dd],
        )

    # Datasets page — two tabs sharing one assistant_state
    with demo.route("Datasets") as datasets_page:
        ds_assistant_state = gr.State(value=None)
        with gr.Tabs():
            with gr.Tab("Live Chat Datasets"):
                (
                    _,
                    ds_dataset_dd,
                    ds_session_dd,
                    ds_message_cb,
                    ds_preview_md,
                    ds_export_json,
                ) = build_datasets_tab(ds_assistant_state)
            with gr.Tab("Annotate Documents"):
                ev_ann_doc_dd, ev_dataset_dd = build_annotation_tab(ds_assistant_state)

        datasets_page.load(
            fn=on_datasets_tab_load,
            inputs=[ds_assistant_state],
            outputs=[
                ds_assistant_state,
                ds_dataset_dd,
                ds_session_dd,
                ds_message_cb,
                ds_export_json,
                ds_preview_md,
            ],
        ).then(
            fn=on_tab_load,
            inputs=[ds_assistant_state],
            outputs=[ev_ann_doc_dd],
        ).then(
            fn=lambda a: gr.update(choices=_annotate_dataset_choices(a)),
            inputs=[ds_assistant_state],
            outputs=[ev_dataset_dd],
        )

    # Evaluation page — Execution Run / Judge Run (Milestones 3 & 4)
    with demo.route("Evaluation") as evaluation_page:
        ev_assistant_state = gr.State(value=None)
        with gr.Tabs():
            with gr.Tab("Execution Run"):
                (
                    ev_dataset_dd,
                    ev_run_dd,
                    ev_results_tbl,
                    ev_summary_md,
                    ev_agent_ver_dd,
                    ev_general_ver_dd,
                ) = build_execution_run_tab(ev_assistant_state)
            with gr.Tab("Judge Run"):
                judge_eval_dd, judge_metrics_multi, judge_run_dd, judge_aggregates = (
                    build_judge_run_tab(ev_assistant_state)
                )

        evaluation_page.load(
            fn=on_evaluation_tab_load,
            inputs=[ev_assistant_state],
            outputs=[
                ev_assistant_state,
                ev_dataset_dd,
                ev_run_dd,
                ev_results_tbl,
                ev_summary_md,
                ev_agent_ver_dd,
                ev_general_ver_dd,
            ],
        ).then(
            fn=on_judge_tab_load,
            inputs=[ev_assistant_state],
            outputs=[
                ev_assistant_state,
                judge_eval_dd,
                judge_metrics_multi,
                judge_run_dd,
                judge_aggregates,
            ],
        )

    # Dashboard page — Data and Evaluations overview (Milestone 5)
    with demo.route("Dashboard") as dashboard_page:
        dash_assistant_state = gr.State(value=None)
        with gr.Tabs():
            with gr.Tab("Data"):
                data_kpis, data_docs, data_sets, data_datasets = build_data_dashboard_tab(
                    dash_assistant_state
                )
            with gr.Tab("Evaluations"):
                (
                    eval_kpis,
                    eval_runs,
                    eval_judge,
                    eval_pivot,
                    eval_metric,
                    eval_failure,
                ) = build_evaluation_dashboard_tab(dash_assistant_state)

        dashboard_page.load(
            fn=on_dashboard_load,
            inputs=[dash_assistant_state],
            outputs=[
                dash_assistant_state,
                data_kpis,
                data_docs,
                data_sets,
                data_datasets,
                eval_kpis,
                eval_runs,
                eval_judge,
                eval_pivot,
                eval_metric,
                eval_failure,
            ],
        )

    # Metrics page — scoring rubrics for judge runs (was under Config)
    with demo.route("Metrics") as metrics_page:
        metrics_assistant_state = gr.State(value=None)
        with gr.Tabs():
            with gr.Tab("Metrics"):
                metric_dd, metrics_table, metrics_status = build_metrics_tab(
                    metrics_assistant_state
                )

        metrics_page.load(
            fn=on_metrics_tab_load,
            inputs=[metrics_assistant_state],
            outputs=[metrics_assistant_state, metric_dd, metrics_table, metrics_status],
        )

    # Config page — app / environment configuration
    with demo.route("Config") as config_page:
        cfg_assistant_state = gr.State(value=None)
        with gr.Tabs():
            with gr.Tab("System"):
                build_system_tab(cfg_assistant_state)
            with gr.Tab("Agent Config"):
                build_agent_config_tab()

    # Ad-hoc page — quick experimental utilities (no validation)
    with demo.route("Ad-hoc") as adhoc_page:
        adhoc_assistant_state = gr.State(value=None)
        with gr.Tabs():
            with gr.Tab("Switch File ID"):
                (
                    adhoc_source_dd,
                    adhoc_old_doc_dd,
                    adhoc_new_doc_dd,
                    _,
                    _,
                ) = build_switch_file_tab(adhoc_assistant_state)
        adhoc_page.load(
            fn=on_adhoc_tab_load,
            inputs=[adhoc_assistant_state],
            outputs=[
                adhoc_assistant_state,
                adhoc_source_dd,
                adhoc_old_doc_dd,
                adhoc_new_doc_dd,
            ],
        )

    return demo


def _annotate_dataset_choices(assistant):
    if assistant is None:
        return []
    return [
        (f"{d['name']} ({d['annotation_count']} items)", d["dataset_id"])
        for d in assistant.store.list_datasets()
    ]


if __name__ == "__main__":
    app = create_app()
    pdf_storage_dir = os.path.abspath(os.getenv("PDF_STORAGE_DIR", "data/pdfs"))
    app.launch(
        server_name="0.0.0.0",
        server_port=7860,
        theme=gr.themes.Soft(),
        allowed_paths=[pdf_storage_dir],
        head=annotator_head_script(),
    )
