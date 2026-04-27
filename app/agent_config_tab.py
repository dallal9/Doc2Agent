"""Config → Agent Config tab — edit agents.json + prompts.json with versioning.

Edits write back to the live config files (same paths the rest of the app
reads from). A "Save as new version" button captures an immutable snapshot
under data/config_versions/agent/ that can later be loaded into the form
or pinned to an evaluation run.
"""

from __future__ import annotations

import json
from pathlib import Path

import gradio as gr

from src.agents_config.schemas import (
    AGENTS_CONFIG_PATH_ENV,
    CONFIG_DIR,
    PROMPTS_CONFIG_PATH_ENV,
)
from src.config_versions import (
    current_agent_state,
    get_version,
    save_version,
    version_choices,
)
from src.logging import setup_logging

logger = setup_logging("agent_config_tab")


def _agents_path() -> Path:
    import os

    raw = os.getenv(AGENTS_CONFIG_PATH_ENV)
    return Path(raw) if raw else (CONFIG_DIR / "agents.json")


def _prompts_path() -> Path:
    import os

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


def build_agent_config_tab():
    gr.Markdown(
        "## Agent Config — `agents.json` and `prompts.json`\n"
        "Edit live config files and (optionally) capture a versioned snapshot. "
        "Versions are immutable JSON files under `data/config_versions/agent/` "
        "and can be pinned to an evaluation run for reproducibility."
    )

    agents_path = _agents_path()
    prompts_path = _prompts_path()

    with gr.Row():
        with gr.Column(scale=1, min_width=420):
            gr.Markdown(f"### `agents.json`  \n_{agents_path}_")
            agents_box = gr.Code(
                value=_read_text(agents_path),
                language="json",
                lines=22,
                label=None,
            )
        with gr.Column(scale=1, min_width=420):
            gr.Markdown(f"### `prompts.json`  \n_{prompts_path}_")
            prompts_box = gr.Code(
                value=_read_text(prompts_path),
                language="json",
                lines=22,
                label=None,
            )

    status_md = gr.Markdown("")

    with gr.Row():
        save_files_btn = gr.Button("Save to files", variant="primary")
        save_version_btn = gr.Button("Save as new version", variant="secondary")
        reload_btn = gr.Button("Reload from disk", size="sm")

    gr.Markdown("### Versions")
    with gr.Row():
        version_dd = gr.Dropdown(
            label="Existing versions",
            choices=version_choices("agent"),
            value=None,
            interactive=True,
            scale=3,
        )
        load_version_btn = gr.Button("Load into editor", size="sm", scale=1)
        refresh_btn = gr.Button("Refresh", size="sm", scale=1)

    version_label_in = gr.Textbox(
        label="Label (optional)",
        placeholder="e.g. baseline, gemma-strict, prompt-v2",
    )
    version_desc_in = gr.Textbox(label="Description (optional)", lines=2)

    # ---- handlers ----

    def on_save_files(agents_text, prompts_text):
        agents, err = _validate_json("agents.json", agents_text)
        if err:
            return f"❌ {err}", gr.update()
        prompts, err = _validate_json("prompts.json", prompts_text)
        if err:
            return f"❌ {err}", gr.update()
        _agents_path().write_text(
            json.dumps(agents, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        _prompts_path().write_text(
            json.dumps(prompts, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        logger.info("Agent config saved to files")
        return (
            f"✅ Saved to `{_agents_path()}` and `{_prompts_path()}`. "
            "New ChatAssistant instances will pick up the changes.",
            gr.update(),
        )

    def on_save_version(agents_text, prompts_text, label, desc):
        agents, err = _validate_json("agents.json", agents_text)
        if err:
            return f"❌ {err}", gr.update()
        prompts, err = _validate_json("prompts.json", prompts_text)
        if err:
            return f"❌ {err}", gr.update()
        v = save_version(
            "agent",
            {"agents": agents, "prompts": prompts},
            label=label,
            description=desc,
        )
        logger.info("Saved agent config version=%s", v.id)
        return (
            f"📌 Snapshot saved as `{v.id}`" + (f" (`{v.label}`)" if v.label else "") + ".",
            gr.update(choices=version_choices("agent"), value=v.id),
        )

    def on_reload():
        return (
            _read_text(_agents_path()),
            _read_text(_prompts_path()),
            "Reloaded from disk.",
        )

    def on_load_version(version_id):
        if not version_id:
            return gr.update(), gr.update(), "Select a version to load."
        v = get_version("agent", version_id)
        if v is None:
            return gr.update(), gr.update(), f"Version `{version_id}` not found."
        agents_text = json.dumps(v.content.get("agents") or {}, indent=2, ensure_ascii=False)
        prompts_text = json.dumps(v.content.get("prompts") or {}, indent=2, ensure_ascii=False)
        return (
            agents_text,
            prompts_text,
            f"Loaded version `{v.id}` into editor — click **Save to files** to make it active.",
        )

    def on_refresh():
        return gr.update(choices=version_choices("agent"))

    save_files_btn.click(
        fn=on_save_files,
        inputs=[agents_box, prompts_box],
        outputs=[status_md, version_dd],
    )
    save_version_btn.click(
        fn=on_save_version,
        inputs=[agents_box, prompts_box, version_label_in, version_desc_in],
        outputs=[status_md, version_dd],
    )
    reload_btn.click(fn=on_reload, outputs=[agents_box, prompts_box, status_md])
    load_version_btn.click(
        fn=on_load_version,
        inputs=[version_dd],
        outputs=[agents_box, prompts_box, status_md],
    )
    refresh_btn.click(fn=on_refresh, outputs=[version_dd])

    return status_md
