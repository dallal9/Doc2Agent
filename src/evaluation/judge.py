"""LLM-as-judge for Milestone 4.

Scores evaluation predictions against metrics, using the question, expected
answer, agent answer, agent think trace, context used by the agent (tool
returns / retrieved passages), and the annotation's evidence spans.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel

from src.agents.base import build_model, run_agent
from src.chat import ChatAssistant
from src.logging import setup_logging

logger = setup_logging("evaluation_judge")

ProgressCallback = Callable[[int, int, str], Awaitable[None] | None]


class JudgeOutput(BaseModel):
    score: float = Field(description="Numeric score; for bool metrics use 0 or 1.")
    reason: str = Field(default="", description="Short explanation for the score.")


class MetricResult(BaseModel):
    metric_name: str = Field(description="Name of the metric being scored, verbatim.")
    score: float = Field(description="Numeric score; for bool metrics use 0 or 1.")
    reason: str = Field(default="", description="Short explanation for the score.")


class BatchJudgeOutput(BaseModel):
    results: list[MetricResult] = Field(
        description="One entry per metric. Use the metric names listed in the prompt verbatim.",
    )


def _resolve_judge_agent_config(
    assistant: ChatAssistant,
    *,
    model_override: str | None,
    backend_override: str | None,
) -> tuple[OpenAIChatModel, str]:
    """Resolve (model, backend_name) for the judge agent."""
    cfg = assistant.config
    agent_cfg = (
        cfg.agents.get("judge") or cfg.agents.get("reviewer") or next(iter(cfg.agents.values()))
    )
    backend_name = backend_override or agent_cfg.backend
    if backend_name not in cfg.backends:
        raise ValueError(f"Unknown backend for judge: {backend_name}")
    backend_cfg = cfg.backends[backend_name]
    return build_model(backend_cfg, model_override or agent_cfg.model), backend_name


def _create_judge_agent(
    assistant: ChatAssistant,
    *,
    model_override: str | None = None,
    backend_override: str | None = None,
) -> Agent[None, JudgeOutput]:
    """Build a one-shot per-metric judge agent (legacy; kept for compatibility)."""
    model, _ = _resolve_judge_agent_config(
        assistant, model_override=model_override, backend_override=backend_override
    )
    agent: Agent[None, JudgeOutput] = Agent(
        model,
        system_prompt=assistant.prompts.judge,
        output_type=JudgeOutput,
    )
    return agent


def _create_batch_judge_agent(
    assistant: ChatAssistant,
    *,
    model_override: str | None = None,
    backend_override: str | None = None,
) -> Agent[None, BatchJudgeOutput]:
    """Build a judge agent that scores all selected metrics in one call."""
    model, _ = _resolve_judge_agent_config(
        assistant, model_override=model_override, backend_override=backend_override
    )
    agent: Agent[None, BatchJudgeOutput] = Agent(
        model,
        system_prompt=assistant.prompts.judge,
        output_type=BatchJudgeOutput,
    )
    return agent


SPAN_PAGE_MAX_CHARS = 4000


def _format_spans(spans: list[dict] | None, store=None, doc_id: str | None = None) -> str:
    if not spans:
        return "(no evidence spans)"
    out = []
    for s in spans:
        kind = s.get("kind", "text")
        page = s.get("page_num", "?")
        text = (s.get("quoted_text") or "").strip()
        if kind == "page" and not text and store is not None and doc_id and isinstance(page, int):
            page_text = (store.get_page_text(doc_id, page) or "").strip()
            if page_text:
                if len(page_text) > SPAN_PAGE_MAX_CHARS:
                    page_text = page_text[:SPAN_PAGE_MAX_CHARS] + "…"
                out.append(f"[Page {page}] (full page)\n{page_text}")
                continue
        if kind == "page" and not text:
            out.append(f"[Page {page}] (full page referenced)")
        elif text:
            out.append(f"[Page {page}] {text}")
    return "\n".join(out) or "(no evidence spans)"


def _clip_score(score: float, metric: dict) -> float:
    """Coerce the LLM's score into the metric's valid range/type."""
    mtype = metric.get("type", "float")
    meta = metric.get("metadata") or {}
    try:
        value = float(score)
    except (TypeError, ValueError):
        value = 0.0
    if mtype == "bool":
        return 1.0 if value >= 0.5 else 0.0
    if mtype == "int":
        value = float(int(round(value)))
    lo = meta.get("min")
    hi = meta.get("max")
    if lo is not None:
        try:
            value = max(float(lo), value)
        except (TypeError, ValueError):
            pass
    if hi is not None:
        try:
            value = min(float(hi), value)
        except (TypeError, ValueError):
            pass
    return value


def _build_judge_prompt(prediction: dict, metric: dict, store=None) -> str:
    metric_prompt = (metric.get("judge_prompt") or "").strip()
    metric_prompt_block = f"Metric judge guidance:\n{metric_prompt}\n\n" if metric_prompt else ""
    mtype = metric.get("type", "float")
    if mtype == "bool":
        scale_hint = "Output score as 0 (false) or 1 (true)."
    elif mtype == "int":
        meta = metric.get("metadata") or {}
        lo = meta.get("min", 0)
        hi = meta.get("max", 5)
        scale_hint = f"Output an integer score in [{lo}, {hi}]."
    else:
        meta = metric.get("metadata") or {}
        lo = meta.get("min", 0.0)
        hi = meta.get("max", 1.0)
        scale_hint = f"Output a float score in [{lo}, {hi}]."

    question = prediction.get("question") or ""
    expected = prediction.get("expected_answer") or ""
    answer = prediction.get("agent_answer") or ""
    thoughts = prediction.get("agent_thoughts") or ""
    context = prediction.get("context_used") or ""
    spans_block = _format_spans(prediction.get("spans"), store, prediction.get("doc_id"))
    doc_ref = prediction.get("doc_name") or prediction.get("document_reference") or "—"

    return (
        f"Metric: {metric['name']}\n"
        f"Metric description: {metric.get('description', '')}\n"
        f"{metric_prompt_block}"
        f"{scale_hint}\n\n"
        f"Document: {doc_ref}\n\n"
        f"Question:\n{question}\n\n"
        f"Expected answer:\n{expected}\n\n"
        f"Agent answer:\n{answer}\n\n"
        f"Agent think trace (may be empty):\n{thoughts or '(none)'}\n\n"
        f"Agent context / retrieved text references (may be empty):\n"
        f"{context or '(none)'}\n\n"
        f"Annotation evidence spans:\n{spans_block}\n"
    )


def _scale_hint(metric: dict) -> str:
    mtype = metric.get("type", "float")
    meta = metric.get("metadata") or {}
    if mtype == "bool":
        return "0 (false) or 1 (true)"
    if mtype == "int":
        lo = meta.get("min", 0)
        hi = meta.get("max", 5)
        return f"integer in [{lo}, {hi}]"
    lo = meta.get("min", 0.0)
    hi = meta.get("max", 1.0)
    return f"float in [{lo}, {hi}]"


def _build_batch_judge_prompt(prediction: dict, metrics: list[dict], store=None) -> str:
    """Build the user message for a batch (multi-metric) judge call.

    The system prompt (assistant.prompts.judge) is the global preamble. This
    function supplies the metric rubric block followed by the prediction
    context, and instructs the model to produce one entry per metric using
    the listed metric names verbatim.
    """
    rubric_lines = ["Metrics to score (use these names VERBATIM in `metric_name`):"]
    for m in metrics:
        name = m.get("name") or m.get("metric_id")
        desc = (m.get("description") or "").strip()
        guidance = (m.get("judge_prompt") or "").strip()
        rubric_lines.append(f"- {name} ({_scale_hint(m)}): {desc}")
        if guidance:
            for ln in guidance.splitlines():
                rubric_lines.append(f"    {ln}")
    rubric = "\n".join(rubric_lines)

    question = prediction.get("question") or ""
    expected = prediction.get("expected_answer") or ""
    answer = prediction.get("agent_answer") or ""
    thoughts = prediction.get("agent_thoughts") or ""
    context = prediction.get("context_used") or ""
    spans_block = _format_spans(prediction.get("spans"), store, prediction.get("doc_id"))
    doc_ref = prediction.get("doc_name") or prediction.get("document_reference") or "—"

    return (
        f"{rubric}\n\n"
        f"Return one MetricResult per metric above. Do not invent metrics.\n\n"
        f"Document: {doc_ref}\n\n"
        f"Question:\n{question}\n\n"
        f"Expected answer:\n{expected}\n\n"
        f"Agent answer:\n{answer}\n\n"
        f"Agent think trace (may be empty):\n{thoughts or '(none)'}\n\n"
        f"Agent context / retrieved text references (may be empty):\n"
        f"{context or '(none)'}\n\n"
        f"Annotation evidence spans:\n{spans_block}\n"
    )


async def judge_prediction_batch(
    judge_agent: Agent[None, BatchJudgeOutput],
    prediction: dict,
    metrics: list[dict],
    store=None,
) -> dict[str, tuple[float, str]]:
    """Score one prediction against all selected metrics in a single call.

    Returns a dict keyed by metric_id of (clipped_score, reason). Metrics the
    LLM omitted are absent; metrics it hallucinated (unknown name) are
    dropped with a warning.
    """
    prompt = _build_batch_judge_prompt(prediction, metrics, store)
    result = await run_agent(judge_agent, prompt, label="judge")
    out = result.output
    if isinstance(out, BatchJudgeOutput):
        items = out.results
    elif isinstance(out, dict) and isinstance(out.get("results"), list):
        items = [MetricResult.model_validate(r) for r in out["results"]]
    else:
        items = []

    name_to_metric = {(m.get("name") or "").strip().lower(): m for m in metrics}
    scored: dict[str, tuple[float, str]] = {}
    for item in items:
        key = (item.metric_name or "").strip().lower()
        metric = name_to_metric.get(key)
        if not metric:
            logger.warning("Judge returned unknown metric_name=%r; dropping", item.metric_name)
            continue
        scored[metric["metric_id"]] = (_clip_score(item.score, metric), item.reason or "")
    return scored


async def judge_prediction(
    judge_agent: Agent[None, JudgeOutput],
    prediction: dict,
    metric: dict,
    store=None,
) -> tuple[float, str]:
    """Score one (prediction, metric) pair. Returns (clipped_score, reason)."""
    prompt = _build_judge_prompt(prediction, metric, store)
    result = await run_agent(judge_agent, prompt, label="judge")
    out = result.output
    if isinstance(out, JudgeOutput):
        raw_score, reason = out.score, out.reason
    elif isinstance(out, dict):
        raw_score, reason = out.get("score", 0), out.get("reason", "")
    else:
        raw_score, reason = 0.0, str(out or "")
    return _clip_score(raw_score, metric), reason or ""


async def run_llm_judge(
    *,
    assistant: ChatAssistant,
    judge_run_id: str,
    on_progress: ProgressCallback | None = None,
    model_override: str | None = None,
    backend_override: str | None = None,
    concurrency: int | None = None,
) -> dict:
    """Score every prediction against all selected metrics in ONE LLM call per
    prediction (so total calls = #predictions, not #predictions × #metrics).

    `concurrency` (or `JUDGE_CONCURRENCY` env) bounds parallel predictions.
    >1 only helps with remote backends; local Ollama should stay at 1.
    """
    store = assistant.store
    jr = store.get_judge_run(judge_run_id)
    if not jr:
        raise ValueError(f"Judge run not found: {judge_run_id}")
    evaluation_run_id = jr["evaluation_run_id"]
    metric_ids: list[str] = jr["metric_ids"]
    metrics = [m for m in (store.get_metric(mid) for mid in metric_ids) if m]
    if not metrics:
        store.update_judge_run_status(judge_run_id, "failed", completed=True)
        return {"judge_run_id": judge_run_id, "status": "failed", "reason": "no metrics"}

    predictions = store.list_predictions(evaluation_run_id)
    predictions = [p for p in predictions if p.get("status") == "success"]
    total = len(predictions) * len(metrics)  # results to write, used for progress
    if total == 0:
        store.update_judge_run_status(judge_run_id, "completed", completed=True)
        return {"judge_run_id": judge_run_id, "status": "completed", "total": 0}

    store.update_judge_run_status(judge_run_id, "running")
    judge_agent = _create_batch_judge_agent(
        assistant, model_override=model_override, backend_override=backend_override
    )

    if concurrency is None:
        concurrency = int(os.getenv("JUDGE_CONCURRENCY", "1") or "1")
    concurrency = max(1, concurrency)
    sem = asyncio.Semaphore(concurrency)
    progress_lock = asyncio.Lock()
    counters = {"done": 0, "ok": 0, "failed": 0}

    full_preds = [store.get_prediction(p["prediction_id"]) or p for p in predictions]

    async def _judge_prediction(full: dict) -> None:
        async with sem:
            try:
                scored = await judge_prediction_batch(judge_agent, full, metrics, store)
                ok_local = 0
                failed_local = 0
                for metric in metrics:
                    pair = scored.get(metric["metric_id"])
                    if pair is None:
                        logger.warning(
                            "Judge missing metric=%s for prediction=%s",
                            metric.get("metric_id"),
                            full.get("prediction_id"),
                        )
                        failed_local += 1
                        continue
                    score, reason = pair
                    store.upsert_evaluation_result(
                        judge_run_id=judge_run_id,
                        evaluation_run_id=evaluation_run_id,
                        prediction_id=full["prediction_id"],
                        annotation_id=full["annotation_id"],
                        metric_id=metric["metric_id"],
                        score=score,
                        judge_type="llm",
                        comment=None,
                        judge_reasoning=reason,
                    )
                    ok_local += 1
            except Exception:
                logger.exception(
                    "Batch judge failed prediction=%s",
                    full.get("prediction_id"),
                )
                ok_local = 0
                failed_local = len(metrics)
        async with progress_lock:
            counters["ok"] += ok_local
            counters["failed"] += failed_local
            counters["done"] += ok_local + failed_local
            if on_progress:
                label = metrics[-1]["name"] if metrics else ""
                maybe: Any = on_progress(counters["done"], total, label)
                if hasattr(maybe, "__await__"):
                    await maybe

    await asyncio.gather(*(_judge_prediction(full) for full in full_preds))

    final_status = "completed" if counters["failed"] == 0 else "failed"
    store.update_judge_run_status(judge_run_id, final_status, completed=True)
    return {
        "judge_run_id": judge_run_id,
        "status": final_status,
        "total": total,
        "success": counters["ok"],
        "failed": counters["failed"],
    }
