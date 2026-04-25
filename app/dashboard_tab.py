"""Dashboard page (Milestone 5) — Data and Evaluations overview."""

from __future__ import annotations

import html
import itertools

import gradio as gr

_TABLE_ID_COUNTER = itertools.count(1)


def _next_table_id() -> str:
    return f"d2a-tbl-{next(_TABLE_ID_COUNTER)}"


from src.chat import ChatAssistant
from src.logging import setup_logging

logger = setup_logging("dashboard_tab")


# ---- helpers --------------------------------------------------------------


def _kpi_block(items: list[tuple[str, object]]) -> str:
    cells = []
    for label, value in items:
        cells.append(
            "<div style='flex:1;min-width:120px;padding:12px 16px;"
            "border:1px solid #2a2a2a;border-radius:8px;margin:4px'>"
            f"<div style='font-size:0.8em;opacity:0.75'>{html.escape(label)}</div>"
            f"<div style='font-size:1.6em;font-weight:600'>{html.escape(str(value))}</div>"
            "</div>"
        )
    return "<div style='display:flex;flex-wrap:wrap'>" + "".join(cells) + "</div>"


def _table(
    headers: list[str],
    rows: list[list[object]],
    empty_msg: str = "—",
    *,
    max_height: int = 360,
    searchable: bool = True,
) -> str:
    if not rows:
        return f"<p><em>{html.escape(empty_msg)}</em></p>"
    tid = _next_table_id()
    th = "".join(
        "<th style='text-align:left;padding:6px;border-bottom:1px solid #888;"
        "position:sticky;top:0;background:var(--background-fill-primary, #1a1a1a);"
        f"z-index:1'>{html.escape(h)}</th>"
        for h in headers
    )
    body = []
    for r in rows:
        tds = "".join(
            "<td style='padding:6px;border-bottom:1px solid #2a2a2a;vertical-align:top'>"
            f"{html.escape('' if c is None else str(c))}</td>"
            for c in r
        )
        body.append(f"<tr>{tds}</tr>")
    search_box = ""
    if searchable:
        search_box = (
            "<input type='search' placeholder='Filter rows...' "
            f"data-target='{tid}' "
            'oninput="(function(e){var id=e.target.dataset.target;var q=e.target.value.toLowerCase();'
            "var t=document.getElementById(id);if(!t)return;"
            "t.querySelectorAll('tbody tr').forEach(function(r){"
            "r.style.display=r.innerText.toLowerCase().indexOf(q)>=0?'':'none';});"
            '})(event)" '
            "style='width:100%;padding:4px 8px;margin-bottom:6px;"
            "border:1px solid #555;border-radius:4px;background:transparent;color:inherit'/>"
        )
    return (
        f"<div>{search_box}"
        f"<div style='max-height:{max_height}px;overflow:auto;"
        "border:1px solid #2a2a2a;border-radius:4px'>"
        f"<table id='{tid}' style='width:100%;border-collapse:collapse;font-size:0.9em'>"
        f"<thead><tr>{th}</tr></thead><tbody>{''.join(body)}</tbody></table>"
        "</div></div>"
    )


def _fmt_score(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


# ---- Data tab -------------------------------------------------------------


def _data_overview(assistant: ChatAssistant | None) -> tuple[str, str, str, str]:
    if assistant is None:
        return "", "", "", ""

    store = assistant.store
    docs = store.list_documents()
    datasets = store.list_datasets()

    annotation_set_rows: list[list[object]] = []
    total_sets = 0
    total_annotations = 0
    for doc in docs:
        sets = store.list_annotation_sets(doc.doc_id)
        for aset in sets:
            total_sets += 1
            n_ann = len(store.list_annotations(aset.set_id))
            total_annotations += n_ann
            annotation_set_rows.append([doc.file_name, aset.label, n_ann, aset.created_at or "—"])

    kpis = _kpi_block(
        [
            ("Documents", len(docs)),
            ("Annotation sets", total_sets),
            ("Annotations", total_annotations),
            ("Datasets", len(datasets)),
        ]
    )

    docs_table = _table(
        ["File", "Pages", "Cached queries", "Doc id"],
        [
            [
                d.file_name,
                d.page_count,
                store.get_query_count_for_document(d.doc_id),
                d.doc_id,
            ]
            for d in docs
        ],
        empty_msg="No documents uploaded yet.",
    )
    sets_table = _table(
        ["Document", "Set label", "Annotations", "Created"],
        annotation_set_rows,
        empty_msg="No annotation sets yet.",
    )
    datasets_table = _table(
        ["Name", "Annotations", "Description", "Created"],
        [
            [d["name"], d["annotation_count"], d.get("description") or "", d["created_at"]]
            for d in datasets
        ],
        empty_msg="No datasets yet.",
    )
    return kpis, docs_table, sets_table, datasets_table


def build_data_dashboard_tab(assistant_state: gr.State):
    gr.Markdown("## Data overview")
    with gr.Row():
        refresh_btn = gr.Button("Refresh", size="sm")
    kpis_html = gr.HTML()
    gr.Markdown("### Documents")
    docs_html = gr.HTML()
    gr.Markdown("### Annotation sets")
    sets_html = gr.HTML()
    gr.Markdown("### Datasets")
    datasets_html = gr.HTML()

    refresh_btn.click(
        fn=on_data_refresh,
        inputs=[assistant_state],
        outputs=[assistant_state, kpis_html, docs_html, sets_html, datasets_html],
    )
    return kpis_html, docs_html, sets_html, datasets_html


def on_data_refresh(assistant):
    if assistant is None:
        assistant = ChatAssistant()
    kpis, docs_t, sets_t, ds_t = _data_overview(assistant)
    return assistant, kpis, docs_t, sets_t, ds_t


# ---- Evaluations tab ------------------------------------------------------


def _is_low_score(score: object, metric_type: str | None) -> bool:
    """Heuristic for 'low' scores: bool=False/0, numeric < 0.5."""
    if score is None:
        return False
    try:
        v = float(score)
    except (TypeError, ValueError):
        return False
    if metric_type == "bool":
        return v <= 0
    return v < 0.5


def _evaluation_overview(
    assistant: ChatAssistant | None,
) -> tuple[str, str, str, str, str, str]:
    if assistant is None:
        return "", "", "", "", "", ""

    store = assistant.store
    runs = store.list_evaluation_runs()
    judge_runs = store.list_judge_runs()
    metrics = store.list_metrics()

    total_predictions = 0
    failed_runs = 0
    runs_rows: list[list[object]] = []
    failed_predictions: list[list[object]] = []
    missing_doc_predictions: list[list[object]] = []

    for r in runs:
        run_id = r["run_id"]
        preds = store.list_predictions(run_id)
        total_predictions += len(preds)
        ok = sum(1 for p in preds if p["status"] == "success")
        failed = sum(1 for p in preds if p["status"] == "failed")
        skipped = sum(1 for p in preds if p["status"] == "skipped")
        if r["status"] == "failed":
            failed_runs += 1
        runs_rows.append(
            [
                r["name"],
                r.get("dataset_name") or "—",
                r["status"],
                len(preds),
                ok,
                failed,
                skipped,
                r.get("created_at") or "—",
            ]
        )
        for p in preds:
            if p["status"] == "failed":
                failed_predictions.append(
                    [
                        r["name"],
                        (p.get("question") or "")[:140],
                        (p.get("error_message") or "")[:200],
                    ]
                )
            if not p.get("document_reference"):
                missing_doc_predictions.append(
                    [
                        r["name"],
                        (p.get("question") or "")[:140],
                        p["status"],
                    ]
                )

    # Per-judge-run aggregates and per-metric global rollup
    pivot_metric_ids: list[str] = [m["metric_id"] for m in metrics]
    pivot_metric_names: list[str] = [m["name"] for m in metrics]
    pivot_rows: list[list[object]] = []
    judge_rows: list[list[object]] = []
    metric_rollup: dict[str, dict] = {
        m["metric_id"]: {
            "name": m["name"],
            "type": m["type"],
            "aggregation": m["aggregation"],
            "scores": [],
            "judged": 0,
            "missing": 0,
        }
        for m in metrics
    }
    low_score_rows: list[list[object]] = []
    total_results = 0

    for jr in judge_runs:
        aggs = store.aggregate_judge_run(jr["judge_run_id"])
        agg_summary = ", ".join(
            f"{a['metric_name']}={_fmt_score(a['score'])} ({a['judged_count']}/{a['total_predictions']})"
            for a in aggs
        )
        judge_rows.append(
            [
                jr["name"],
                jr.get("evaluation_run_name") or "—",
                jr["judge_type"],
                jr["status"],
                agg_summary or "—",
                jr.get("created_at") or "—",
            ]
        )

        agg_by_id = {a["metric_id"]: a for a in aggs}
        pivot_row: list[object] = [
            jr["name"],
            jr.get("evaluation_run_name") or "—",
            jr["judge_type"],
        ]
        for mid in pivot_metric_ids:
            a = agg_by_id.get(mid)
            if a is None:
                pivot_row.append("—")
            else:
                pivot_row.append(
                    f"{_fmt_score(a['score'])} ({a['judged_count']}/{a['total_predictions']})"
                )
        pivot_rows.append(pivot_row)

        results = store.list_evaluation_results(jr["judge_run_id"])
        total_results += len(results)
        for res in results:
            mid = res["metric_id"]
            if mid in metric_rollup:
                metric_rollup[mid]["scores"].append(res["score"])
                metric_rollup[mid]["judged"] += 1
            if _is_low_score(res["score"], res.get("metric_type")):
                pred = store.get_prediction(res["prediction_id"])
                low_score_rows.append(
                    [
                        jr["name"],
                        res.get("metric_name") or mid,
                        _fmt_score(res["score"]),
                        ((pred or {}).get("question") or "")[:140],
                        ((pred or {}).get("agent_answer") or "")[:200],
                    ]
                )

    metric_rollup_rows: list[list[object]] = []
    for info in metric_rollup.values():
        scores = info["scores"]
        agg = info["aggregation"]
        if not scores:
            value = None
        elif agg == "avg":
            value = sum(scores) / len(scores)
        elif agg == "sum":
            value = sum(scores)
        elif agg == "min":
            value = min(scores)
        elif agg == "max":
            value = max(scores)
        else:
            value = None
        metric_rollup_rows.append(
            [info["name"], info["type"], agg, _fmt_score(value), info["judged"]]
        )

    kpis = _kpi_block(
        [
            ("Evaluation runs", len(runs)),
            ("Predictions", total_predictions),
            ("Judge runs", len(judge_runs)),
            ("Judgments", total_results),
            ("Failed runs", failed_runs),
            ("Metrics", len(metrics)),
        ]
    )
    runs_table = _table(
        ["Name", "Dataset", "Status", "Predictions", "OK", "Failed", "Skipped", "Created"],
        runs_rows,
        empty_msg="No evaluation runs yet.",
    )
    judge_table = _table(
        ["Name", "Eval run", "Judge", "Status", "Aggregates", "Created"],
        judge_rows,
        empty_msg="No judge runs yet.",
    )
    pivot_table = _table(
        ["Judge run", "Eval run", "Judge"] + pivot_metric_names,
        pivot_rows,
        empty_msg="No judge runs / metrics to pivot yet.",
    )
    metric_table = _table(
        ["Metric", "Type", "Aggregation", "Score", "Judged"],
        metric_rollup_rows,
        empty_msg="No metrics defined.",
    )
    failures_table = _table(
        ["Run", "Question", "Error"],
        failed_predictions,
        empty_msg="No failed predictions.",
    )
    low_table = _table(
        ["Judge run", "Metric", "Score", "Question", "Agent answer"],
        low_score_rows,
        empty_msg="No low-score judgments.",
    )
    missing_doc_table = _table(
        ["Run", "Question", "Status"],
        missing_doc_predictions,
        empty_msg="All predictions have document references.",
    )

    failure_html = (
        "<h4>Failed predictions</h4>"
        + failures_table
        + "<h4 style='margin-top:1em'>Low-score judgments (bool ≤ 0 or score &lt; 0.5)</h4>"
        + low_table
        + "<h4 style='margin-top:1em'>Predictions missing document reference</h4>"
        + missing_doc_table
    )

    return kpis, runs_table, judge_table, pivot_table, metric_table, failure_html


def build_evaluation_dashboard_tab(assistant_state: gr.State):
    gr.Markdown("## Evaluations overview")
    with gr.Row():
        refresh_btn = gr.Button("Refresh", size="sm")
    kpis_html = gr.HTML()
    gr.Markdown("### Evaluation runs")
    runs_html = gr.HTML()
    gr.Markdown("### Judge runs")
    judge_html = gr.HTML()
    gr.Markdown("### Average score per metric, per judge run")
    pivot_html = gr.HTML()
    gr.Markdown("### Metric rollup (across all judge runs)")
    metric_html = gr.HTML()
    gr.Markdown("### Failure inspection")
    failure_html = gr.HTML()

    refresh_btn.click(
        fn=on_evaluation_refresh,
        inputs=[assistant_state],
        outputs=[
            assistant_state,
            kpis_html,
            runs_html,
            judge_html,
            pivot_html,
            metric_html,
            failure_html,
        ],
    )
    return kpis_html, runs_html, judge_html, pivot_html, metric_html, failure_html


def on_evaluation_refresh(assistant):
    if assistant is None:
        assistant = ChatAssistant()
    kpis, runs_t, judge_t, pivot_t, metric_t, failure_t = _evaluation_overview(assistant)
    return assistant, kpis, runs_t, judge_t, pivot_t, metric_t, failure_t


# ---- combined page load ---------------------------------------------------


def on_dashboard_load(assistant):
    if assistant is None:
        assistant = ChatAssistant()
    data_kpis, docs_t, sets_t, ds_t = _data_overview(assistant)
    eval_kpis, runs_t, judge_t, pivot_t, metric_t, failure_t = _evaluation_overview(assistant)
    return (
        assistant,
        data_kpis,
        docs_t,
        sets_t,
        ds_t,
        eval_kpis,
        runs_t,
        judge_t,
        pivot_t,
        metric_t,
        failure_t,
    )
