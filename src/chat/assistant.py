from __future__ import annotations

import os
from pathlib import Path

from src.agents import create_main_agent, create_reviewer_agent
from src.agents.main import MainDeps
from src.agents_config import load_agents_config, load_personal_info, load_prompts_config
from src.logging import setup_logging
from src.schemas import StructuredDocument
from src.tools import extract_text_full, parse_pdf_to_document

logger = setup_logging("chat_assistant")


def _parse_reviewer(output: str) -> tuple[str, str, list[str]]:
    txt = (output or "").strip()
    verdict = (
        "NEEDS_WORK" if "VERDICT: NEEDS_WORK" in txt else ("OK" if "VERDICT: OK" in txt else "")
    )
    final = ""
    fixes: list[str] = []
    if "FINAL:" in txt:
        final = txt.split("FINAL:", 1)[1].strip()
    if "FIXES:" in txt:
        fixes_block = txt.split("FIXES:", 1)[1].strip()
        fixes = [line.strip("- ").strip() for line in fixes_block.splitlines() if line.strip()]
    return verdict, final, fixes


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

    def _init_agents(self):
        self.main = create_main_agent(self.config, self.prompts)
        self.reviewer = create_reviewer_agent(self.config, self.prompts)

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
        self.history.append(("user", user_message))
        recent = self.history[-12:]
        history_text = "\n".join(f"{role}: {msg}" for role, msg in recent)
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

        prompt = f"{doc_block}Conversation so far:\n{history_text}\n\nUser message: {user_message}"
        deps = MainDeps(document=self.document, text=self.text, personal_info=self.personal_info)

        turn_id = len(self.history) // 2
        logger.info("turn=%s agent=main start", turn_id)
        draft = (await self.main.run(prompt, deps=deps)).output
        logger.info("turn=%s agent=main done chars=%s", turn_id, len(draft or ""))

        review_prompt = f"User question:\n{user_message}\n\nDraft answer:\n{draft}"
        logger.info("turn=%s agent=reviewer start", turn_id)
        review = (await self.reviewer.run(review_prompt)).output
        verdict, final, fixes = _parse_reviewer(review)
        logger.info("turn=%s agent=reviewer verdict=%s", turn_id, verdict or "UNKNOWN")

        if verdict == "NEEDS_WORK" and fixes:
            fix_text = "\n".join(f"- {x}" for x in fixes[:8])
            retry_prompt = f"""User message: {user_message}

Previous draft:
{draft}

Reviewer fixes:
{fix_text}"""
            logger.info("turn=%s agent=main retry start", turn_id)
            draft2 = (await self.main.run(retry_prompt, deps=deps)).output
            logger.info("turn=%s agent=main retry done chars=%s", turn_id, len(draft2 or ""))

            review2_prompt = f"User question:\n{user_message}\n\nDraft answer:\n{draft2}"
            logger.info("turn=%s agent=reviewer retry start", turn_id)
            review2 = (await self.reviewer.run(review2_prompt)).output
            verdict2, final2, _ = _parse_reviewer(review2)
            logger.info("turn=%s agent=reviewer retry verdict=%s", turn_id, verdict2 or "UNKNOWN")
            reply = final2 or draft2
        else:
            reply = final or draft

        self.history.append(("assistant", reply))
        return reply
