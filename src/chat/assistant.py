from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable

from src.agents import create_ingestion_agent, create_main_agent, ingest_page
from src.agents.main import MainDeps
from src.agents_config import load_agents_config, load_personal_info, load_prompts_config
from src.logging import setup_logging
from src.schemas import DocumentMetadata, DocumentSchema, StructuredDocument
from src.storage import SQLiteStore
from src.tools import (
    PDFParser,
    document_schema_to_structured,
    extract_text_full,
    parse_pdf_to_document,
)

logger = setup_logging("chat_assistant")

ProgressCallback = Callable[[int, int], None]  # (current_page, total_pages)


class ChatAssistant:
    def __init__(self):
        self.config = load_agents_config()
        self.prompts = load_prompts_config()
        self.personal_info = load_personal_info()
        self.document: StructuredDocument | None = None
        self.enriched_doc: DocumentSchema | None = None
        self.document_id: str | None = None
        self.session_id: str | None = None
        self.text: str = ""
        self.history: list[tuple[str, str]] = []
        logger.info("Initializing ChatAssistant backend=%s", self.config.default_backend)
        self._init_agents()
        self.inline_doc_max_chars = int(os.getenv("INLINE_DOC_MAX_CHARS", "20000"))
        self.pdf_json_max_bytes = int(os.getenv("PDF_JSON_MAX_BYTES", "2000000"))
        self.pdf_json_dir = os.getenv("PDF_JSON_DIR", "data")
        # SQLite dir for all database files
        self.pdf_sqlite_dir = Path(os.getenv("PDF_SQLITE_DIR", "data"))
        self.pdf_sqlite_dir.mkdir(exist_ok=True)
        self.pdf_sqlite_path = self.pdf_sqlite_dir / "pdf_data.db"
        # PDF storage dir for permanent copies
        self.pdf_storage_dir = Path(os.getenv("PDF_STORAGE_DIR", "data/pdfs"))
        self.pdf_storage_dir.mkdir(parents=True, exist_ok=True)
        # Initialize SQLite store eagerly for unified caching
        self.store = SQLiteStore(str(self.pdf_sqlite_path))
        # Query cache settings
        self.query_cache_enabled = os.getenv("QUERY_CACHE_ENABLED", "true").lower() == "true"
        self.query_cache_max_per_file = int(os.getenv("QUERY_CACHE_MAX_PER_FILE", "10"))

    def set_text(self, text: str) -> None:
        """Set raw document text for prompt context (used by unit tests)."""
        self.text = text or ""

    async def chat(self, user_message: str) -> str:
        """Run one chat turn against the main agent."""
        prompt, deps = self.prepare_turn(user_message)
        result = await self.main.run(prompt, deps=deps)
        reply = result.output if hasattr(result, "output") else result
        return self.finalize_turn(reply)

    def _normalize_query(self, query: str) -> str:
        """Normalize query for cache matching: trim whitespace and lowercase."""
        return query.strip().lower()

    def prepare_turn(self, user_message: str) -> tuple[str, MainDeps]:
        """Prepare prompt + deps for a chat turn."""
        self.history.append(("user", user_message))
        recent = self.history[-12:]
        history_text = "\n".join(f"{role}: {msg}" for role, msg in recent)

        pi_block = ""
        if self.personal_info and self.personal_info.data:
            pi_block = f"{self.personal_info.to_prompt_context()}\n\n"

        doc_block = ""
        if self.enriched_doc and self.enriched_doc.total_chars() <= self.inline_doc_max_chars:
            # Inline enriched pages for small docs
            pages_summary = "\n".join(
                (
                    f"[Page {p.page_num}] {p.text[:500]}..."
                    if len(p.text) > 500
                    else f"[Page {p.page_num}] {p.text}"
                )
                for p in self.enriched_doc.pages
            )
            doc_block = f"Document pages:\n{pages_summary}\n\n"
            logger.info("turn=%d inline_enriched=true", len(self.history) // 2)
        elif self.text and len(self.text) <= self.inline_doc_max_chars:
            doc_block = f"Document text (full):\n{self.text}\n\n"
            logger.info("turn=%d inline_doc=true chars=%d", len(self.history) // 2, len(self.text))
        elif self.text:
            doc_block = f"Document text (truncated):\n{self.text[:self.inline_doc_max_chars]}\n\n"
            logger.info("turn=%d inline_doc=false use_tools=true", len(self.history) // 2)

        prompt = (
            f"{pi_block}{doc_block}Conversation so far:\n{history_text}\n\n"
            f"User message: {user_message}"
        )
        deps = MainDeps(
            document=self.document,
            text=self.text,
            personal_info=self.personal_info,
            document_id=self.document_id,
            store=self.store,
        )
        return prompt, deps

    def finalize_turn(self, reply: str) -> str:
        self.history.append(("assistant", reply))
        return reply

    def _init_agents(self):
        self.main = create_main_agent(self.config, self.prompts)

    def load_pdf(self, path: str) -> str:
        """Legacy loader using pypdf."""
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

    async def ingest_pdf(
        self,
        file_path: str,
        enrich: bool = True,
        on_progress: ProgressCallback | None = None,
        original_filename: str | None = None,
    ) -> str:
        """Ingest PDF with cache-first logic, PyMuPDF parser, and optional LLM enrichment."""
        p = Path(file_path)
        if not p.exists():
            logger.warning("File not found: %s", file_path)
            return f"File not found: {file_path}"

        # Get file stats for cache check
        stat = p.stat()
        mod_time = stat.st_mtime

        # Check cache first
        existing = self.store.get_document_by_path(file_path)
        if existing and existing.file_mod_time == mod_time:
            logger.info("Cache hit for %s (doc_id=%s)", file_path, existing.doc_id)
            cached_doc = self.store.load_document(existing.doc_id)
            if cached_doc:
                self._set_active_document(cached_doc)
                return f"Loaded cached: {existing.file_name} ({existing.page_count} pages)"

        # Cache miss - parse PDF
        logger.info("Ingesting PDF: %s enrich=%s", file_path, enrich)
        with PDFParser(file_path) as parser:
            doc = parser.parse_document()

        # Use original filename if provided (from upload), otherwise use path name
        if original_filename:
            doc.metadata.file_name = original_filename

        # Add cache invalidation fields to metadata
        file_hash = hashlib.md5(p.read_bytes()).hexdigest()
        doc.metadata.file_mod_time = mod_time
        doc.metadata.file_hash = file_hash

        # Copy PDF to permanent storage
        permanent_path = self.pdf_storage_dir / f"{doc.metadata.doc_id}.pdf"
        shutil.copy2(file_path, permanent_path)
        doc.metadata.file_path = str(permanent_path)
        logger.info("Copied PDF to: %s", permanent_path)

        if enrich:
            ing_agent = create_ingestion_agent(self.config, self.prompts)
            total = len(doc.pages)
            for i, page in enumerate(doc.pages, 1):
                page_input = page.model_dump()
                try:
                    enriched = await ingest_page(ing_agent, page_input)
                    # Merge enriched fields
                    page.contains_names = enriched.contains_names
                    page.contains_dates = enriched.contains_dates
                    page.contains_locations = enriched.contains_locations
                    page.contains_signatures = enriched.contains_signatures
                    page.contains_personal_info = enriched.contains_personal_info
                    page.headings = enriched.headings
                    page.languages = enriched.languages
                    page.keywords = enriched.keywords
                except Exception as e:
                    logger.warning("ingestion failed page=%d error=%s", page.page_num, e)
                if on_progress:
                    await on_progress(i, total)

        self._set_active_document(doc)

        # Always save to SQLite (unified cache)
        self.store.insert_document(doc)
        logger.info("Saved to SQLite: %s", self.pdf_sqlite_path)

        # Optional JSON export for small files
        if doc.metadata.file_size_bytes <= self.pdf_json_max_bytes:
            data_dir = Path(self.pdf_json_dir)
            data_dir.mkdir(exist_ok=True)
            json_path = data_dir / f"{doc.metadata.doc_id}.json"
            json_path.write_text(doc.model_dump_json(indent=2))
            logger.info("Exported to JSON: %s", json_path)

        return f"Ingested {doc.metadata.page_count} pages (doc_id={doc.metadata.doc_id})"

    def _set_active_document(self, doc: DocumentSchema) -> None:
        """Set the active document for chat context."""
        self.enriched_doc = doc
        self.document_id = doc.metadata.doc_id
        self.document = document_schema_to_structured(doc)
        self.text = "\n\n".join(p.text for p in doc.pages)

    def get_cached_query(self, user_message: str) -> dict | None:
        """Check if query is cached. Returns cached data or None."""
        if not self.query_cache_enabled or not self.document_id:
            return None
        normalized = self._normalize_query(user_message)
        return self.store.get_cached_query(self.document_id, normalized)

    def save_query_cache(self, user_message: str, output: str, traces: list, logs: dict) -> None:
        """Save query result to cache."""
        if not self.query_cache_enabled or not self.document_id:
            return
        normalized = self._normalize_query(user_message)
        self.store.save_query_cache(
            self.document_id,
            normalized,
            user_message,
            output,
            traces,
            logs,
            self.query_cache_max_per_file,
        )

    def list_cached_documents(self) -> list[DocumentMetadata]:
        """List all cached documents from SQLite."""
        return self.store.list_documents()

    def load_cached_document(self, doc_id: str) -> str:
        """Load a cached document by ID."""
        doc = self.store.load_document(doc_id)
        if not doc:
            logger.warning("Document not found: %s", doc_id)
            return f"Document not found: {doc_id}"
        self._set_active_document(doc)
        logger.info("Loaded cached doc_id=%s pages=%d", doc_id, doc.metadata.page_count)
        return f"Loaded {doc.metadata.file_name} ({doc.metadata.page_count} pages)"

    def delete_cached_document(self, doc_id: str) -> str:
        """Delete a cached document and its PDF file."""
        # Get metadata before deletion to find PDF path
        meta = self.store.get_document_metadata(doc_id)
        if not meta:
            logger.warning("Document not found for deletion: %s", doc_id)
            return f"Document not found: {doc_id}"

        # Delete from database
        self.store.delete_document(doc_id)

        # Delete PDF file if it exists in our storage
        pdf_path = Path(meta.file_path)
        if pdf_path.exists() and self.pdf_storage_dir in pdf_path.parents:
            pdf_path.unlink()
            logger.info("Deleted PDF file: %s", pdf_path)

        # Clear active doc if it was the deleted one
        if self.document_id == doc_id:
            self.enriched_doc = None
            self.document_id = None
            self.text = ""

        logger.info("Deleted cached doc_id=%s", doc_id)
        return f"Deleted document {doc_id}"

    def create_chat_session(self, title: str | None = None) -> str:
        timestamp_title = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        session_title = (title or timestamp_title).strip() or timestamp_title
        self.session_id = self.store.create_chat_session(
            title=session_title, doc_id=self.document_id
        )
        return self.session_id

    def list_chat_sessions(self, limit: int = 30) -> list[dict]:
        return self.store.list_chat_sessions(limit=limit)

    def load_chat_session(self, session_id: str) -> list[dict]:
        messages = self.store.get_chat_messages(session_id)
        self.session_id = session_id
        self.history = [
            (msg["role"], msg["content"])
            for msg in messages
            if msg["role"] in {"user", "assistant"}
        ]
        return [{"role": msg["role"], "content": msg["content"]} for msg in messages]

    def save_chat_message(self, role: str, content: str) -> None:
        if not self.session_id:
            return
        self.store.save_chat_message(session_id=self.session_id, role=role, content=content)

    def sync_session_document(self) -> None:
        if not self.session_id:
            return
        self.store.update_chat_session_doc(self.session_id, self.document_id)

    def clear_current_session_messages(self) -> int:
        if not self.session_id:
            return 0
        self.history = []
        return self.store.clear_chat_messages(self.session_id)

    def clear_all_sessions(self) -> int:
        self.session_id = None
        self.history = []
        return self.store.clear_all_chat_sessions()

    def get_current_session(self) -> dict | None:
        if not self.session_id:
            return None
        return self.store.get_chat_session(self.session_id)
