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


async def chat_with_steps(assistant, user_message: str) -> None:
    """Chat with visible reasoning steps in Chainlit UI."""
    prompt, deps = assistant.prepare_turn(user_message)

    async with cl.Step(name="🤔 Thinking...", type="llm") as step:
        result = await run_agent(assistant.main, prompt, deps=deps, label="main")
        raw_output = result.output or ""
        step_parts = []

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
        tool_info = {}  # tool_call_id -> {name, args, result}
        for msg in result.all_messages():
            for p in getattr(msg, "parts", []):
                part_kind = getattr(p, "part_kind", "")
                if part_kind == "tool-call" and hasattr(p, "tool_name"):
                    # Tool call
                    args_str = ""
                    args = getattr(p, "args", None)
                    if args:
                        if isinstance(args, dict):
                            args_str = ", ".join(args.keys())
                        elif isinstance(args, str):
                            # JSON string - just show truncated
                            args_str = "..."
                    tid = getattr(p, "tool_call_id", id(p))
                    tool_info[tid] = {"name": p.tool_name, "args": args_str, "result": None}
                elif part_kind == "tool-return" and hasattr(p, "content"):
                    # Tool return
                    tid = getattr(p, "tool_call_id", None)
                    if tid and tid in tool_info:
                        content = str(p.content)[:150]
                        tool_info[tid]["result"] = content

        # Format tool calls for display
        for info in tool_info.values():
            agent = TOOL_AGENTS.get(info["name"], "")
            agent_label = f" → {agent}" if agent else ""
            line = f"🔧 **{info['name']}**({info['args']}){agent_label}"
            if info["result"]:
                line += f"\n   ↳ {info['result']}..."
            step_parts.append(line)

        # Build step output
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


async def _reset_attachment(assistant) -> None:
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
        # Avoid re-sending file elements here; Chainlit may duplicate them in `.files/`.
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
    assistant = cl.user_session.get("assistant")
    await _reset_attachment(assistant)
    await cl.Message(content="✅ Attachment removed.").send()


@cl.on_message
async def on_message(message: cl.Message):
    assistant = cl.user_session.get("assistant")

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
        current_name = cl.user_session.get(CURRENT_FILE_NAME_KEY)
        current_path = cl.user_session.get(CURRENT_FILE_PATH_KEY)
        if current_name == element.name and current_path:
            # Some clients resend the attachment each message; keep existing attachment.
            if message.content.strip():
                await chat_with_steps(assistant, message.content)
            return

        result = assistant.load_pdf(element.path)

        cl.user_session.set(CURRENT_FILE_NAME_KEY, element.name)
        cl.user_session.set(CURRENT_FILE_PATH_KEY, element.path)
        await _upsert_attachment_status_message(load_result=f"📄 Loaded\n{result}")

        if message.content.strip():
            await chat_with_steps(assistant, message.content)
        return

    # Regular chat with visible reasoning steps
    await chat_with_steps(assistant, message.content)
