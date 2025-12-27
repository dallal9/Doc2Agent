import asyncio
import os

import chainlit as cl

from src.bootstrap import init_app

init_app()

from app.utils import render_chat_with_cache
from src.agents import run_agent
from src.chat import ChatAssistant
from src.logging import setup_logging

logger = setup_logging("chainlit_app")
SHOW_REASONING = os.getenv("SHOW_REASONING", "true").lower() == "true"
USE_ENRICHMENT = os.getenv("USE_ENRICHMENT", "true").lower() == "true"
SHOW_INGESTION_LOGS = os.getenv("SHOW_INGESTION_LOGS", "false").lower() == "true"
ASSISTANT_AUTHOR = os.getenv("CHAINLIT_ASSISTANT_AUTHOR", "Doc2Agent")


async def chat_with_steps(assistant, user_message: str) -> None:
    """Chat with visible reasoning steps in Chainlit UI (with query cache)."""
    reply = await render_chat_with_cache(
        assistant=assistant,
        user_message=user_message,
        run_agent=run_agent,
        show_reasoning=SHOW_REASONING,
    )
    assistant.finalize_turn(reply)
    await cl.Message(content=reply, author=ASSISTANT_AUTHOR).send()


ATTACHMENT_MSG_KEY = "attachment_msg_id"
CURRENT_FILE_NAME_KEY = "current_file_name"
CURRENT_FILE_PATH_KEY = "current_file_path"


async def _show_cached_documents(assistant) -> None:
    """Display cached documents with selection and delete buttons."""
    docs = assistant.list_cached_documents()
    if not docs:
        await cl.Message(
            content="📚 No cached documents. Upload a PDF to get started.",
            author=ASSISTANT_AUTHOR,
        ).send()
        return

    actions = []
    for doc in docs[:10]:  # Limit to 10 most recent
        cache_count = assistant.store.get_query_count_for_document(doc.doc_id)
        cache_label = f" ({cache_count} cached queries)" if cache_count > 0 else ""
        actions.append(
            cl.Action(
                name="select_doc",
                payload={
                    "doc_id": doc.doc_id,
                    "file_name": doc.file_name,
                    "file_path": doc.file_path,
                },
                label=f"📄 {doc.file_name} ({doc.page_count} pages){cache_label}",
            )
        )
        actions.append(
            cl.Action(
                name="delete_doc",
                payload={"doc_id": doc.doc_id, "file_name": doc.file_name},
                label=f"🗑️ Delete {doc.file_name}",
            )
        )
        if cache_count > 0:
            actions.append(
                cl.Action(
                    name="flush_cache",
                    payload={"doc_id": doc.doc_id, "file_name": doc.file_name},
                    label=f"🗑️ Flush cache for {doc.file_name}",
                )
            )
    actions.append(
        cl.Action(
            name="flush_cache",
            payload={"doc_id": None},
            label="🗑️ Flush all query cache",
        )
    )
    content = (
        f"📚 **Cached Documents** ({len(docs)} total)\n"
        "Select one to load, delete, or upload a new PDF:"
    )
    await cl.Message(content=content, actions=actions, author=ASSISTANT_AUTHOR).send()


async def _reset_attachment(assistant) -> None:
    cl.user_session.set(CURRENT_FILE_NAME_KEY, None)
    cl.user_session.set(CURRENT_FILE_PATH_KEY, None)
    assistant.text = ""
    assistant.document = None
    assistant.enriched_doc = None
    assistant.document_id = None
    await _upsert_attachment_status_message()


async def _upsert_attachment_status_message(load_result: str | None = None) -> None:
    """Create or update a single 'attachment status' message."""
    file_name = cl.user_session.get(CURRENT_FILE_NAME_KEY)
    file_path = cl.user_session.get(CURRENT_FILE_PATH_KEY)
    msg_id = cl.user_session.get(ATTACHMENT_MSG_KEY)

    if file_name and file_path:
        elements = []
        actions = [
            cl.Action(
                name="detach_file",
                payload={"action": "detach"},
                label="Remove attachment",
            )
        ]
        content = f"📎 **Attached:** {file_name}"
        if load_result:
            content += f"\n\n{load_result}"
    else:
        elements = []
        actions = []
        content = "📎 **No file attached.** Upload a PDF to attach it."

    if msg_id:
        msg = cl.Message(content=content, elements=elements, actions=actions)
        msg.id = msg_id
        await msg.update()
    else:
        msg = await cl.Message(
            content=content,
            elements=elements,
            actions=actions,
            author=ASSISTANT_AUTHOR,
        ).send()
        cl.user_session.set(ATTACHMENT_MSG_KEY, msg.id)


@cl.on_chat_start
async def start():
    await asyncio.sleep(0.5)
    assistant = ChatAssistant()
    cl.user_session.set("assistant", assistant)

    cl.user_session.set(CURRENT_FILE_NAME_KEY, None)
    cl.user_session.set(CURRENT_FILE_PATH_KEY, None)
    cl.user_session.set(ATTACHMENT_MSG_KEY, None)

    await cl.Message(
        content="👋 Hi! Upload a PDF (📎) or select a cached document below.\n"
        "Use `/docs` to list cached documents, `/clear` to remove attachment.",
        author=ASSISTANT_AUTHOR,
    ).send()

    # Show cached documents on start
    await _show_cached_documents(assistant)
    await _upsert_attachment_status_message()


@cl.action_callback("detach_file")
async def on_detach_file(_: cl.Action):
    assistant = cl.user_session.get("assistant")
    await _reset_attachment(assistant)
    await cl.Message(content="✅ Attachment removed.", author=ASSISTANT_AUTHOR).send()


@cl.action_callback("select_doc")
async def on_select_doc(action: cl.Action):
    """Handle cached document selection."""
    assistant = cl.user_session.get("assistant")
    doc_id = action.payload.get("doc_id")
    file_name = action.payload.get("file_name")
    file_path = action.payload.get("file_path")

    result = assistant.load_cached_document(doc_id)
    cl.user_session.set(CURRENT_FILE_NAME_KEY, file_name)
    cl.user_session.set(CURRENT_FILE_PATH_KEY, file_path)
    await _upsert_attachment_status_message(load_result=f"📄 {result}")

    # Show PDF preview if file exists
    if file_path and os.path.exists(file_path):
        await cl.Message(
            content=f"**Preview of {file_name}:**",
            elements=[cl.Pdf(name=file_name, path=file_path, display="inline")],
            author=ASSISTANT_AUTHOR,
        ).send()
    else:
        await cl.Message(
            content=f"✅ {result}\n\n_(Original file not available for preview)_",
            author=ASSISTANT_AUTHOR,
        ).send()


@cl.action_callback("delete_doc")
async def on_delete_doc(action: cl.Action):
    """Handle cached document deletion."""
    assistant = cl.user_session.get("assistant")
    doc_id = action.payload.get("doc_id")
    file_name = action.payload.get("file_name")

    result = assistant.delete_cached_document(doc_id)
    await cl.Message(content=f"🗑️ {result}", author=ASSISTANT_AUTHOR).send()

    # Clear attachment if deleted doc was active
    if cl.user_session.get(CURRENT_FILE_NAME_KEY) == file_name:
        await _reset_attachment(assistant)

    # Refresh the document list
    await _show_cached_documents(assistant)


@cl.action_callback("flush_cache")
async def on_flush_cache(action: cl.Action):
    """Handle query cache flush."""
    assistant = cl.user_session.get("assistant")
    doc_id = action.payload.get("doc_id")
    file_name = action.payload.get("file_name")

    count = assistant.store.flush_query_cache(doc_id)
    if doc_id:
        await cl.Message(
            content=f"🗑️ Flushed {count} cached queries for {file_name}",
            author=ASSISTANT_AUTHOR,
        ).send()
    else:
        await cl.Message(
            content=f"🗑️ Flushed {count} cached queries (all documents)",
            author=ASSISTANT_AUTHOR,
        ).send()

    # Refresh the document list
    await _show_cached_documents(assistant)


@cl.on_message
async def on_message(message: cl.Message):
    assistant = cl.user_session.get("assistant")
    cmd = message.content.strip().lower()

    if cmd == "/clear":
        await _reset_attachment(assistant)
        await cl.Message(content="✅ Attachment removed.", author=ASSISTANT_AUTHOR).send()
        return

    if cmd == "/docs":
        await _show_cached_documents(assistant)
        return

    # Handle file uploads
    element = next(
        (e for e in (message.elements or []) if getattr(e, "mime", None) == "application/pdf"),
        None,
    )
    if element:
        current_name = cl.user_session.get(CURRENT_FILE_NAME_KEY)
        current_path = cl.user_session.get(CURRENT_FILE_PATH_KEY)
        if current_name == element.name and current_path:
            if message.content.strip():
                await chat_with_steps(assistant, message.content)
            return

        # Use new async ingest_pdf with enrichment and progress callback
        async with cl.Step(name="📄 Ingesting PDF...", type="tool") as step:
            step.output = "Initializing parser..."

            async def on_progress(current: int, total: int):
                if SHOW_INGESTION_LOGS:
                    step.output = f"Enriching page {current}/{total}..."
                    await step.update()

            result = await assistant.ingest_pdf(
                element.path,
                enrich=USE_ENRICHMENT,
                on_progress=on_progress,
                original_filename=element.name,
            )
            step.output = result

        cl.user_session.set(CURRENT_FILE_NAME_KEY, element.name)
        cl.user_session.set(CURRENT_FILE_PATH_KEY, element.path)
        await _upsert_attachment_status_message(load_result=f"📄 {result}")

        if message.content.strip():
            await chat_with_steps(assistant, message.content)
        return

    await chat_with_steps(assistant, message.content)
