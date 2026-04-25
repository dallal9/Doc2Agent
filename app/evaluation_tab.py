"""Evaluation page — Execution Run tab (Milestone 3).

Runs a selected dataset against the existing chat agent and stores one
`EvaluationPrediction` per annotation. Reuses the existing Chat pipeline.
"""

from __future__ import annotations

import html
import json

import gradio as gr

from src.chat import ChatAssistant
from src.evaluation import run_evaluation, run_llm_judge
from src.evaluation.runner import normalize_config
from src.logging import setup_logging

METRIC_TYPES = ["bool", "int", "float"]
AGGREGATIONS = ["avg", "sum", "min", "max"]

logger = setup_logging("evaluation_tab")


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
    """Render predictions as an HTML table. Avoids a gr.Dataframe recursion bug."""
    if assistant is None or not run_id:
        return ""
    preds = assistant.store.list_predictions(run_id)
    if not preds:
        return "<p><em>No predictions yet.</em></p>"
    headers = ["Question", "Expected", "Agent answer", "Document", "Status", "Error"]
    out = [
        "<table style='width:100%;border-collapse:collapse;font-size:0.9em'>",
        "<thead><tr>"
        + "".join(
            f"<th style='text-align:left;padding:6px;border-bottom:1px solid #888'>{h}</th>"
            for h in headers
        )
        + "</tr></thead>",
        "<tbody>",
    ]
    status_colors = {"success": "#1a7f37", "failed": "#b42318", "skipped": "#8a6d00"}
    for p in preds:
        cells = [
            (p.get("question") or "")[:400],
            (p.get("expected_answer") or "")[:400],
            (p.get("agent_answer") or "")[:400],
            p.get("doc_name") or p.get("document_reference") or "—",
            p["status"],
            (p.get("error_message") or "")[:200],
        ]
        tds = []
        for i, c in enumerate(cells):
            style = "padding:6px;border-bottom:1px solid #2a2a2a;vertical-align:top"
            if i == 4:
                style += f";color:{status_colors.get(c, '#888')};font-weight:600"
            tds.append(f"<td style='{style}'>{html.escape(str(c))}</td>")
        out.append("<tr>" + "".join(tds) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


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
    lines = [
        f"### {run['name']}",
        run.get("description") or "",
        f"**Status:** {run['status']} · **Dataset:** `{run['dataset_id']}`",
        f"**Predictions:** {len(preds)} — success: {ok} · failed: {failed} · skipped: {skipped}",
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
    config, err = _resolve_config(
        concurrency, max_samples, shuffle, seed, context_mode, extra_json
    )
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
    desc = (run_desc or "").strip() or None

    run_id = assistant.store.create_evaluation_run(
        dataset_id=dataset_id, name=name, description=desc, agent_config=config
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
            run_name = gr.Textbox(label="Run name", placeholder="e.g. baseline-2026-04-24")
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
    out = [
        "<table style='width:100%;border-collapse:collapse;font-size:0.9em'>",
        "<thead><tr>"
        + "".join(
            f"<th style='text-align:left;padding:6px;border-bottom:1px solid #888'>{h}</th>"
            for h in ["Name", "Type", "Aggregation", "Description", "Has judge prompt"]
        )
        + "</tr></thead><tbody>",
    ]
    for m in metrics:
        cells = [
            m["name"],
            m["type"],
            m["aggregation"],
            (m.get("description") or "")[:200],
            "yes" if (m.get("judge_prompt") or "").strip() else "no",
        ]
        out.append(
            "<tr>"
            + "".join(
                f"<td style='padding:6px;border-bottom:1px solid #2a2a2a;vertical-align:top'>{html.escape(str(c))}</td>"
                for c in cells
            )
            + "</tr>"
        )
    out.append("</tbody></table>")
    return "".join(out)


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


def on_metric_select(metric_id, assistant):
    if assistant is None or not metric_id:
        return (
            gr.update(value=""),
            gr.update(value=""),
            gr.update(value="float"),
            gr.update(value="avg"),
            gr.update(value=""),
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
            gr.update(value=""),
            "Metric not found.",
        )
    meta_str = json.dumps(m.get("metadata") or {}, indent=2) if m.get("metadata") else ""
    return (
        gr.update(value=m["name"]),
        gr.update(value=m.get("description") or ""),
        gr.update(value=m["type"]),
        gr.update(value=m["aggregation"]),
        gr.update(value=m.get("judge_prompt") or ""),
        gr.update(value=meta_str),
        f"Loaded metric `{m['name']}`.",
    )


def on_metric_save(
    metric_id, name, description, mtype, aggregation, judge_prompt, metadata_json, assistant
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
                type_in = gr.Dropdown(
                    label="Type", choices=METRIC_TYPES, value="float"
                )
                agg_in = gr.Dropdown(
                    label="Aggregation", choices=AGGREGATIONS, value="avg"
                )
            judge_prompt_in = gr.Textbox(
                label="Judge prompt (optional)",
                lines=4,
                placeholder="Guidance shown to the LLM judge for this metric.",
            )
            metadata_in = gr.Code(
                label="Metadata (JSON, optional — e.g. min/max/labels)",
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
        outputs=[name_in, desc_in, type_in, agg_in, judge_prompt_in, metadata_in, status_md],
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
        label = (
            f"{r['name']} · {r.get('dataset_name', '?')} · "
            f"preds={r['prediction_count']}"
        )
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
    rows = assistant.store.aggregate_judge_run(judge_run_id)
    if not rows:
        return "<p><em>No aggregates yet — score predictions to populate.</em></p>"
    out = [
        "<table style='width:100%;border-collapse:collapse;font-size:0.9em'>",
        "<thead><tr>"
        + "".join(
            f"<th style='text-align:left;padding:6px;border-bottom:1px solid #888'>{h}</th>"
            for h in ["Metric", "Agg", "Score", "Judged", "Missing", "Total"]
        )
        + "</tr></thead><tbody>",
    ]
    for r in rows:
        score = r["score"]
        score_str = "—" if score is None else (f"{score:.3f}" if isinstance(score, float) else str(score))
        cells = [
            r["metric_name"],
            r["aggregation"],
            score_str,
            r["judged_count"],
            r["missing_count"],
            r["total_predictions"],
        ]
        out.append(
            "<tr>"
            + "".join(
                f"<td style='padding:6px;border-bottom:1px solid #2a2a2a'>{html.escape(str(c))}</td>"
                for c in cells
            )
            + "</tr>"
        )
    out.append("</tbody></table>")
    return "".join(out)


def _prediction_view_html(prediction: dict | None) -> str:
    if not prediction:
        return "<p><em>No prediction loaded.</em></p>"
    q = html.escape(prediction.get("question") or "")
    expected = html.escape(prediction.get("expected_answer") or "")
    answer = html.escape(prediction.get("agent_answer") or "")
    thoughts = html.escape(prediction.get("agent_thoughts") or "")
    context = html.escape(prediction.get("context_used") or "")
    doc_ref = html.escape(
        prediction.get("doc_name") or prediction.get("document_reference") or "—"
    )
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
    details = (
        "style='margin-top:8px'"
    )
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


def on_create_judge_run(eval_run_id, metric_ids, judge_type, name, assistant):
    if assistant is None:
        assistant = ChatAssistant()
    if not eval_run_id:
        return assistant, gr.update(), "Select an evaluation run."
    if not metric_ids:
        return assistant, gr.update(), "Select at least one metric."
    name = (name or "").strip() or "Judge run"
    jr_id = assistant.store.create_judge_run(
        evaluation_run_id=eval_run_id,
        name=name,
        judge_type=judge_type or "manual",
        metric_ids=list(metric_ids),
    )
    return (
        assistant,
        gr.update(choices=_judge_run_choices(assistant), value=jr_id),
        f"Created judge run `{name}`.",
    )


def on_judge_run_select(judge_run_id, assistant):
    """When a judge run is selected, reset prediction index to 0 and render state."""
    if assistant is None or not judge_run_id:
        return (
            0,
            "",
            "",
            gr.update(value=[], headers=["Metric", "Type", "Score", "Comment"]),
            "_Select a judge run._",
        )
    jr, preds = _get_predictions_for_run(assistant, judge_run_id)
    if not jr or not preds:
        return (
            0,
            "<p><em>No predictions to judge.</em></p>",
            "",
            gr.update(value=[], headers=["Metric", "Type", "Score", "Comment"]),
            _aggregates_html(assistant, judge_run_id),
        )
    idx = 0
    pred = assistant.store.get_prediction(preds[idx]["prediction_id"]) or preds[idx]
    scores_rows = _scores_rows_for_pred(assistant, judge_run_id, pred, jr["metric_ids"])
    nav = f"Prediction {idx + 1} / {len(preds)}"
    return (
        idx,
        _prediction_view_html(pred),
        nav,
        gr.update(value=scores_rows, headers=["Metric", "Type", "Score", "Comment"]),
        _aggregates_html(assistant, judge_run_id),
    )


def _scores_rows_for_pred(assistant, judge_run_id, pred, metric_ids):
    existing = assistant.store.get_results_for_prediction(
        judge_run_id, pred["prediction_id"]
    )
    rows = []
    for mid in metric_ids:
        metric = assistant.store.get_metric(mid)
        if not metric:
            continue
        existing_r = existing.get(mid)
        score_val = "" if existing_r is None else _format_score_for_type(
            existing_r["score"], metric["type"]
        )
        comment = (existing_r.get("comment") if existing_r else "") or ""
        rows.append([metric["name"], metric["type"], score_val, comment])
    return rows


def _format_score_for_type(score, mtype):
    if score is None:
        return ""
    if mtype == "bool":
        return "1" if float(score) >= 0.5 else "0"
    if mtype == "int":
        return str(int(round(float(score))))
    return f"{float(score):.3f}"


def on_nav_prediction(direction, idx, judge_run_id, assistant):
    if assistant is None or not judge_run_id:
        return idx, "", "", gr.update()
    jr, preds = _get_predictions_for_run(assistant, judge_run_id)
    if not jr or not preds:
        return idx, "<p><em>No predictions.</em></p>", "", gr.update()
    new_idx = max(0, min(len(preds) - 1, int(idx or 0) + int(direction)))
    pred = assistant.store.get_prediction(preds[new_idx]["prediction_id"]) or preds[new_idx]
    nav = f"Prediction {new_idx + 1} / {len(preds)}"
    rows = _scores_rows_for_pred(assistant, judge_run_id, pred, jr["metric_ids"])
    return (
        new_idx,
        _prediction_view_html(pred),
        nav,
        gr.update(value=rows, headers=["Metric", "Type", "Score", "Comment"]),
    )


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


def on_save_manual_scores(idx, judge_run_id, scores_rows, assistant):
    if assistant is None or not judge_run_id:
        return "No judge run selected.", gr.update(), gr.update()
    jr, preds = _get_predictions_for_run(assistant, judge_run_id)
    if not jr or not preds:
        return "No predictions.", gr.update(), gr.update()
    i = max(0, min(len(preds) - 1, int(idx or 0)))
    pred = preds[i]
    # scores_rows is a list of [name, type, score_str, comment]
    rows_iter = scores_rows if isinstance(scores_rows, list) else []
    metric_ids = jr["metric_ids"]
    # rebuild name→metric_id in the same order used for rendering
    metrics_in_order: list[dict] = []
    for mid in metric_ids:
        m = assistant.store.get_metric(mid)
        if m:
            metrics_in_order.append(m)
    saved = 0
    errors: list[str] = []
    for row, metric in zip(rows_iter, metrics_in_order):
        if not isinstance(row, (list, tuple)) or len(row) < 4:
            continue
        _name, mtype, score_raw, comment = row[0], row[1], row[2], row[3]
        score, err = _parse_manual_score(score_raw, mtype or metric["type"])
        if err:
            errors.append(f"{metric['name']}: {err}")
            continue
        if score is None:
            continue
        assistant.store.upsert_evaluation_result(
            judge_run_id=judge_run_id,
            evaluation_run_id=jr["evaluation_run_id"],
            prediction_id=pred["prediction_id"],
            annotation_id=pred["annotation_id"],
            metric_id=metric["metric_id"],
            score=score,
            judge_type="manual",
            comment=(str(comment).strip() or None) if comment is not None else None,
            judge_reasoning=None,
        )
        saved += 1
    msg = f"Saved {saved} score(s)."
    if errors:
        msg += " Errors: " + "; ".join(errors)
    return (
        msg,
        _aggregates_html(assistant, judge_run_id),
        gr.update(choices=_judge_run_choices(assistant), value=judge_run_id),
    )


async def on_run_llm_judge(judge_run_id, assistant):
    if assistant is None:
        assistant = ChatAssistant()
    if not judge_run_id:
        return assistant, "Select a judge run.", gr.update(), gr.update()
    try:
        summary = await run_llm_judge(assistant=assistant, judge_run_id=judge_run_id)
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
                gr.Button("Manage metrics →", link="../config", size="sm", scale=1)
            judge_type_rd = gr.Radio(
                label="Judge type", choices=["manual", "llm"], value="manual"
            )
            jr_name = gr.Textbox(
                label="Judge run name", placeholder="e.g. manual-2026-04-25"
            )
            create_jr_btn = gr.Button("Create judge run", variant="primary")

            gr.Markdown("### Existing judge runs")
            judge_run_dd = gr.Dropdown(label="Judge run", choices=[], interactive=True)
            with gr.Row():
                refresh_btn = gr.Button("Refresh", size="sm")
                run_llm_btn = gr.Button("Run LLM judge", size="sm")
                delete_jr_btn = gr.Button("Delete", variant="stop", size="sm")
            jr_status_md = gr.Markdown("")

            gr.Markdown("### Aggregates")
            aggregates_html = gr.HTML(value="")

        # Right: prediction viewer + scoring
        with gr.Column(scale=2, min_width=500):
            gr.Markdown("### Prediction")
            nav_md = gr.Markdown("_Select a judge run to start._")
            with gr.Row():
                prev_btn = gr.Button("◀ Prev", size="sm")
                next_btn = gr.Button("Next ▶", size="sm")
                save_btn = gr.Button("Save scores", variant="primary", size="sm")
            pred_idx = gr.State(value=0)
            pred_html = gr.HTML(value="")
            gr.Markdown(
                "### Scores — edit the *Score* and *Comment* columns, then click **Save scores**"
            )
            scores_df = gr.Dataframe(
                headers=["Metric", "Type", "Score", "Comment"],
                datatype=["str", "str", "str", "str"],
                interactive=True,
                wrap=True,
            )

    create_jr_btn.click(
        fn=on_create_judge_run,
        inputs=[eval_run_dd, metrics_multi, judge_type_rd, jr_name, assistant_state],
        outputs=[assistant_state, judge_run_dd, jr_status_md],
    )
    refresh_btn.click(
        fn=on_judge_refresh,
        inputs=[assistant_state],
        outputs=[assistant_state, eval_run_dd, metrics_multi, judge_run_dd],
    )
    judge_run_dd.change(
        fn=on_judge_run_select,
        inputs=[judge_run_dd, assistant_state],
        outputs=[pred_idx, pred_html, nav_md, scores_df, aggregates_html],
    )
    prev_btn.click(
        fn=lambda idx, jr, a: on_nav_prediction(-1, idx, jr, a),
        inputs=[pred_idx, judge_run_dd, assistant_state],
        outputs=[pred_idx, pred_html, nav_md, scores_df],
    )
    next_btn.click(
        fn=lambda idx, jr, a: on_nav_prediction(1, idx, jr, a),
        inputs=[pred_idx, judge_run_dd, assistant_state],
        outputs=[pred_idx, pred_html, nav_md, scores_df],
    )
    save_btn.click(
        fn=on_save_manual_scores,
        inputs=[pred_idx, judge_run_dd, scores_df, assistant_state],
        outputs=[jr_status_md, aggregates_html, judge_run_dd],
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

    return eval_run_dd, metrics_multi, judge_run_dd, aggregates_html
