from __future__ import annotations

import os
from pathlib import Path

from src.agents import create_main_agent, run_agent
from src.agents.main import MainDeps
from src.agents_config import load_agents_config, load_personal_info, load_prompts_config
from src.logging import setup_logging
from src.schemas import StructuredDocument
from src.tools import extract_text_full, parse_pdf_to_document

logger = setup_logging("chat_assistant")


class ChatAssistant:
    def __init__(self):
        self.config = load_agents_config()
        self.prompts = load_prompts_config()
        self.personal_info = load_personal_info()
        self.document: StructuredDocument | None = None
        self.text: str = ""
        self.history: list[tuple[str, str]] = []
        logger.info("Initializing ChatAssistant backend=%s", self.config.default_backend)
        self._init_agents()
        self.inline_doc_max_chars = int(os.getenv("INLINE_DOC_MAX_CHARS", "20000"))

    def prepare_turn(self, user_message: str) -> tuple[str, MainDeps]:
        """Prepare prompt + deps for a chat turn and append the user message to history."""
        self.history.append(("user", user_message))
        recent = self.history[-12:]
        history_text = "\n".join(f"{role}: {msg}" for role, msg in recent)

        pi_block = ""
        if self.personal_info and self.personal_info.data:
            pi_block = f"{self.personal_info.to_prompt_context()}\n\n"

        doc_block = ""
        if self.text and len(self.text) <= self.inline_doc_max_chars:
            logger.info(
                "turn=%s inline_doc=true chars=%s",
                len(self.history) // 2,
                len(self.text),
            )
            doc_block = f"Document text (full):\n{self.text}\n\n"
        elif self.text:
            logger.info(
                "turn=%s inline_doc=false chars=%s max=%s",
                len(self.history) // 2,
                len(self.text),
                self.inline_doc_max_chars,
            )
            doc_block = f"Document text (truncated):\n{self.text[: self.inline_doc_max_chars]}\n\n"

        prompt = (
            f"{pi_block}{doc_block}Conversation so far:\n{history_text}\n\n"
            f"User message: {user_message}"
        )
        deps = MainDeps(
            document=self.document,
            text=self.text,
            personal_info=self.personal_info,
        )
        return prompt, deps

    def finalize_turn(self, reply: str) -> str:
        self.history.append(("assistant", reply))
        return reply

    def _init_agents(self):
        self.main = create_main_agent(self.config, self.prompts)

    def load_pdf(self, path: str) -> str:
        p = Path(path)
        if not p.exists():
            logger.warning("File not found: %s", path)
            return f"File not found: {path}"
        logger.info("Loading PDF: %s", path)
        self.document = parse_pdf_to_document(p)
        self.text = extract_text_full(p)
        logger.info(
            "Loaded pages=%d spans=%d chars=%d",
            len(self.document.pages),
            len(self.document.citable_spans),
            len(self.text),
        )
        return f"Loaded {len(self.document.pages)} pages, {len(self.document.citable_spans)} spans"

    def set_text(self, text: str) -> str:
        self.text = text
        self.document = None
        return f"Text set ({len(text)} chars)"

    def reset_chat(self) -> str:
        self.history = []
        return "Chat history cleared"

    def show_info(self) -> str:
        lines = [
            f"Backend: {self.config.default_backend}",
            f"Personal info: {self.personal_info.data or 'None'}",
            f"Document loaded: {self.document is not None}",
            f"Text length: {len(self.text)} chars",
            f"Chat turns: {len(self.history)}",
        ]
        if self.document:
            lines.append(f"Pages: {len(self.document.pages)}")
            lines.append(f"Sections: {self.document.sections[:5]}")
        return "\n".join(lines)

    async def chat(self, user_message: str) -> str:
        prompt, deps = self.prepare_turn(user_message)
        result = await run_agent(self.main, prompt, deps=deps, label="main")
        reply = result.output or ""
        return self.finalize_turn(reply)
