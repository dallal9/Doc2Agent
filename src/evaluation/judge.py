"""LLM-as-judge for Milestone 4.

Scores evaluation predictions against metrics, using the question, expected
answer, agent answer, agent think trace, context used by the agent (tool
returns / retrieved passages), and the annotation's evidence spans.
"""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field
from pydantic_ai import Agent

from src.agents.base import get_model_string, run_agent
from src.chat import ChatAssistant
from src.logging import setup_logging

logger = setup_logging("evaluation_judge")

ProgressCallback = Callable[[int, int, str], Awaitable[None] | None]


JUDGE_SYSTEM_PROMPT = (
    "You are an evaluation judge. Score the agent's answer against the given metric. "
    "You must return a JSON object with fields `score` (number) and `reason` (short string). "
    "Use the evidence (document spans, agent context, agent think trace) to justify your score. "
    "Be concise and factual."
)


class JudgeOutput(BaseModel):
    score: float = Field(description="Numeric score; for bool metrics use 0 or 1.")
    reason: str = Field(default="", description="Short explanation for the score.")


def _create_judge_agent(assistant: ChatAssistant) -> Agent[None, JudgeOutput]:
    """Build a one-shot judge agent reusing the reviewer's backend/model."""
    cfg = assistant.config
    agent_cfg = cfg.agents.get("reviewer") or next(iter(cfg.agents.values()))
    backend_cfg = cfg.backends[agent_cfg.backend]
    model_string = get_model_string(backend_cfg, agent_cfg.model)
    agent: Agent[None, JudgeOutput] = Agent(
        model_string,
        system_prompt=JUDGE_SYSTEM_PROMPT,
        output_type=JudgeOutput,
    )
    return agent


def _format_spans(spans: list[dict] | None) -> str:
    if not spans:
        return "(no evidence spans)"
    out = []
    for s in spans:
        kind = s.get("kind", "text")
        page = s.get("page_num", "?")
        text = (s.get("quoted_text") or "").strip()
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


def _build_judge_prompt(prediction: dict, metric: dict) -> str:
    metric_prompt = (metric.get("judge_prompt") or "").strip()
    metric_prompt_block = (
        f"Metric judge guidance:\n{metric_prompt}\n\n" if metric_prompt else ""
    )
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
    spans_block = _format_spans(prediction.get("spans"))
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


async def judge_prediction(
    judge_agent: Agent[None, JudgeOutput],
    prediction: dict,
    metric: dict,
) -> tuple[float, str]:
    """Score one (prediction, metric) pair. Returns (clipped_score, reason)."""
    prompt = _build_judge_prompt(prediction, metric)
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
) -> dict:
    """Iterate predictions × metrics, persist one EvaluationResult per pair."""
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
    total = len(predictions) * len(metrics)
    if total == 0:
        store.update_judge_run_status(judge_run_id, "completed", completed=True)
        return {"judge_run_id": judge_run_id, "status": "completed", "total": 0}

    store.update_judge_run_status(judge_run_id, "running")
    judge_agent = _create_judge_agent(assistant)

    done = 0
    ok = 0
    failed = 0
    for pred in predictions:
        # enrich prediction with spans
        full = store.get_prediction(pred["prediction_id"]) or pred
        for metric in metrics:
            try:
                score, reason = await judge_prediction(judge_agent, full, metric)
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
                ok += 1
            except Exception as e:
                logger.exception(
                    "Judge failed prediction=%s metric=%s",
                    full.get("prediction_id"),
                    metric.get("metric_id"),
                )
                failed += 1
                _ = e
            done += 1
            if on_progress:
                maybe: Any = on_progress(done, total, metric["name"])
                if hasattr(maybe, "__await__"):
                    await maybe

    final_status = "completed" if failed == 0 else "failed"
    store.update_judge_run_status(judge_run_id, final_status, completed=True)
    return {
        "judge_run_id": judge_run_id,
        "status": final_status,
        "total": total,
        "success": ok,
        "failed": failed,
    }
