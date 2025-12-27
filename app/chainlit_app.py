import os
import re

import chainlit as cl

from src.bootstrap import init_app

init_app()

from src.agents import run_agent
from src.chat import ChatAssistant
from src.logging import setup_logging

logger = setup_logging("chainlit_app")
SHOW_REASONING = os.getenv("SHOW_REASONING", "true").lower() == "true"
USE_ENRICHMENT = os.getenv("USE_ENRICHMENT", "true").lower() == "true"
SHOW_INGESTION_LOGS = os.getenv("SHOW_INGESTION_LOGS", "false").lower() == "true"


async def chat_with_steps(assistant, user_message: str) -> None:
    """Chat with visible reasoning steps in Chainlit UI."""
    prompt, deps = assistant.prepare_turn(user_message)
    logger.info("chainlit chat_with_steps user_msg_len=%d", len(user_message))

    async with cl.Step(name="🤔 Thinking...", type="llm") as step:
        result = await run_agent(assistant.main, prompt, deps=deps, label="main")
        raw_output = result.output or ""
        step_parts = []
        
        # Log summary of tool calls
        tool_calls_list = []
        for msg in result.all_messages():
            for p in getattr(msg, "parts", []):
                if getattr(p, "part_kind", "") == "tool-call" and hasattr(p, "tool_name"):
                    tool_calls_list.append(p.tool_name)
        tool_calls_count = len(tool_calls_list)
        if tool_calls_list:
            logger.info("chainlit main_agent_complete tool_calls=%d tools=%s output_len=%d", 
                       tool_calls_count, ", ".join(tool_calls_list), len(raw_output))
        else:
            logger.warning("chainlit main_agent_complete no_tool_calls output_len=%d", len(raw_output))

        # Extract reasoning traces if present
        think_match = re.search(r"<think>(.*?)</think>", raw_output, re.DOTALL)
        if SHOW_REASONING and think_match:
            step_parts.append(think_match.group(1).strip())
            reply = re.sub(r"<think>.*?</think>", "", raw_output, flags=re.DOTALL).strip()
        else:
            reply = raw_output

        # Map tool names to agent labels
        TOOL_AGENTS = {
            "validate_against_personal_info": "validator",
            "review_draft": "reviewer",
        }

        # Collect tool calls and returns
        tool_info = {}
        for msg in result.all_messages():
            for p in getattr(msg, "parts", []):
                part_kind = getattr(p, "part_kind", "")
                if part_kind == "tool-call" and hasattr(p, "tool_name"):
                    args_str = ""
                    args = getattr(p, "args", None)
                    if args:
                        if isinstance(args, dict):
                            # Show key args for better visibility
                            key_args = []
                            for k, v in args.items():
                                if isinstance(v, str):
                                    key_args.append(f"{k}={v[:30]}..." if len(v) > 30 else f"{k}={v}")
                                elif isinstance(v, list):
                                    key_args.append(f"{k}=[{len(v)} items]")
                                else:
                                    key_args.append(f"{k}={v}")
                            args_str = ", ".join(key_args)
                        elif isinstance(args, str):
                            args_str = f"... ({len(args)} chars)"
                    tid = getattr(p, "tool_call_id", id(p))
                    tool_info[tid] = {"name": p.tool_name, "args": args_str, "result": None, "called": True}
                    logger.debug("chainlit tool_call detected: %s(%s)", p.tool_name, args_str)
                elif part_kind == "tool-return" and hasattr(p, "content"):
                    tid = getattr(p, "tool_call_id", None)
                    if tid and tid in tool_info:
                        content = str(p.content)
                        tool_info[tid]["result"] = content[:200] + "..." if len(content) > 200 else content
                        logger.debug("chainlit tool_return for %s: %d chars", tool_info[tid]["name"], len(content))

        # Format tool calls for display
        for info in tool_info.values():
            agent = TOOL_AGENTS.get(info["name"], "")
            agent_label = f" → **{agent} agent**" if agent else ""
            line = f"🔧 **{info['name']}**({info['args']}){agent_label}"
            if info["result"]:
                result_preview = info["result"][:150] + "..." if len(info["result"]) > 150 else info["result"]
                line += f"\n   ↳ {result_preview}"
            step_parts.append(line)
        
        if not tool_info and tool_calls_count == 0:
            logger.warning("chainlit no tool calls detected - agent may have answered directly without using tools")

        if step_parts:
            step.output = "\n\n".join(step_parts)
        else:
            usage = result.usage()
            step.output = f"📝 Direct answer ({usage.output_tokens} tokens)"

    assistant.finalize_turn(reply)
    await cl.Message(content=reply).send()


ATTACHMENT_MSG_KEY = "attachment_msg_id"
CURRENT_FILE_NAME_KEY = "current_file_name"
CURRENT_FILE_PATH_KEY = "current_file_path"


async def _show_cached_documents(assistant) -> None:
    """Display cached documents with selection and delete buttons."""
    docs = assistant.list_cached_documents()
    if not docs:
        await cl.Message(content="📚 No cached documents. Upload a PDF to get started.").send()
        return

    actions = []
    for doc in docs[:10]:  # Limit to 10 most recent
        actions.append(
            cl.Action(
                name="select_doc",
                payload={
                    "doc_id": doc.doc_id,
                    "file_name": doc.file_name,
                    "file_path": doc.file_path,
                },
                label=f"📄 {doc.file_name} ({doc.page_count} pages)",
            )
        )
        actions.append(
            cl.Action(
                name="delete_doc",
                payload={"doc_id": doc.doc_id, "file_name": doc.file_name},
                label=f"🗑️ Delete {doc.file_name}",
            )
        )
    content = f"📚 **Cached Documents** ({len(docs)} total)\nSelect one to load, delete, or upload a new PDF:"
    await cl.Message(content=content, actions=actions).send()


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
        msg = await cl.Message(content=content, elements=elements, actions=actions).send()
        cl.user_session.set(ATTACHMENT_MSG_KEY, msg.id)


@cl.on_chat_start
async def start():
    assistant = ChatAssistant()
    cl.user_session.set("assistant", assistant)

    cl.user_session.set(CURRENT_FILE_NAME_KEY, None)
    cl.user_session.set(CURRENT_FILE_PATH_KEY, None)
    cl.user_session.set(ATTACHMENT_MSG_KEY, None)

    await cl.Message(
        content="👋 Hi! Upload a PDF (📎) or select a cached document below.\n"
        "Use `/docs` to list cached documents, `/clear` to remove attachment."
    ).send()

    # Show cached documents on start
    await _show_cached_documents(assistant)
    await _upsert_attachment_status_message()


@cl.action_callback("detach_file")
async def on_detach_file(_: cl.Action):
    assistant = cl.user_session.get("assistant")
    await _reset_attachment(assistant)
    await cl.Message(content="✅ Attachment removed.").send()


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
        ).send()
    else:
        await cl.Message(
            content=f"✅ {result}\n\n_(Original file not available for preview)_"
        ).send()


@cl.action_callback("delete_doc")
async def on_delete_doc(action: cl.Action):
    """Handle cached document deletion."""
    assistant = cl.user_session.get("assistant")
    doc_id = action.payload.get("doc_id")
    file_name = action.payload.get("file_name")

    result = assistant.delete_cached_document(doc_id)
    await cl.Message(content=f"🗑️ {result}").send()

    # Clear attachment if deleted doc was active
    if cl.user_session.get(CURRENT_FILE_NAME_KEY) == file_name:
        await _reset_attachment(assistant)

    # Refresh the document list
    await _show_cached_documents(assistant)


@cl.on_message
async def on_message(message: cl.Message):
    assistant = cl.user_session.get("assistant")
    cmd = message.content.strip().lower()

    if cmd == "/clear":
        await _reset_attachment(assistant)
        await cl.Message(content="✅ Attachment removed.").send()
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
