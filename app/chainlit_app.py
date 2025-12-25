"""Chainlit app for PDF Q&A with smooth single-attachment behavior."""

import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import chainlit as cl

from src.agents import run_agent
from src.chat import ChatAssistant


async def chat_with_steps(assistant: ChatAssistant, user_message: str) -> str:
    """Chat with visible reasoning steps in Chainlit UI."""
    prompt, deps = assistant.prepare_turn(user_message)

    # Step 1: Main agent draft
    async with cl.Step(name="🤔 Thinking", type="llm") as step:
        draft = (await run_agent(assistant.main, prompt, deps=deps, label="main")).output
        step.output = draft

    # Step 2: Reviewer
    async with cl.Step(name="📝 Reviewing", type="llm") as step:
        review_prompt = assistant.build_review_prompt(user_message, draft)
        review = (await run_agent(assistant.reviewer, review_prompt, label="reviewer")).output
        verdict, final, fixes = assistant.parse_reviewer(review)
        step.output = f"Verdict: {verdict or 'OK'}"
        if fixes:
            step.output += f"\nFixes: {fixes}"

    # Step 3: Retry if needed
    if verdict == "NEEDS_WORK" and fixes:
        async with cl.Step(name="🔄 Refining", type="llm") as step:
            retry_prompt = assistant.build_retry_prompt(user_message, draft, fixes)
            draft2 = (
                await run_agent(assistant.main, retry_prompt, deps=deps, label="main-retry")
            ).output
            step.output = draft2

            review2_prompt = assistant.build_review_prompt(user_message, draft2)
            review2 = (
                await run_agent(assistant.reviewer, review2_prompt, label="reviewer-retry")
            ).output
            _, final2, _ = assistant.parse_reviewer(review2)
            reply = assistant.finalize_turn(final2 or draft2)
    else:
        return assistant.finalize_turn(final or draft)

    return reply


ATTACHMENT_MSG_KEY = "attachment_msg_id"
CURRENT_FILE_NAME_KEY = "current_file_name"
CURRENT_FILE_PATH_KEY = "current_file_path"


def _safe_unlink(path: str | None) -> None:
    if not path:
        return
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def _persist_pdf_to_tmp(src_path: str, original_name: str) -> str:
    suffix = Path(original_name).suffix or ".pdf"
    dest = Path(tempfile.gettempdir()) / f"myagent_{uuid4().hex}{suffix}"
    shutil.copy(src_path, dest)
    return str(dest)


async def _reset_attachment(assistant: ChatAssistant) -> None:
    # Delete persisted file
    _safe_unlink(cl.user_session.get(CURRENT_FILE_PATH_KEY))

    # Reset session + assistant
    cl.user_session.set(CURRENT_FILE_NAME_KEY, None)
    cl.user_session.set(CURRENT_FILE_PATH_KEY, None)
    assistant.text = ""
    assistant.document = None

    # Update the pinned status message (if present)
    await _upsert_attachment_status_message()


async def _upsert_attachment_status_message(load_result: str | None = None) -> None:
    """Create or update a single 'attachment status' message."""
    file_name = cl.user_session.get(CURRENT_FILE_NAME_KEY)
    file_path = cl.user_session.get(CURRENT_FILE_PATH_KEY)
    msg_id = cl.user_session.get(ATTACHMENT_MSG_KEY)

    if file_name and file_path:
        elements = [
            # Viewer in the chat UI
            cl.Pdf(name=file_name, path=file_path, display="inline"),
            # Optional: a download button
            cl.File(name=file_name, path=file_path, display="inline"),
        ]
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

    # Create once, then update in place
    if msg_id:
        msg = cl.Message(content=content, elements=elements, actions=actions)
        msg.id = msg_id
        await msg.update()
    else:
        msg = await cl.Message(content=content, elements=elements, actions=actions).send()
        cl.user_session.set(ATTACHMENT_MSG_KEY, msg.id)


@cl.on_chat_start
async def start():
    assistant = ChatAssistant()
    cl.user_session.set("assistant", assistant)

    # Start clean
    cl.user_session.set(CURRENT_FILE_NAME_KEY, None)
    cl.user_session.set(CURRENT_FILE_PATH_KEY, None)
    cl.user_session.set(ATTACHMENT_MSG_KEY, None)

    await cl.Message(
        content="👋 Hi! Upload a PDF (📎) to attach it and ask questions.\n"
        "You can remove it using the button under the attachment."
    ).send()

    await _upsert_attachment_status_message()


@cl.action_callback("detach_file")
async def on_detach_file(_: cl.Action):
    assistant: ChatAssistant = cl.user_session.get("assistant")
    await _reset_attachment(assistant)
    await cl.Message(content="✅ Attachment removed.").send()


@cl.on_message
async def on_message(message: cl.Message):
    assistant: ChatAssistant = cl.user_session.get("assistant")

    # Keep your /clear command as a text equivalent (optional)
    if message.content.strip().lower() == "/clear":
        await _reset_attachment(assistant)
        await cl.Message(content="✅ Attachment removed.").send()
        return

    # Handle file uploads (replace existing)
    element = next(
        (e for e in (message.elements or []) if getattr(e, "mime", None) == "application/pdf"),
        None,
    )
    if element:
        _safe_unlink(cl.user_session.get(CURRENT_FILE_PATH_KEY))
        dest_path = _persist_pdf_to_tmp(element.path, element.name)
        result = assistant.load_pdf(dest_path)

        cl.user_session.set(CURRENT_FILE_NAME_KEY, element.name)
        cl.user_session.set(CURRENT_FILE_PATH_KEY, dest_path)
        await _upsert_attachment_status_message(load_result=f"📄 Loaded\n{result}")

        if message.content.strip():
            response = await chat_with_steps(assistant, message.content)
            await cl.Message(content=response).send()
        return

    # Regular chat with visible reasoning steps
    response = await chat_with_steps(assistant, message.content)
    await cl.Message(content=response).send()
