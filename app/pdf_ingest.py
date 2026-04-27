"""Shared PDF upload → ingest pipeline for Chat and Documents pages."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from src.chat import ChatAssistant


async def ingest_upload_pdf_stream(
    assistant: ChatAssistant,
    file_path: str,
    original_name: str,
    *,
    use_enrichment: bool,
    show_ingestion_logs: bool,
) -> AsyncIterator[tuple[str, object]]:
    """Yield `("progress", current, total)` then `("done", result_str)` from ingest."""
    if show_ingestion_logs:
        progress_updates: asyncio.Queue[tuple[int, int]] = asyncio.Queue()

        async def _on_progress(current: int, total: int):
            await progress_updates.put((current, total))

        ingest_task = asyncio.create_task(
            assistant.ingest_pdf(
                file_path,
                enrich=use_enrichment,
                on_progress=_on_progress,
                original_filename=original_name,
            )
        )
        while not ingest_task.done():
            try:
                current, total = await asyncio.wait_for(progress_updates.get(), timeout=0.25)
            except TimeoutError:
                continue
            yield ("progress", current, total)
        result = await ingest_task
    else:
        result = await assistant.ingest_pdf(
            file_path, enrich=use_enrichment, original_filename=original_name
        )
    assistant.sync_session_document()
    yield ("done", result)
