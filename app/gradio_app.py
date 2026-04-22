import asyncio
import os

import gradio as gr

from src.bootstrap import init_app

init_app()

from app.utils import ChatResult, render_chat_with_cache
from src.agents import run_agent
from src.chat import ChatAssistant
from src.logging import setup_logging

logger = setup_logging("gradio_app")

SHOW_REASONING = os.getenv("SHOW_REASONING", "true").lower() == "true"
USE_ENRICHMENT = os.getenv("USE_ENRICHMENT", "true").lower() == "true"
SHOW_INGESTION_LOGS = os.getenv("SHOW_INGESTION_LOGS", "false").lower() == "true"
ASSISTANT_NAME = os.getenv("ASSISTANT_NAME", "Doc2Agent")
LOGO_PATH = "public/logo_dark.png"


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


# ---------------------------------------------------------------------------
# Event handlers
# ---------------------------------------------------------------------------


async def on_app_load():
    """Initialise a ChatAssistant when the page loads."""
    assistant = ChatAssistant()
    choices = _doc_choices(assistant)
    welcome = [{"role": "assistant", "content": f"Hi! Upload a PDF or select a cached document to get started."}]
    return assistant, welcome, gr.update(choices=choices, value=None), "No file attached."


async def on_upload(file_path, assistant, history):
    if file_path is None or assistant is None:
        yield assistant, None, None, "No file uploaded.", history, gr.update()
        return

    original_name = os.path.basename(file_path)
    history = history + [
        {"role": "assistant", "content": f"Ingesting **{original_name}**..."},
    ]
    yield assistant, original_name, file_path, f"Ingesting {original_name}...", history, gr.update()

    if SHOW_INGESTION_LOGS:
        progress_updates: asyncio.Queue[tuple[int, int]] = asyncio.Queue()

        async def on_progress(current: int, total: int):
            await progress_updates.put((current, total))

        ingest_task = asyncio.create_task(
            assistant.ingest_pdf(
                file_path,
                enrich=USE_ENRICHMENT,
                on_progress=on_progress,
                original_filename=original_name,
            )
        )
        while not ingest_task.done():
            try:
                current, total = await asyncio.wait_for(progress_updates.get(), timeout=0.25)
            except TimeoutError:
                continue
            history = _upsert_last_assistant(
                history, f"Ingesting **{original_name}**... ({current}/{total})"
            )
            yield assistant, original_name, file_path, f"Ingesting {original_name}...", history, gr.update()
        result = await ingest_task
    else:
        result = await assistant.ingest_pdf(
            file_path, enrich=USE_ENRICHMENT, original_filename=original_name
        )
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


async def on_send(message, history, assistant, file_name, file_path):
    if not message or not message.strip() or assistant is None:
        yield "", history, assistant, file_name, file_path
        return

    history = history + [{"role": "user", "content": message}]
    history = _upsert_last_assistant(history, "*Checking cache...*")
    yield "", history, assistant, file_name, file_path

    cached = assistant.get_cached_query(message)
    if cached is None:
        history = _upsert_last_assistant(history, "*Running main agent...*")
    else:
        history = _upsert_last_assistant(history, "*Cache hit. Preparing response...*")
    yield "", history, assistant, file_name, file_path

    result = await render_chat_with_cache(
        assistant=assistant,
        user_message=message,
        run_agent=run_agent,
        show_reasoning=SHOW_REASONING,
    )
    assistant.finalize_turn(result.reply)
    formatted = _format_bot_message(result)
    history = _upsert_last_assistant(history, formatted)
    yield "", history, assistant, file_name, file_path


async def on_load_doc(doc_id, assistant, history):
    if not doc_id or assistant is None:
        return assistant, None, None, "No document selected.", history

    result_msg = assistant.load_cached_document(doc_id)
    meta = assistant.store.get_document_metadata(doc_id)
    file_name = meta.file_name if meta else doc_id
    file_path = meta.file_path if meta else None
    history = history + [{"role": "assistant", "content": result_msg}]
    return assistant, file_name, file_path, f"**Attached:** {file_name}", history


async def on_delete_doc(doc_id, assistant, current_fname, history):
    if not doc_id or assistant is None:
        return assistant, current_fname, None, "No document selected.", history, gr.update()

    meta = assistant.store.get_document_metadata(doc_id)
    fname = meta.file_name if meta else doc_id
    result_msg = assistant.delete_cached_document(doc_id)
    history = history + [{"role": "assistant", "content": f"Deleted {fname}. {result_msg}"}]

    new_fname = current_fname
    status = f"**Attached:** {current_fname}" if current_fname else "No file attached."
    if current_fname == fname:
        new_fname = None
        status = "No file attached."

    choices = _doc_choices(assistant)
    return assistant, new_fname, None, status, history, gr.update(choices=choices, value=None)


async def on_flush_cache(doc_id, assistant, history):
    if assistant is None:
        return history, gr.update()
    if not doc_id:
        return history, gr.update()

    count = assistant.store.flush_query_cache(doc_id)
    meta = assistant.store.get_document_metadata(doc_id)
    fname = meta.file_name if meta else doc_id
    history = history + [
        {"role": "assistant", "content": f"Flushed {count} cached queries for {fname}."}
    ]
    choices = _doc_choices(assistant)
    return history, gr.update(choices=choices, value=None)


async def on_flush_all(assistant, history):
    if assistant is None:
        return history, gr.update()
    count = assistant.store.flush_query_cache(None)
    history = history + [
        {"role": "assistant", "content": f"Flushed {count} cached queries (all documents)."}
    ]
    choices = _doc_choices(assistant)
    return history, gr.update(choices=choices, value=None)


async def on_detach(assistant):
    if assistant is None:
        return assistant, None, None, "No file attached."
    assistant.text = ""
    assistant.document = None
    assistant.enriched_doc = None
    assistant.document_id = None
    return assistant, None, None, "No file attached."


# ---------------------------------------------------------------------------
# Build UI
# ---------------------------------------------------------------------------


def build_chat_tab():
    """Build the 'Chat with Documents' tab contents. Returns components needed for wiring."""
    # -- State --
    assistant_state = gr.State(value=None)
    file_name_state = gr.State(value=None)
    file_path_state = gr.State(value=None)

    with gr.Row():
        # -- Sidebar --
        with gr.Column(scale=1, min_width=260):
            gr.Image(
                value=LOGO_PATH,
                show_label=False,
                container=False,
                interactive=False,
                buttons=[],
                width="100%",
            )
            gr.Markdown(f"### {ASSISTANT_NAME}")
            file_upload = gr.File(label="Upload PDF", file_types=[".pdf"], type="filepath")
            status_md = gr.Markdown("No file attached.")
            doc_dropdown = gr.Dropdown(label="Cached Documents", choices=[], interactive=True)
            with gr.Row():
                load_btn = gr.Button("Load", size="sm")
                delete_btn = gr.Button("Delete", variant="stop", size="sm")
            with gr.Row():
                flush_btn = gr.Button("Flush Cache", size="sm")
                flush_all_btn = gr.Button("Flush All", variant="stop", size="sm")
            detach_btn = gr.Button("Detach File", size="sm")

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
    chatbot.change(fn=None, js="() => { const el = document.querySelector('.chatbot'); if(el) el.scrollTop = el.scrollHeight; }")

    load_event = gr.on(
        triggers=[msg_input.submit, send_btn.click],
        fn=on_send,
        inputs=[msg_input, chatbot, assistant_state, file_name_state, file_path_state],
        outputs=[msg_input, chatbot, assistant_state, file_name_state, file_path_state],
    )

    file_upload.upload(
        fn=on_upload,
        inputs=[file_upload, assistant_state, chatbot],
        outputs=[assistant_state, file_name_state, file_path_state, status_md, chatbot, doc_dropdown],
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

    delete_btn.click(
        fn=on_delete_doc,
        inputs=[doc_dropdown, assistant_state, file_name_state, chatbot],
        outputs=[assistant_state, file_name_state, file_path_state, status_md, chatbot, doc_dropdown],
    )

    flush_btn.click(
        fn=on_flush_cache,
        inputs=[doc_dropdown, assistant_state, chatbot],
        outputs=[chatbot, doc_dropdown],
    )

    flush_all_btn.click(
        fn=on_flush_all,
        inputs=[assistant_state, chatbot],
        outputs=[chatbot, doc_dropdown],
    )

    detach_btn.click(
        fn=on_detach,
        inputs=[assistant_state],
        outputs=[assistant_state, file_name_state, file_path_state, status_md],
    )

    return assistant_state, chatbot, doc_dropdown, status_md


def create_app() -> gr.Blocks:
    with gr.Blocks(title=ASSISTANT_NAME) as demo:
        with gr.Tabs():
            with gr.Tab("Chat with Documents"):
                assistant_state, chatbot, doc_dropdown, status_md = build_chat_tab()

        demo.load(
            fn=on_app_load,
            outputs=[assistant_state, chatbot, doc_dropdown, status_md],
        )
    return demo


if __name__ == "__main__":
    app = create_app()
    app.launch(server_name="0.0.0.0", server_port=7860, theme=gr.themes.Soft())
