"""Evaluation runner — execute a dataset against the Chat pipeline.

Milestone 3: reuses the existing main agent. Each annotation is run as a
fresh one-turn query (no prior chat history) against its linked document.

Supports run-time configuration:
  - `concurrency`: int (default 1) — max annotations run in parallel per doc
  - `max_samples`: int | null (default null) — cap total annotations
"""

from __future__ import annotations

import asyncio
import random
import re
from collections import defaultdict
from typing import Any, Awaitable, Callable

from src.agents import run_agent
from src.agents.main import MainDeps
from src.chat import ChatAssistant
from src.logging import setup_logging

logger = setup_logging("evaluation_runner")

ProgressCallback = Callable[[int, int, str], Awaitable[None] | None]


CONTEXT_MODES = ("full_doc", "spans_only", "question_only")

DEFAULT_CONFIG: dict[str, Any] = {
    "concurrency": 1,
    "max_samples": None,
    "shuffle": False,
    "seed": None,
    "context_mode": "full_doc",
}


def normalize_config(config: dict | None) -> dict:
    """Merge user config over defaults and coerce types. Unknown keys pass through."""
    cfg = {**DEFAULT_CONFIG, **(config or {})}
    try:
        cfg["concurrency"] = max(1, int(cfg.get("concurrency") or 1))
    except (TypeError, ValueError):
        cfg["concurrency"] = 1
    ms = cfg.get("max_samples")
    if ms in (None, "", 0, "0"):
        cfg["max_samples"] = None
    else:
        try:
            cfg["max_samples"] = max(1, int(ms))
        except (TypeError, ValueError):
            cfg["max_samples"] = None
    cfg["shuffle"] = bool(cfg.get("shuffle"))
    mode = str(cfg.get("context_mode") or "full_doc")
    if mode not in CONTEXT_MODES:
        mode = "full_doc"
    cfg["context_mode"] = mode
    return cfg


def _split_think(text: str) -> tuple[str, str | None]:
    m = re.search(r"<think>(.*?)</think>", text or "", re.DOTALL)
    if not m:
        return (text or "").strip(), None
    reasoning = m.group(1).strip()
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    return cleaned, reasoning


def _extract_context(result) -> str | None:
    parts: list[str] = []
    for msg in result.all_messages():
        for p in getattr(msg, "parts", []):
            if getattr(p, "part_kind", "") == "tool-return" and hasattr(p, "content"):
                content = str(p.content).strip()
                if content:
                    parts.append(content)
    return "\n\n---\n\n".join(parts) if parts else None


def _spans_block(spans: list[dict] | None) -> str:
    if not spans:
        return ""
    lines: list[str] = []
    for s in spans:
        kind = s.get("kind", "text")
        page = s.get("page_num", 0)
        text = (s.get("quoted_text") or "").strip()
        if kind == "page" and not text:
            lines.append(f"[Page {page}] (full page referenced)")
        elif text:
            lines.append(f"[Page {page}] {text}")
    if not lines:
        return ""
    return "Provided evidence (from annotation):\n" + "\n".join(lines) + "\n\n"


def _build_eval_prompt(
    assistant: ChatAssistant,
    question: str,
    *,
    context_mode: str = "full_doc",
    spans: list[dict] | None = None,
) -> tuple[str, MainDeps]:
    """Build a one-turn prompt without mutating assistant history.

    `context_mode`:
      - "full_doc": inline the whole document (same as chat pipeline).
      - "spans_only": include only the annotation's spans as context.
      - "question_only": no document context at all.
    """
    pi_block = ""
    if assistant.personal_info and assistant.personal_info.data:
        pi_block = f"{assistant.personal_info.to_prompt_context()}\n\n"

    doc_block = ""
    if context_mode == "full_doc":
        max_chars = assistant.inline_doc_max_chars
        if assistant.enriched_doc and assistant.enriched_doc.total_chars() <= max_chars:
            pages_summary = "\n".join(
                (
                    f"[Page {p.page_num}] {p.text[:500]}..."
                    if len(p.text) > 500
                    else f"[Page {p.page_num}] {p.text}"
                )
                for p in assistant.enriched_doc.pages
            )
            doc_block = f"Document pages:\n{pages_summary}\n\n"
        elif assistant.text and len(assistant.text) <= max_chars:
            doc_block = f"Document text (full):\n{assistant.text}\n\n"
        elif assistant.text:
            doc_block = f"Document text (truncated):\n{assistant.text[:max_chars]}\n\n"
    elif context_mode == "spans_only":
        doc_block = _spans_block(spans)
    # "question_only" → no doc_block

    # deps still reference the loaded doc so tools (search_fts, query_pages)
    # remain callable if the agent chooses to use them.
    deps = MainDeps(
        document=assistant.document,
        text=assistant.text,
        personal_info=assistant.personal_info,
        document_id=assistant.document_id,
        store=assistant.store,
    )
    prompt = f"{pi_block}{doc_block}User message: {question}"
    return prompt, deps


async def _run_one(
    assistant: ChatAssistant,
    ann: dict,
    run_id: str,
    dataset_id: str,
    *,
    context_mode: str = "full_doc",
) -> str:
    """Execute one annotation against the currently-loaded document.

    Returns the status string ('success' | 'failed'). Persists the prediction.
    """
    annotation_id = ann["annotation_id"]
    doc_id = ann.get("doc_id")
    store = assistant.store
    try:
        prompt, deps = _build_eval_prompt(
            assistant,
            ann["question"],
            context_mode=context_mode,
            spans=ann.get("spans"),
        )
        result = await run_agent(assistant.main, prompt, deps=deps, label="eval")
        raw_output = result.output or ""
        answer, reasoning = _split_think(raw_output)
        context = _extract_context(result)
        doc_meta = store.get_document_metadata(doc_id) if doc_id else None
        doc_ref = doc_meta.file_name if doc_meta else doc_id

        store.save_prediction(
            run_id=run_id,
            dataset_id=dataset_id,
            annotation_id=annotation_id,
            agent_answer=answer,
            agent_thoughts=reasoning,
            document_reference=doc_ref,
            context_used=context,
            status="success",
            error_message=None,
        )
        return "success"
    except Exception as e:
        logger.exception("Prediction failed for annotation=%s", annotation_id)
        store.save_prediction(
            run_id=run_id,
            dataset_id=dataset_id,
            annotation_id=annotation_id,
            agent_answer=None,
            agent_thoughts=None,
            document_reference=doc_id,
            context_used=None,
            status="failed",
            error_message=str(e),
        )
        return "failed"


async def run_evaluation(
    *,
    assistant: ChatAssistant,
    run_id: str,
    config: dict | None = None,
    on_progress: ProgressCallback | None = None,
) -> dict:
    """Execute a previously-created evaluation run.

    `config` accepts: concurrency (int), max_samples (int|null), shuffle (bool),
    seed (int|null). The full resolved config is returned for logging.
    """
    store = assistant.store
    run = store.get_evaluation_run(run_id)
    if not run:
        raise ValueError(f"Evaluation run not found: {run_id}")
    dataset_id = run["dataset_id"]

    cfg = normalize_config(config)
    logger.info("Evaluation run=%s config=%s", run_id, cfg)

    annotations = store.list_dataset_annotations(dataset_id)
    if cfg["shuffle"]:
        rng = random.Random(cfg.get("seed"))
        rng.shuffle(annotations)
    if cfg["max_samples"]:
        annotations = annotations[: cfg["max_samples"]]

    total = len(annotations)
    store.update_run_status(run_id, "running")
    counts = {"success": 0, "failed": 0, "skipped": 0}

    # Group by doc_id so we only swap the loaded document once per group.
    groups: dict[str | None, list[dict]] = defaultdict(list)
    for ann in annotations:
        groups[ann.get("doc_id")].append(ann)

    sem = asyncio.Semaphore(cfg["concurrency"])
    done = 0

    async def _guarded(ann: dict) -> str:
        async with sem:
            status = await _run_one(
                assistant, ann, run_id, dataset_id, context_mode=cfg["context_mode"]
            )
        nonlocal done
        done += 1
        if on_progress:
            maybe = on_progress(done, total, ann["question"][:60])
            if asyncio.iscoroutine(maybe):
                await maybe
        return status

    for doc_id, group in groups.items():
        if doc_id is None:
            for ann in group:
                store.save_prediction(
                    run_id=run_id,
                    dataset_id=dataset_id,
                    annotation_id=ann["annotation_id"],
                    agent_answer=None,
                    agent_thoughts=None,
                    document_reference=None,
                    context_used=None,
                    status="skipped",
                    error_message="annotation has no linked document",
                )
                counts["skipped"] += 1
                done += 1
                if on_progress:
                    maybe = on_progress(done, total, ann["question"][:60])
                    if asyncio.iscoroutine(maybe):
                        await maybe
            continue

        assistant.load_cached_document(doc_id)
        assistant.history = []
        results = await asyncio.gather(*[_guarded(ann) for ann in group])
        for s in results:
            counts[s] = counts.get(s, 0) + 1

    final_status = "completed" if counts["failed"] == 0 else "failed"
    store.update_run_status(run_id, final_status, completed=True)
    logger.info("Evaluation run=%s %s counts=%s total=%d", run_id, final_status, counts, total)
    return {
        "run_id": run_id,
        "status": final_status,
        "total": total,
        "config": cfg,
        **counts,
    }
