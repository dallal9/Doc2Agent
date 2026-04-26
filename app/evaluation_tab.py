"""Evaluation page — Execution Run tab (Milestone 3).

Runs a selected dataset against the existing chat agent and stores one
`EvaluationPrediction` per annotation. Reuses the existing Chat pipeline.
"""

from __future__ import annotations

import html
import json
import os
import re
import tempfile
from datetime import datetime

import gradio as gr

from app.ui_components import fmt_duration_ms, fmt_score, render_table
from src.chat import ChatAssistant
from src.evaluation import run_evaluation, run_llm_judge
from src.evaluation.runner import normalize_config
from src.logging import setup_logging

METRIC_TYPES = ["bool", "int", "float"]
AGGREGATIONS = ["avg", "sum", "min", "max"]

logger = setup_logging("evaluation_tab")


# ---- run naming helpers ---------------------------------------------------


def _slugify(s: str) -> str:
    """Lowercase, collapse non-alphanum to '-', trim leading/trailing '-'."""
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def _auto_run_name_from_dataset(
    dataset_id: str | None, keyword: str, assistant: ChatAssistant | None
) -> str:
    """Build `{YYYYMMDD_HHMM}_{dataset-slug}[_{keyword-slug}]`.

    Returns "" if dataset is unresolved so the textbox stays empty rather
    than showing a malformed prefix.
    """
    if not dataset_id or assistant is None:
        return ""
    ds = assistant.store.get_dataset(dataset_id)
    if not ds:
        return ""
    ds_slug = _slugify(ds.get("name") or "")
    if not ds_slug:
        return ""
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    parts = [stamp, ds_slug]
    kw_slug = _slugify(keyword or "")
    if kw_slug:
        parts.append(kw_slug)
    return "_".join(parts)


def _auto_run_name_from_eval_run(
    eval_run_id: str | None, keyword: str, assistant: ChatAssistant | None
) -> str:
    """Same format as _auto_run_name_from_dataset but resolves dataset via eval run."""
    if not eval_run_id or assistant is None:
        return ""
    run = assistant.store.get_evaluation_run(eval_run_id)
    if not run:
        return ""
    return _auto_run_name_from_dataset(run.get("dataset_id"), keyword, assistant)


# ---- choice builders ------------------------------------------------------


def _dataset_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    return [
        (f"{d['name']} ({d['annotation_count']} items)", d["dataset_id"])
        for d in assistant.store.list_datasets()
    ]


def _run_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    out = []
    for r in assistant.store.list_evaluation_runs():
        label = (
            f"{r['name']} · {r.get('dataset_name', '?')} · "
            f"{r['status']} ({r['prediction_count']})"
        )
        out.append((label, r["run_id"]))
    return out


def _results_html(assistant: ChatAssistant | None, run_id: str | None) -> str:
    """Render predictions as a scrollable, filterable table."""
    if assistant is None or not run_id:
        return ""
    preds = assistant.store.list_predictions(run_id)
    if not preds:
        return "<p><em>No predictions yet.</em></p>"
    status_colors = {"success": "#1a7f37", "failed": "#b42318", "skipped": "#8a6d00"}
    rows: list[list[object]] = []
    for p in preds:
        status = p["status"]
        rows.append(
            [
                (p.get("question") or "")[:400],
                (p.get("expected_answer") or "")[:400],
                (p.get("agent_answer") or "")[:400],
                p.get("doc_name") or p.get("document_reference") or "—",
                fmt_duration_ms(p.get("execution_time_ms")),
                (status, f"color:{status_colors.get(status, '#888')};font-weight:600"),
                (p.get("error_message") or "")[:200],
            ]
        )
    return render_table(
        ["Question", "Expected", "Agent answer", "Document", "Time", "Status", "Error"],
        rows,
        empty_msg="No predictions yet.",
        max_height=480,
    )


def _run_summary(assistant: ChatAssistant | None, run_id: str | None) -> str:
    if assistant is None or not run_id:
        return "_Select a run to see its summary._"
    run = assistant.store.get_evaluation_run(run_id)
    if not run:
        return "_Run not found._"
    preds = assistant.store.list_predictions(run_id)
    ok = sum(1 for p in preds if p["status"] == "success")
    failed = sum(1 for p in preds if p["status"] == "failed")
    skipped = sum(1 for p in preds if p["status"] == "skipped")
    cfg_str = run.get("agent_config_json") or ""
    try:
        cfg = json.loads(cfg_str) if cfg_str else {}
    except json.JSONDecodeError:
        cfg = {}
    cfg_line = ""
    if cfg:
        cfg_line = "**Config:** " + ", ".join(f"{k}={v}" for k, v in cfg.items())
    timing = assistant.store.get_run_timing(run_id)
    if timing["count"]:
        timing_line = (
            f"**Execution time:** total {fmt_duration_ms(timing['total_ms'])} · "
            f"avg {fmt_duration_ms(timing['avg_ms'])} (over {timing['count']} successful)"
        )
    else:
        timing_line = "**Execution time:** —"
    lines = [
        f"### {run['name']}",
        run.get("description") or "",
        f"**Status:** {run['status']} · **Dataset:** `{run['dataset_id']}`",
        f"**Predictions:** {len(preds)} — success: {ok} · failed: {failed} · skipped: {skipped}",
        timing_line,
        cfg_line,
    ]
    return "\n\n".join(l for l in lines if l)


# ---- handlers -------------------------------------------------------------


def on_tab_load(assistant):
    if assistant is None:
        assistant = ChatAssistant()
    return (
        assistant,
        gr.update(choices=_dataset_choices(assistant), value=None),
        gr.update(choices=_run_choices(assistant), value=None),
        "",
        "_Select a run to see its summary._",
    )


def on_refresh(assistant):
    if assistant is None:
        assistant = ChatAssistant()
    return (
        assistant,
        gr.update(choices=_dataset_choices(assistant)),
        gr.update(choices=_run_choices(assistant)),
    )


def _resolve_config(
    concurrency: float | int | None,
    max_samples: float | int | None,
    shuffle: bool,
    seed: float | int | None,
    context_mode: str | None,
    extra_json: str | None,
) -> tuple[dict, str | None]:
    """Merge form fields with optional JSON override. Returns (config, error)."""
    base = {
        "concurrency": int(concurrency or 1),
        "max_samples": int(max_samples) if max_samples else None,
        "shuffle": bool(shuffle),
        "seed": int(seed) if seed not in (None, "", 0) else None,
        "context_mode": context_mode or "full_doc",
    }
    raw = (extra_json or "").strip()
    if raw:
        try:
            overlay = json.loads(raw)
            if not isinstance(overlay, dict):
                return base, "Advanced config must be a JSON object."
            base.update(overlay)
        except json.JSONDecodeError as e:
            return base, f"Invalid JSON: {e}"
    return normalize_config(base), None


async def on_start_run(
    dataset_id,
    run_name,
    run_label,
    run_desc,
    concurrency,
    max_samples,
    shuffle,
    seed,
    context_mode,
    extra_json,
    assistant,
):
    if assistant is None:
        assistant = ChatAssistant()
    if not dataset_id:
        return (
            assistant,
            gr.update(),
            gr.update(),
            "Please select a dataset.",
            "",
            "_Select a run to see its summary._",
        )
    config, err = _resolve_config(concurrency, max_samples, shuffle, seed, context_mode, extra_json)
    if err:
        return (
            assistant,
            gr.update(),
            gr.update(),
            err,
            "",
            "_Select a run to see its summary._",
        )

    name = (run_name or "").strip() or "Eval run"
    label = (run_label or "").strip() or None
    desc = (run_desc or "").strip() or None

    run_id = assistant.store.create_evaluation_run(
        dataset_id=dataset_id,
        name=name,
        label=label,
        description=desc,
        agent_config=config,
    )
    logger.info("Started evaluation run=%s dataset=%s config=%s", run_id, dataset_id, config)

    try:
        summary = await run_evaluation(assistant=assistant, run_id=run_id, config=config)
        status_msg = (
            f"Run **{name}** {summary['status']}. "
            f"success: {summary['success']} · failed: {summary['failed']} · "
            f"skipped: {summary['skipped']} / {summary['total']} "
            f"(concurrency={config['concurrency']}, max_samples={config['max_samples']}, "
            f"context_mode={config['context_mode']})"
        )
    except Exception as e:
        logger.exception("Evaluation run failed run=%s", run_id)
        assistant.store.update_run_status(run_id, "failed", completed=True)
        status_msg = f"Run failed: {e}"

    return (
        assistant,
        gr.update(choices=_run_choices(assistant), value=run_id),
        gr.update(),
        status_msg,
        _results_html(assistant, run_id),
        _run_summary(assistant, run_id),
    )


def on_run_change(run_id, assistant):
    return _results_html(assistant, run_id), _run_summary(assistant, run_id)


def on_delete_run(run_id, assistant):
    if assistant is None or not run_id:
        return (
            assistant,
            gr.update(),
            "No run selected.",
            "",
            "_Select a run to see its summary._",
        )
    assistant.store.delete_evaluation_run(run_id)
    return (
        assistant,
        gr.update(choices=_run_choices(assistant), value=None),
        "Run deleted.",
        [],
        "_Select a run to see its summary._",
    )


# ---- UI -------------------------------------------------------------------


def build_execution_run_tab(assistant_state: gr.State):
    gr.Markdown("## Execution Run — run a dataset through the chat agent")

    with gr.Row():
        # left: configure + launch
        with gr.Column(scale=1, min_width=300):
            gr.Markdown("### New run")
            dataset_dropdown = gr.Dropdown(label="Dataset", choices=[], interactive=True)
            run_keyword = gr.Textbox(
                label="Keyword (optional)",
                placeholder="Short tag, e.g. baseline / smoke / new-prompt",
            )
            run_name = gr.Textbox(
                label="Run name",
                placeholder="Auto-filled from datetime + dataset + keyword — edit to override.",
            )
            run_label = gr.Textbox(
                label="Label (optional)",
                placeholder="Short tag — used as the default judge run name.",
            )
            run_desc = gr.Textbox(label="Description (optional)", lines=2)
            with gr.Accordion("Run configuration", open=True):
                with gr.Row():
                    concurrency_in = gr.Number(
                        label="Concurrency", value=1, precision=0, minimum=1, maximum=32
                    )
                    max_samples_in = gr.Number(
                        label="Max samples (0 = all)", value=0, precision=0, minimum=0
                    )
                with gr.Row():
                    shuffle_in = gr.Checkbox(label="Shuffle", value=False)
                    seed_in = gr.Number(label="Seed (optional)", value=0, precision=0)
                context_mode_in = gr.Dropdown(
                    label="Context sent to agent",
                    choices=[
                        ("Full document (same as chat)", "full_doc"),
                        ("Annotation spans only", "spans_only"),
                        ("Question only (no context)", "question_only"),
                    ],
                    value="full_doc",
                )
                extra_json_in = gr.Code(
                    label="Advanced (JSON, merges over fields)",
                    language="json",
                    value="",
                    lines=4,
                )
            start_btn = gr.Button("Start evaluation", variant="primary")
            status_md = gr.Markdown("")

            gr.Markdown("### Existing runs")
            run_dropdown = gr.Dropdown(label="Run", choices=[], interactive=True)
            with gr.Row():
                refresh_btn = gr.Button("Refresh", size="sm")
                delete_run_btn = gr.Button("Delete", variant="stop", size="sm")

        # right: results
        with gr.Column(scale=3, min_width=500):
            summary_md = gr.Markdown("_Select a run to see its summary._")
            gr.Markdown("### Predictions")
            results_tbl = gr.HTML(value="")

    # wiring
    refresh_btn.click(
        fn=on_refresh,
        inputs=[assistant_state],
        outputs=[assistant_state, dataset_dropdown, run_dropdown],
    )
    start_btn.click(
        fn=on_start_run,
        inputs=[
            dataset_dropdown,
            run_name,
            run_label,
            run_desc,
            concurrency_in,
            max_samples_in,
            shuffle_in,
            seed_in,
            context_mode_in,
            extra_json_in,
            assistant_state,
        ],
        outputs=[
            assistant_state,
            run_dropdown,
            dataset_dropdown,
            status_md,
            results_tbl,
            summary_md,
        ],
    )
    run_dropdown.change(
        fn=on_run_change,
        inputs=[run_dropdown, assistant_state],
        outputs=[results_tbl, summary_md],
    )
    dataset_dropdown.change(
        fn=lambda dsid, kw, a: gr.update(value=_auto_run_name_from_dataset(dsid, kw, a)),
        inputs=[dataset_dropdown, run_keyword, assistant_state],
        outputs=[run_name],
    )
    run_keyword.change(
        fn=lambda dsid, kw, a: gr.update(value=_auto_run_name_from_dataset(dsid, kw, a)),
        inputs=[dataset_dropdown, run_keyword, assistant_state],
        outputs=[run_name],
    )
    delete_run_btn.click(
        fn=on_delete_run,
        inputs=[run_dropdown, assistant_state],
        outputs=[assistant_state, run_dropdown, status_md, results_tbl, summary_md],
    )

    return dataset_dropdown, run_dropdown, results_tbl, summary_md


# =========================================================================
# Metrics tab
# =========================================================================


def _metric_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    return [
        (f"{m['name']} [{m['type']}·{m['aggregation']}]", m["metric_id"])
        for m in assistant.store.list_metrics()
    ]


def _metrics_table_html(assistant: ChatAssistant | None) -> str:
    if assistant is None:
        return ""
    metrics = assistant.store.list_metrics()
    if not metrics:
        return "<p><em>No metrics yet. Create one on the left.</em></p>"
    rows: list[list[object]] = []
    for m in metrics:
        meta = m.get("metadata") or {}
        mn = meta.get("min")
        mx = meta.get("max")
        if m["type"] == "bool":
            range_str = "—"
        elif mn is None and mx is None:
            range_str = "unbounded"
        else:
            range_str = f"[{'-∞' if mn is None else mn}, {'∞' if mx is None else mx}]"
        rows.append(
            [
                m["name"],
                m["type"],
                m["aggregation"],
                range_str,
                (m.get("description") or "")[:200],
                "yes" if (m.get("judge_prompt") or "").strip() else "no",
            ]
        )
    return render_table(
        ["Name", "Type", "Aggregation", "Range", "Description", "Has judge prompt"],
        rows,
        empty_msg="No metrics yet. Create one on the left.",
    )


def _parse_metadata(raw: str | None) -> tuple[dict, str | None]:
    raw = (raw or "").strip()
    if not raw:
        return {}, None
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {}, "Metadata must be a JSON object."
        return data, None
    except json.JSONDecodeError as e:
        return {}, f"Invalid metadata JSON: {e}"


def on_metrics_tab_load(assistant):
    if assistant is None:
        assistant = ChatAssistant()
    return (
        assistant,
        gr.update(choices=_metric_choices(assistant), value=None),
        _metrics_table_html(assistant),
        "",
    )


def _range_visible(mtype: str | None) -> bool:
    return mtype in ("int", "float")


def on_metric_type_change(mtype):
    show = _range_visible(mtype)
    return gr.update(visible=show), gr.update(visible=show)


def on_metric_select(metric_id, assistant):
    if assistant is None or not metric_id:
        return (
            gr.update(value=""),
            gr.update(value=""),
            gr.update(value="float"),
            gr.update(value="avg"),
            gr.update(value=""),
            gr.update(value=None, visible=True),
            gr.update(value=None, visible=True),
            gr.update(value=""),
            "",
        )
    m = assistant.store.get_metric(metric_id)
    if not m:
        return (
            gr.update(value=""),
            gr.update(value=""),
            gr.update(value="float"),
            gr.update(value="avg"),
            gr.update(value=""),
            gr.update(value=None, visible=True),
            gr.update(value=None, visible=True),
            gr.update(value=""),
            "Metric not found.",
        )
    meta = dict(m.get("metadata") or {})
    mn = meta.pop("min", None)
    mx = meta.pop("max", None)
    meta_str = json.dumps(meta, indent=2) if meta else ""
    show = _range_visible(m["type"])
    return (
        gr.update(value=m["name"]),
        gr.update(value=m.get("description") or ""),
        gr.update(value=m["type"]),
        gr.update(value=m["aggregation"]),
        gr.update(value=m.get("judge_prompt") or ""),
        gr.update(value=mn, visible=show),
        gr.update(value=mx, visible=show),
        gr.update(value=meta_str),
        f"Loaded metric `{m['name']}`.",
    )


def _coerce_range(value, mtype: str):
    if value is None or value == "":
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return int(v) if mtype == "int" else v


def on_metric_save(
    metric_id,
    name,
    description,
    mtype,
    aggregation,
    judge_prompt,
    min_value,
    max_value,
    metadata_json,
    assistant,
):
    if assistant is None:
        assistant = ChatAssistant()
    name = (name or "").strip()
    if not name:
        return assistant, gr.update(), _metrics_table_html(assistant), "Name is required."
    if mtype not in METRIC_TYPES:
        return assistant, gr.update(), _metrics_table_html(assistant), "Invalid type."
    if aggregation not in AGGREGATIONS:
        return assistant, gr.update(), _metrics_table_html(assistant), "Invalid aggregation."
    meta, err = _parse_metadata(metadata_json)
    if err:
        return assistant, gr.update(), _metrics_table_html(assistant), err
    if _range_visible(mtype):
        mn = _coerce_range(min_value, mtype)
        mx = _coerce_range(max_value, mtype)
        if mn is not None and mx is not None and mn > mx:
            return (
                assistant,
                gr.update(),
                _metrics_table_html(assistant),
                "Min cannot be greater than max.",
            )
        if mn is not None:
            meta["min"] = mn
        else:
            meta.pop("min", None)
        if mx is not None:
            meta["max"] = mx
        else:
            meta.pop("max", None)
    else:
        meta.pop("min", None)
        meta.pop("max", None)
    jp = (judge_prompt or "").strip() or None
    desc = (description or "").strip()
    if metric_id:
        assistant.store.update_metric(
            metric_id,
            name=name,
            description=desc,
            type=mtype,
            aggregation=aggregation,
            judge_prompt=jp,
            metadata=meta,
        )
        msg = f"Updated metric `{name}`."
        new_id = metric_id
    else:
        new_id = assistant.store.create_metric(
            name=name,
            description=desc,
            type=mtype,
            aggregation=aggregation,
            judge_prompt=jp,
            metadata=meta,
        )
        msg = f"Created metric `{name}`."
    return (
        assistant,
        gr.update(choices=_metric_choices(assistant), value=new_id),
        _metrics_table_html(assistant),
        msg,
    )


def on_metric_delete(metric_id, assistant):
    if assistant is None or not metric_id:
        return assistant, gr.update(), _metrics_table_html(assistant), "No metric selected."
    assistant.store.delete_metric(metric_id)
    return (
        assistant,
        gr.update(choices=_metric_choices(assistant), value=None),
        _metrics_table_html(assistant),
        "Metric deleted.",
    )


def on_metric_clear():
    return (
        gr.update(value=None),
        gr.update(value=""),
        gr.update(value=""),
        gr.update(value="float"),
        gr.update(value="avg"),
        gr.update(value=""),
        gr.update(value=None, visible=True),
        gr.update(value=None, visible=True),
        gr.update(value=""),
        "Form cleared.",
    )


def build_metrics_tab(assistant_state: gr.State):
    gr.Markdown("## Metrics — define scoring rubrics used by judge runs")

    with gr.Row():
        with gr.Column(scale=1, min_width=320):
            gr.Markdown("### Existing metrics")
            metric_dd = gr.Dropdown(label="Metric", choices=[], interactive=True)
            with gr.Row():
                new_btn = gr.Button("New", size="sm")
                delete_btn = gr.Button("Delete", variant="stop", size="sm")

            gr.Markdown("### Edit / Create")
            name_in = gr.Textbox(label="Name", placeholder="e.g. Correctness")
            desc_in = gr.Textbox(label="Description", lines=2)
            with gr.Row():
                type_in = gr.Dropdown(label="Type", choices=METRIC_TYPES, value="float")
                agg_in = gr.Dropdown(label="Aggregation", choices=AGGREGATIONS, value="avg")
            judge_prompt_in = gr.Textbox(
                label="Judge prompt (optional)",
                lines=4,
                placeholder="Guidance shown to the LLM judge for this metric.",
            )
            with gr.Row():
                min_in = gr.Number(
                    label="Min (optional, int/float only)",
                    value=None,
                    visible=True,
                )
                max_in = gr.Number(
                    label="Max (optional, int/float only)",
                    value=None,
                    visible=True,
                )
            metadata_in = gr.Code(
                label="Metadata (JSON, optional — extra fields beyond min/max)",
                language="json",
                value="",
                lines=4,
            )
            save_btn = gr.Button("Save", variant="primary")
            status_md = gr.Markdown("")

        with gr.Column(scale=2, min_width=500):
            gr.Markdown("### All metrics")
            table_html = gr.HTML(value="")

    metric_dd.change(
        fn=on_metric_select,
        inputs=[metric_dd, assistant_state],
        outputs=[
            name_in,
            desc_in,
            type_in,
            agg_in,
            judge_prompt_in,
            min_in,
            max_in,
            metadata_in,
            status_md,
        ],
    )
    type_in.change(
        fn=on_metric_type_change,
        inputs=[type_in],
        outputs=[min_in, max_in],
    )
    save_btn.click(
        fn=on_metric_save,
        inputs=[
            metric_dd,
            name_in,
            desc_in,
            type_in,
            agg_in,
            judge_prompt_in,
            min_in,
            max_in,
            metadata_in,
            assistant_state,
        ],
        outputs=[assistant_state, metric_dd, table_html, status_md],
    )
    delete_btn.click(
        fn=on_metric_delete,
        inputs=[metric_dd, assistant_state],
        outputs=[assistant_state, metric_dd, table_html, status_md],
    )
    new_btn.click(
        fn=on_metric_clear,
        inputs=[],
        outputs=[
            metric_dd,
            name_in,
            desc_in,
            type_in,
            agg_in,
            judge_prompt_in,
            min_in,
            max_in,
            metadata_in,
            status_md,
        ],
    )

    return metric_dd, table_html, status_md


# =========================================================================
# Judge Run tab
# =========================================================================


def _eval_run_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    out = []
    for r in assistant.store.list_evaluation_runs():
        tag = f" [{r['label']}]" if r.get("label") else ""
        label = f"{r['name']}{tag} · {r.get('dataset_name', '?')} · preds={r['prediction_count']}"
        out.append((label, r["run_id"]))
    return out


def _judge_run_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    if assistant is None:
        return []
    out = []
    for j in assistant.store.list_judge_runs():
        label = (
            f"{j['name']} · {j.get('evaluation_run_name', '?')} · "
            f"{j['judge_type']} · {j['status']}"
        )
        out.append((label, j["judge_run_id"]))
    return out


def _metric_multi_choices(assistant: ChatAssistant | None) -> list[tuple[str, str]]:
    return _metric_choices(assistant)


def _aggregates_html(assistant: ChatAssistant | None, judge_run_id: str | None) -> str:
    if assistant is None or not judge_run_id:
        return ""
    aggs = assistant.store.aggregate_judge_run(judge_run_id)
    if not aggs:
        return "<p><em>No aggregates yet — score predictions to populate.</em></p>"
    total_ms = aggs[0].get("total_execution_time_ms")
    avg_ms = aggs[0].get("avg_execution_time_ms")
    timing_line = ""
    if total_ms:
        timing_line = (
            f"<p style='opacity:0.8;margin:4px 0'><b>Execution time:</b> "
            f"total {html.escape(fmt_duration_ms(total_ms))} · "
            f"avg {html.escape(fmt_duration_ms(avg_ms))}</p>"
        )
    rows: list[list[object]] = [
        [
            r["metric_name"],
            r["aggregation"],
            fmt_score(r["score"]),
            r["judged_count"],
            r["missing_count"],
            r["total_predictions"],
        ]
        for r in aggs
    ]
    table = render_table(
        ["Metric", "Agg", "Score", "Judged", "Missing", "Total"],
        rows,
        empty_msg="No aggregates yet — score predictions to populate.",
    )
    return timing_line + table


def _prediction_view_html(prediction: dict | None) -> str:
    if not prediction:
        return "<p><em>No prediction loaded.</em></p>"
    q = html.escape(prediction.get("question") or "")
    expected = html.escape(prediction.get("expected_answer") or "")
    answer = html.escape(prediction.get("agent_answer") or "")
    thoughts = html.escape(prediction.get("agent_thoughts") or "")
    context = html.escape(prediction.get("context_used") or "")
    doc_ref = html.escape(prediction.get("doc_name") or prediction.get("document_reference") or "—")
    spans = prediction.get("spans") or []
    if spans:
        span_lines = []
        for s in spans:
            kind = s.get("kind", "text")
            page = s.get("page_num", "?")
            text = html.escape((s.get("quoted_text") or "").strip())
            if kind == "page" and not text:
                span_lines.append(f"<li>[Page {page}] (full page)</li>")
            elif text:
                span_lines.append(f"<li>[Page {page}] {text}</li>")
        spans_block = "<ul style='margin:4px 0 0 18px'>" + "".join(span_lines) + "</ul>"
    else:
        spans_block = "<em>(no evidence spans)</em>"

    pre = "style='white-space:pre-wrap;background:#1e1e1e;color:#ddd;padding:8px;border-radius:4px;max-height:200px;overflow:auto'"
    details = "style='margin-top:8px'"
    return (
        f"<div style='font-size:0.92em'>"
        f"<div><strong>Document:</strong> {doc_ref}</div>"
        f"<h4 style='margin:8px 0 4px 0'>Question</h4><div {pre}>{q}</div>"
        f"<h4 style='margin:8px 0 4px 0'>Expected answer</h4><div {pre}>{expected}</div>"
        f"<h4 style='margin:8px 0 4px 0'>Agent answer</h4><div {pre}>{answer}</div>"
        f"<details {details}><summary><strong>Agent think trace</strong></summary>"
        f"<div {pre}>{thoughts or '(none)'}</div></details>"
        f"<details {details}><summary><strong>Agent context / retrieved text</strong></summary>"
        f"<div {pre}>{context or '(none)'}</div></details>"
        f"<h4 style='margin:8px 0 4px 0'>Evidence spans</h4>{spans_block}"
        f"</div>"
    )


def _get_predictions_for_run(assistant, judge_run_id):
    jr = assistant.store.get_judge_run(judge_run_id)
    if not jr:
        return None, []
    preds = assistant.store.list_predictions(jr["evaluation_run_id"])
    preds = [p for p in preds if p["status"] == "success"]
    return jr, preds


def on_judge_tab_load(assistant):
    if assistant is None:
        assistant = ChatAssistant()
    return (
        assistant,
        gr.update(choices=_eval_run_choices(assistant), value=None),
        gr.update(choices=_metric_multi_choices(assistant), value=[]),
        gr.update(choices=_judge_run_choices(assistant), value=None),
        "",
    )


def _judge_default_cfg(assistant: ChatAssistant | None) -> dict:
    """Return the default {model, backend} for the judge agent."""
    if assistant is None:
        return {"model": "", "backend": ""}
    cfg = assistant.config
    agent_cfg = (
        cfg.agents.get("judge")
        or cfg.agents.get("reviewer")
        or next(iter(cfg.agents.values()))
    )
    return {"model": agent_cfg.model, "backend": agent_cfg.backend}


def on_create_judge_run(
    eval_run_id, metric_ids, judge_type, name, model, backend, concurrency, assistant
):
    if assistant is None:
        assistant = ChatAssistant()
    if not eval_run_id:
        return assistant, gr.update(), "Select an evaluation run."
    if not metric_ids:
        return assistant, gr.update(), "Select at least one metric."
    name = (name or "").strip() or "Judge run"

    defaults = _judge_default_cfg(assistant)
    model = (model or "").strip() or defaults["model"]
    backend = (backend or "").strip() or defaults["backend"]
    try:
        concurrency_int = max(1, int(concurrency or 1))
    except (TypeError, ValueError):
        concurrency_int = 1

    snapshot = {
        "model": model,
        "backend": backend,
        "concurrency": concurrency_int,
    }
    jr_id = assistant.store.create_judge_run(
        evaluation_run_id=eval_run_id,
        name=name,
        judge_type=judge_type or "manual",
        metric_ids=list(metric_ids),
        judge_config_snapshot=snapshot,
    )
    return (
        assistant,
        gr.update(choices=_judge_run_choices(assistant), value=jr_id),
        f"Created judge run `{name}` (model={model}, backend={backend}, concurrency={concurrency_int}).",
    )


def _build_score_state(assistant, judge_run_id, idx):
    """Return the shared state dict consumed by the @gr.render scoring view."""
    empty = {
        "judge_run_id": None,
        "prediction_id": None,
        "idx": 0,
        "total": 0,
        "rows": [],
    }
    if assistant is None or not judge_run_id:
        return empty
    jr, preds = _get_predictions_for_run(assistant, judge_run_id)
    if not jr or not preds:
        return {**empty, "judge_run_id": judge_run_id}
    i = max(0, min(len(preds) - 1, int(idx or 0)))
    pred_summary = preds[i]
    pred = assistant.store.get_prediction(pred_summary["prediction_id"]) or pred_summary
    existing = assistant.store.get_results_for_prediction(judge_run_id, pred["prediction_id"])
    rows = []
    for mid in jr["metric_ids"]:
        metric = assistant.store.get_metric(mid)
        if not metric:
            continue
        existing_r = existing.get(mid)
        meta = metric.get("metadata") or {}
        score_val = (
            ""
            if existing_r is None
            else _format_score_for_type(existing_r["score"], metric["type"])
        )
        comment = (existing_r.get("comment") if existing_r else "") or ""
        rows.append(
            {
                "metric_id": mid,
                "name": metric["name"],
                "type": metric["type"],
                "min": meta.get("min"),
                "max": meta.get("max"),
                "score": score_val,
                "comment": comment,
            }
        )
    return {
        "judge_run_id": judge_run_id,
        "prediction_id": pred["prediction_id"],
        "idx": i,
        "total": len(preds),
        "rows": rows,
        "pred_html": _prediction_view_html(pred),
        "nav": f"Prediction {i + 1} / {len(preds)}",
    }


def on_judge_run_select(judge_run_id, assistant):
    state = _build_score_state(assistant, judge_run_id, 0)
    pred_html = state.get("pred_html") or "<p><em>No predictions to judge.</em></p>"
    nav = state.get("nav") or ""
    return (
        state,
        state["idx"],
        pred_html,
        nav,
        _aggregates_html(assistant, judge_run_id) if judge_run_id else "_Select a judge run._",
    )


def _format_score_for_type(score, mtype):
    if score is None:
        return ""
    if mtype == "bool":
        return "1" if float(score) >= 0.5 else "0"
    if mtype == "int":
        return str(int(round(float(score))))
    return f"{float(score):.3f}"


def on_nav_prediction(direction, idx, judge_run_id, assistant):
    new_idx = int(idx or 0) + int(direction)
    state = _build_score_state(assistant, judge_run_id, new_idx)
    pred_html = state.get("pred_html") or "<p><em>No predictions.</em></p>"
    nav = state.get("nav") or ""
    return state, state["idx"], pred_html, nav


def _parse_manual_score(raw, mtype):
    raw = str(raw).strip()
    if raw == "":
        return None, None
    try:
        v = float(raw)
    except ValueError:
        return None, f"Invalid number '{raw}'."
    if mtype == "bool":
        return (1.0 if v >= 0.5 else 0.0), None
    if mtype == "int":
        return float(int(round(v))), None
    return v, None


def _save_manual_scores_from_state(state, score_values, comment_values, assistant):
    """Save the score/comment values for the prediction described by `state`."""
    if assistant is None or not state or not state.get("judge_run_id"):
        return "No judge run selected."
    judge_run_id = state["judge_run_id"]
    jr = assistant.store.get_judge_run(judge_run_id)
    if not jr:
        return "Judge run not found."
    pred = assistant.store.get_prediction(state["prediction_id"])
    if not pred:
        return "Prediction not found."
    rows = state.get("rows") or []
    saved = 0
    errors: list[str] = []
    for row, score_raw, comment in zip(rows, score_values, comment_values):
        score, err = _parse_manual_score(score_raw, row["type"])
        if err:
            errors.append(f"{row['name']}: {err}")
            continue
        if score is None:
            continue
        # Clamp to range if defined
        if row["type"] in ("int", "float"):
            mn, mx = row.get("min"), row.get("max")
            if mn is not None and score < float(mn):
                errors.append(f"{row['name']}: {score} below min {mn}.")
                continue
            if mx is not None and score > float(mx):
                errors.append(f"{row['name']}: {score} above max {mx}.")
                continue
        assistant.store.upsert_evaluation_result(
            judge_run_id=judge_run_id,
            evaluation_run_id=jr["evaluation_run_id"],
            prediction_id=pred["prediction_id"],
            annotation_id=pred["annotation_id"],
            metric_id=row["metric_id"],
            score=score,
            judge_type="manual",
            comment=(str(comment).strip() or None) if comment is not None else None,
            judge_reasoning=None,
        )
        saved += 1
    msg = f"Saved {saved} score(s)."
    if errors:
        msg += " Errors: " + "; ".join(errors)
    return msg


async def on_run_llm_judge(judge_run_id, assistant):
    if assistant is None:
        assistant = ChatAssistant()
    if not judge_run_id:
        return assistant, "Select a judge run.", gr.update(), gr.update()
    snap = (assistant.store.get_judge_run(judge_run_id) or {}).get(
        "judge_config_snapshot"
    ) or {}
    try:
        summary = await run_llm_judge(
            assistant=assistant,
            judge_run_id=judge_run_id,
            model_override=snap.get("model") or None,
            backend_override=snap.get("backend") or None,
            concurrency=snap.get("concurrency"),
        )
        msg = (
            f"LLM judge {summary['status']} — success: {summary.get('success', 0)} · "
            f"failed: {summary.get('failed', 0)} / {summary.get('total', 0)}"
        )
    except Exception as e:
        logger.exception("LLM judge failed run=%s", judge_run_id)
        msg = f"LLM judge failed: {e}"
    return (
        assistant,
        msg,
        _aggregates_html(assistant, judge_run_id),
        gr.update(choices=_judge_run_choices(assistant), value=judge_run_id),
    )


def on_export_judge_jsonl(judge_run_id, assistant):
    """Export one JSONL line per prediction with its per-metric judge results."""
    if assistant is None or not judge_run_id:
        return None, "Select a judge run first."
    jr = assistant.store.get_judge_run(judge_run_id)
    if not jr:
        return None, "Judge run not found."

    eval_run_id = jr["evaluation_run_id"]
    preds = assistant.store.list_predictions(eval_run_id)
    results = assistant.store.list_evaluation_results(judge_run_id)

    # Group results by prediction_id
    by_pred: dict[str, list[dict]] = {}
    for r in results:
        by_pred.setdefault(r["prediction_id"], []).append(
            {
                "metric_id": r["metric_id"],
                "metric_name": r.get("metric_name"),
                "metric_type": r.get("metric_type"),
                "score": r["score"],
                "judge_type": r["judge_type"],
                "comment": r.get("comment"),
                "judge_reasoning": r.get("judge_reasoning"),
            }
        )

    safe_jr_name = _slugify(jr.get("name") or "judge")
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".jsonl",
        prefix=f"judge_{safe_jr_name}_",
        delete=False,
        encoding="utf-8",
    )
    written = 0
    for p in preds:
        full = assistant.store.get_prediction(p["prediction_id"]) or p
        line = {
            "prediction_id": full.get("prediction_id"),
            "annotation_id": full.get("annotation_id"),
            "doc_name": full.get("doc_name"),
            "document_reference": full.get("document_reference"),
            "question": full.get("question"),
            "expected_answer": full.get("expected_answer"),
            "agent_answer": full.get("agent_answer"),
            "agent_thoughts": full.get("agent_thoughts"),
            "context_used": full.get("context_used"),
            "spans": full.get("spans") or [],
            "status": full.get("status"),
            "error_message": full.get("error_message"),
            "metrics": by_pred.get(full.get("prediction_id"), []),
        }
        tmp.write(json.dumps(line, ensure_ascii=False) + "\n")
        written += 1
    tmp.close()
    logger.info(
        "exported judge_run=%s file=%s predictions=%d results=%d",
        judge_run_id,
        tmp.name,
        written,
        len(results),
    )
    return tmp.name, f"Exported {written} prediction(s) to JSONL."


def on_delete_judge_run(judge_run_id, assistant):
    if assistant is None or not judge_run_id:
        return assistant, gr.update(), "No judge run selected.", "", ""
    assistant.store.delete_judge_run(judge_run_id)
    return (
        assistant,
        gr.update(choices=_judge_run_choices(assistant), value=None),
        "Judge run deleted.",
        "",
        "",
    )


def on_judge_refresh(assistant):
    if assistant is None:
        assistant = ChatAssistant()
    return (
        assistant,
        gr.update(choices=_eval_run_choices(assistant)),
        gr.update(choices=_metric_multi_choices(assistant)),
        gr.update(choices=_judge_run_choices(assistant)),
    )


def build_judge_run_tab(assistant_state: gr.State):
    gr.Markdown("## Judge Run — score predictions manually or with an LLM judge")

    with gr.Row():
        # Left: create / select judge run
        with gr.Column(scale=1, min_width=320):
            gr.Markdown("### New judge run")
            eval_run_dd = gr.Dropdown(label="Evaluation run", choices=[], interactive=True)
            with gr.Row():
                metrics_multi = gr.Dropdown(
                    label="Metrics", choices=[], multiselect=True, interactive=True, scale=3
                )
                gr.Button("Manage metrics →", link="../_config", size="sm", scale=1)
            judge_type_rd = gr.Radio(label="Judge type", choices=["manual", "llm"], value="manual")
            jr_keyword = gr.Textbox(
                label="Keyword (optional)",
                placeholder="Short tag, e.g. manual / llm-strict / qwen-judge",
            )
            jr_name = gr.Textbox(
                label="Judge run name",
                placeholder="Auto-filled from datetime + dataset + keyword — edit to override.",
            )

            with gr.Accordion("Judge config (LLM judge only)", open=False):
                judge_model_tb = gr.Textbox(
                    label="Model",
                    placeholder="leave empty to use the `judge` agent default",
                )
                judge_backend_dd = gr.Dropdown(
                    label="Backend",
                    choices=["", "local", "openrouter"],
                    value="",
                    allow_custom_value=True,
                )
                judge_concurrency_n = gr.Number(
                    label="Concurrency",
                    value=int(os.getenv("JUDGE_CONCURRENCY", "1") or "1"),
                    precision=0,
                    minimum=1,
                    info="Parallel (prediction × metric) judgments. Keep at 1 for local Ollama.",
                )

            create_jr_btn = gr.Button("Create judge run", variant="primary")

            gr.Markdown("### Existing judge runs")
            judge_run_dd = gr.Dropdown(label="Judge run", choices=[], interactive=True)
            with gr.Row():
                refresh_btn = gr.Button("Refresh", size="sm")
                run_llm_btn = gr.Button("Run LLM judge", size="sm")
                delete_jr_btn = gr.Button("Delete", variant="stop", size="sm")
            jr_status_md = gr.Markdown("")

            export_jsonl_btn = gr.Button("Export judge logs (JSONL)", size="sm")
            export_jsonl_file = gr.File(label="Download", interactive=False)

            gr.Markdown("### Aggregates")
            aggregates_html = gr.HTML(value="")

        # Right: prediction viewer + scoring
        with gr.Column(scale=2, min_width=500):
            gr.Markdown("### Prediction")
            nav_md = gr.Markdown("_Select a judge run to start._")
            with gr.Row():
                prev_btn = gr.Button("◀ Prev", size="sm")
                next_btn = gr.Button("Next ▶", size="sm")
            pred_idx = gr.State(value=0)
            score_state = gr.State(
                value={"judge_run_id": None, "prediction_id": None, "idx": 0, "rows": []}
            )
            pred_html = gr.HTML(value="")
            gr.Markdown("### Scores")

            @gr.render(inputs=[score_state])
            def render_scores(state):
                if not state or not state.get("rows"):
                    if state and state.get("judge_run_id"):
                        gr.Markdown(
                            "_No metrics on this judge run, or no successful predictions to score._"
                        )
                    else:
                        gr.Markdown("_Select a judge run to start scoring._")
                    return
                score_inputs = []
                comment_inputs = []
                for row in state["rows"]:
                    range_hint = ""
                    if row["type"] in ("int", "float"):
                        mn, mx = row.get("min"), row.get("max")
                        if mn is not None or mx is not None:
                            range_hint = (
                                f" (range: {'-∞' if mn is None else mn} – "
                                f"{'∞' if mx is None else mx})"
                            )
                    with gr.Row():
                        with gr.Column(min_width=180, scale=0):
                            gr.Markdown(
                                f"**{row['name']}** _({row['type']})_{range_hint}"
                            )
                        s = gr.Textbox(
                            value=row["score"],
                            label="Score",
                            scale=1,
                            interactive=True,
                        )
                        c = gr.Textbox(
                            value=row["comment"],
                            label="Comment",
                            scale=2,
                            interactive=True,
                        )
                        score_inputs.append(s)
                        comment_inputs.append(c)

                row_save_btn = gr.Button("Save scores", variant="primary", size="sm")

                def _do_save(state_in, assistant_in, *vals):
                    n = len(state_in.get("rows") or [])
                    scores = list(vals[:n])
                    comments = list(vals[n : 2 * n])
                    msg = _save_manual_scores_from_state(state_in, scores, comments, assistant_in)
                    aggs = _aggregates_html(assistant_in, state_in.get("judge_run_id"))
                    return msg, aggs

                row_save_btn.click(
                    fn=_do_save,
                    inputs=[score_state, assistant_state, *score_inputs, *comment_inputs],
                    outputs=[jr_status_md, aggregates_html],
                )

    create_jr_btn.click(
        fn=on_create_judge_run,
        inputs=[
            eval_run_dd,
            metrics_multi,
            judge_type_rd,
            jr_name,
            judge_model_tb,
            judge_backend_dd,
            judge_concurrency_n,
            assistant_state,
        ],
        outputs=[assistant_state, judge_run_dd, jr_status_md],
    )
    eval_run_dd.change(
        fn=lambda erid, kw, a: gr.update(value=_auto_run_name_from_eval_run(erid, kw, a)),
        inputs=[eval_run_dd, jr_keyword, assistant_state],
        outputs=[jr_name],
    )
    jr_keyword.change(
        fn=lambda erid, kw, a: gr.update(value=_auto_run_name_from_eval_run(erid, kw, a)),
        inputs=[eval_run_dd, jr_keyword, assistant_state],
        outputs=[jr_name],
    )
    refresh_btn.click(
        fn=on_judge_refresh,
        inputs=[assistant_state],
        outputs=[assistant_state, eval_run_dd, metrics_multi, judge_run_dd],
    )
    judge_run_dd.change(
        fn=on_judge_run_select,
        inputs=[judge_run_dd, assistant_state],
        outputs=[score_state, pred_idx, pred_html, nav_md, aggregates_html],
    )
    prev_btn.click(
        fn=lambda idx, jr, a: on_nav_prediction(-1, idx, jr, a),
        inputs=[pred_idx, judge_run_dd, assistant_state],
        outputs=[score_state, pred_idx, pred_html, nav_md],
    )
    next_btn.click(
        fn=lambda idx, jr, a: on_nav_prediction(1, idx, jr, a),
        inputs=[pred_idx, judge_run_dd, assistant_state],
        outputs=[score_state, pred_idx, pred_html, nav_md],
    )
    run_llm_btn.click(
        fn=on_run_llm_judge,
        inputs=[judge_run_dd, assistant_state],
        outputs=[assistant_state, jr_status_md, aggregates_html, judge_run_dd],
    )
    delete_jr_btn.click(
        fn=on_delete_judge_run,
        inputs=[judge_run_dd, assistant_state],
        outputs=[assistant_state, judge_run_dd, jr_status_md, pred_html, aggregates_html],
    )
    export_jsonl_btn.click(
        fn=on_export_judge_jsonl,
        inputs=[judge_run_dd, assistant_state],
        outputs=[export_jsonl_file, jr_status_md],
    )

    return eval_run_dd, metrics_multi, judge_run_dd, aggregates_html
