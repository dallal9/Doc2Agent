"""Config → Agent Config tab — edit agents.json + prompts.json with versioning.

Versions are immutable. Editing the JSON and clicking **Save new version**
writes the live files and snapshots a new version in one step. Existing
versions can only be deleted, not edited; if the last one is removed, a
fresh default is auto-recreated from the current live state.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import gradio as gr

from src.agents_config.schemas import (
    AGENTS_CONFIG_PATH_ENV,
    CONFIG_DIR,
    PROMPTS_CONFIG_PATH_ENV,
)
from src.config_versions import (
    delete_version,
    ensure_default_version,
    get_version,
    save_version,
    set_active_version,
    version_choices,
)
from src.logging import setup_logging

logger = setup_logging("agent_config_tab")


def _agents_path() -> Path:
    raw = os.getenv(AGENTS_CONFIG_PATH_ENV)
    return Path(raw) if raw else (CONFIG_DIR / "agents.json")


def _prompts_path() -> Path:
    raw = os.getenv(PROMPTS_CONFIG_PATH_ENV)
    return Path(raw) if raw else (CONFIG_DIR / "prompts.json")


def _read_text(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


def _validate_json(label: str, text: str) -> tuple[dict | None, str | None]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        return None, f"{label} is not valid JSON: {e}"
    if not isinstance(data, dict):
        return None, f"{label} must be a JSON object."
    return data, None


def _auto_name(prefix: str = "agent") -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"


def build_agent_config_tab():
    default_v = ensure_default_version("agent")

    gr.Markdown(
        "## Agent Config — `agents.json` and `prompts.json`\n"
        "Versions are immutable snapshots stored under "
        "`data/config_versions/agent/`. Pick a version, then **Apply** to "
        "switch the live files to it, or edit the JSON below and **Save new "
        "version** to snapshot the current editor contents."
    )

    # ---- Versions block (top) ----
    with gr.Row():
        version_dd = gr.Dropdown(
            label="Version",
            choices=version_choices("agent"),
            value=default_v.id,
            interactive=True,
            scale=4,
        )
        refresh_btn = gr.Button("Refresh", size="sm", scale=1)
        apply_btn = gr.Button("Apply", variant="primary", scale=1)
        delete_btn = gr.Button("Delete", variant="stop", scale=1)

    status_md = gr.Markdown("")

    # ---- Editors ----
    gr.Markdown("### Editor")
    agents_path = _agents_path()
    prompts_path = _prompts_path()
    with gr.Row():
        with gr.Column(scale=1, min_width=420):
            gr.Markdown(f"#### `agents.json`  \n_{agents_path}_")
            agents_box = gr.Code(
                value=_read_text(agents_path),
                language="json",
                lines=22,
            )
        with gr.Column(scale=1, min_width=420):
            gr.Markdown(f"#### `prompts.json`  \n_{prompts_path}_")
            prompts_box = gr.Code(
                value=_read_text(prompts_path),
                language="json",
                lines=22,
            )

    gr.Markdown("### Save as new version")
    with gr.Row():
        new_name_in = gr.Textbox(
            label="Name",
            value=_auto_name("agent"),
            scale=2,
        )
        new_desc_in = gr.Textbox(label="Description (optional)", scale=3)
    save_btn = gr.Button("Save new version", variant="primary")
    gr.Markdown(
        "_**Save new version** writes the editor contents to `agents.json` and "
        "`prompts.json` and creates an immutable snapshot. **Apply** writes the "
        "selected version's snapshot to the live files. New ChatAssistant "
        "instances pick up the live files automatically — no app restart required._"
    )

    # ---- handlers ----

    def on_save(agents_text, prompts_text, name, desc):
        agents, err = _validate_json("agents.json", agents_text)
        if err:
            return f"❌ {err}", gr.update(), gr.update()
        prompts, err = _validate_json("prompts.json", prompts_text)
        if err:
            return f"❌ {err}", gr.update(), gr.update()
        _agents_path().write_text(
            json.dumps(agents, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        _prompts_path().write_text(
            json.dumps(prompts, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        v = save_version(
            "agent",
            {"agents": agents, "prompts": prompts},
            name=name,
            description=desc,
        )
        set_active_version("agent", v.id)
        logger.info("Saved agent config version=%s (active)", v.id)
        return (
            f"✅ Saved live files and snapshotted as `{v.id}`.",
            gr.update(choices=version_choices("agent"), value=v.id),
            gr.update(value=_auto_name("agent")),
        )

    def on_select_version(version_id):
        if not version_id:
            return gr.update(), gr.update(), "", gr.update()
        v = get_version("agent", version_id)
        if v is None:
            return gr.update(), gr.update(), f"Version `{version_id}` not found.", gr.update()
        agents_text = json.dumps(v.content.get("agents") or {}, indent=2, ensure_ascii=False)
        prompts_text = json.dumps(v.content.get("prompts") or {}, indent=2, ensure_ascii=False)
        return (
            agents_text,
            prompts_text,
            f"Loaded `{v.id}` into editor.",
            gr.update(value=_auto_name("agent")),
        )

    def on_apply(version_id):
        if not version_id:
            return gr.update(), gr.update(), "Select a version first."
        v = get_version("agent", version_id)
        if v is None:
            return gr.update(), gr.update(), f"Version `{version_id}` not found."
        agents_text = json.dumps(v.content.get("agents") or {}, indent=2, ensure_ascii=False)
        prompts_text = json.dumps(v.content.get("prompts") or {}, indent=2, ensure_ascii=False)
        _agents_path().write_text(agents_text, encoding="utf-8")
        _prompts_path().write_text(prompts_text, encoding="utf-8")
        set_active_version("agent", v.id)
        logger.info("Applied agent config version=%s to live files", v.id)
        return (
            agents_text,
            prompts_text,
            f"✅ Applied `{v.id}` to live files.",
        )

    def on_delete(version_id):
        if not version_id:
            return gr.update(), gr.update(), gr.update(), "Select a version first."
        removed = delete_version("agent", version_id)
        if not removed:
            return (
                gr.update(),
                gr.update(),
                gr.update(),
                f"Version `{version_id}` not found.",
            )
        logger.info("Deleted agent config version=%s", version_id)
        latest = ensure_default_version("agent")
        set_active_version("agent", latest.id)
        agents_text = json.dumps(latest.content.get("agents") or {}, indent=2, ensure_ascii=False)
        prompts_text = json.dumps(latest.content.get("prompts") or {}, indent=2, ensure_ascii=False)
        return (
            gr.update(choices=version_choices("agent"), value=latest.id),
            agents_text,
            prompts_text,
            f"🗑️ Deleted `{version_id}`. Active version: `{latest.id}`.",
        )

    def on_refresh():
        return gr.update(choices=version_choices("agent"))

    # ---- wiring ----

    save_btn.click(
        fn=on_save,
        inputs=[agents_box, prompts_box, new_name_in, new_desc_in],
        outputs=[status_md, version_dd, new_name_in],
    )
    delete_btn.click(
        fn=on_delete,
        inputs=[version_dd],
        outputs=[version_dd, agents_box, prompts_box, status_md],
    )
    version_dd.change(
        fn=on_select_version,
        inputs=[version_dd],
        outputs=[agents_box, prompts_box, status_md, new_name_in],
    )
    apply_btn.click(
        fn=on_apply,
        inputs=[version_dd],
        outputs=[agents_box, prompts_box, status_md],
    )
    refresh_btn.click(fn=on_refresh, outputs=[version_dd])

    return status_md
