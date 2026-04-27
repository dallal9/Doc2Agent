"""Config → System tab — view & edit .env values from the UI.

Two sections:
  - Live: changes apply immediately via os.environ; lazily-read settings pick
    them up on next use (new ChatAssistant, next eval run, next agent init).
  - Restart-required: cached at module import in gradio_app.py or attached as
    log handlers — only effective after a full process restart.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

import gradio as gr

from src.config.env_schema import ENV_VARS, EnvVar, vars_by_group
from src.config.env_writer import write_env
from src.config_versions import (
    current_general_state,
    general_allowed_keys,
    get_version,
    save_version,
    version_choices,
)
from src.logging import setup_logging

logger = setup_logging("system_tab")

ENV_PATH = Path(".env")
EXAMPLE_PATH = Path("env.example")


def _current_value(var: EnvVar) -> str:
    raw = os.environ.get(var.key)
    if raw is None or raw == "":
        return ""
    return raw


def _coerce_for_input(var: EnvVar, raw: str) -> object:
    """Convert string env value into the right Gradio component value."""
    if var.type == "bool":
        return raw.lower() in ("1", "true", "yes", "on") if raw else False
    if var.type == "int":
        try:
            return int(raw) if raw else None
        except ValueError:
            return None
    if var.type == "float":
        try:
            return float(raw) if raw else None
        except ValueError:
            return None
    return raw


def _coerce_for_storage(var: EnvVar, value: object) -> str:
    """Convert Gradio component value back to a .env string."""
    if value is None:
        return ""
    if var.type == "bool":
        return "true" if bool(value) else "false"
    if var.type in ("int", "float"):
        if value == "" or value is None:
            return ""
        try:
            if var.type == "int":
                return str(int(value))
            return str(float(value))
        except (TypeError, ValueError):
            return ""
    if var.type == "json":
        text = str(value).strip()
        if not text:
            return ""
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{var.key} is not valid JSON: {exc}") from exc
        return text
    return str(value)


def _make_input(var: EnvVar) -> gr.components.Component:
    label = var.key
    info = var.description
    current = _coerce_for_input(var, _current_value(var))
    if var.type == "bool":
        return gr.Checkbox(label=label, info=info, value=bool(current))
    if var.type == "int":
        return gr.Number(label=label, info=info, value=current, precision=0)
    if var.type == "float":
        return gr.Number(label=label, info=info, value=current)
    if var.type == "secret":
        return gr.Textbox(label=label, info=info, value=current or "", type="password")
    if var.type == "json":
        return gr.Textbox(label=label, info=info, value=current or "", lines=4)
    placeholder = var.default or ""
    return gr.Textbox(label=label, info=info, value=current or "", placeholder=placeholder)


def _apply_log_level() -> None:
    """Reset root logger level from current LOG_LEVEL env value."""
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        handler.setLevel(level)


def _collect_updates(var_keys: list[str], values: list[object]) -> dict[str, str]:
    updates: dict[str, str] = {}
    for key, value in zip(var_keys, values):
        var = next((v for v in ENV_VARS if v.key == key), None)
        if var is None:
            continue
        updates[key] = _coerce_for_storage(var, value)
    return updates


def _save_to_env(updates: dict[str, str]) -> Path:
    return write_env(updates, env_path=ENV_PATH, example_path=EXAMPLE_PATH)


def _push_to_environ(updates: dict[str, str]) -> None:
    for key, value in updates.items():
        if value == "":
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def build_system_tab(assistant_state: gr.State | None = None):
    gr.Markdown(
        "## System — environment configuration\n"
        "Edit values from your `.env` file. **Live** settings apply on save; "
        "**Restart-required** settings only take effect after restarting the app."
    )

    live_keys: list[str] = []
    live_inputs: list[gr.components.Component] = []
    restart_keys: list[str] = []
    restart_inputs: list[gr.components.Component] = []

    with gr.Accordion("Live settings (apply on save)", open=True):
        for group, vars_in_group in vars_by_group(reload="live").items():
            with gr.Group():
                gr.Markdown(f"### {group}")
                for v in vars_in_group:
                    comp = _make_input(v)
                    live_keys.append(v.key)
                    live_inputs.append(comp)

    with gr.Accordion("Restart-required settings", open=False):
        gr.Markdown("_These are cached at startup. Click **Save & Restart** to apply._")
        for group, vars_in_group in vars_by_group(reload="restart").items():
            with gr.Group():
                gr.Markdown(f"### {group}")
                for v in vars_in_group:
                    comp = _make_input(v)
                    restart_keys.append(v.key)
                    restart_inputs.append(comp)

    status_md = gr.Markdown("")

    with gr.Row():
        save_live_btn = gr.Button("Save (apply now)", variant="primary")
        save_only_btn = gr.Button("Save (no apply)")
        save_restart_btn = gr.Button("Save & Restart", variant="stop")

    def on_save_live(*values):
        live_values = list(values[: len(live_keys)])
        restart_values = list(values[len(live_keys) :])
        try:
            live_updates = _collect_updates(live_keys, live_values)
            restart_updates = _collect_updates(restart_keys, restart_values)
        except ValueError as exc:
            return f"❌ {exc}"
        all_updates = {**live_updates, **restart_updates}
        path = _save_to_env(all_updates)
        _push_to_environ(live_updates)
        _apply_log_level()
        logger.info("System tab: live save, %d keys updated, env=%s", len(all_updates), path)
        msg = (
            f"✅ Saved {len(all_updates)} value(s) to `{path}`. "
            f"Live settings ({len(live_updates)}) applied. "
        )
        if restart_updates:
            msg += f"{len(restart_updates)} restart-required setting(s) saved — restart to apply."
        return msg

    def on_save_only(*values):
        live_values = list(values[: len(live_keys)])
        restart_values = list(values[len(live_keys) :])
        try:
            updates = {
                **_collect_updates(live_keys, live_values),
                **_collect_updates(restart_keys, restart_values),
            }
        except ValueError as exc:
            return f"❌ {exc}"
        path = _save_to_env(updates)
        logger.info("System tab: save-only, %d keys updated, env=%s", len(updates), path)
        return f"💾 Saved {len(updates)} value(s) to `{path}`. Nothing applied yet."

    def on_save_restart(*values):
        live_values = list(values[: len(live_keys)])
        restart_values = list(values[len(live_keys) :])
        try:
            updates = {
                **_collect_updates(live_keys, live_values),
                **_collect_updates(restart_keys, restart_values),
            }
        except ValueError as exc:
            return f"❌ {exc}"
        path = _save_to_env(updates)
        logger.warning(
            "System tab: save & restart requested, %d keys updated, env=%s",
            len(updates),
            path,
        )
        # Schedule restart shortly so the response can flush back to the UI.
        import threading

        def _restart() -> None:
            import time

            time.sleep(1.0)
            os.execv(sys.executable, [sys.executable, *sys.argv])

        threading.Thread(target=_restart, daemon=True).start()
        return (
            f"♻️ Saved {len(updates)} value(s) to `{path}`. "
            "Restarting now — reconnect in a few seconds."
        )

    all_inputs = live_inputs + restart_inputs
    save_live_btn.click(fn=on_save_live, inputs=all_inputs, outputs=[status_md])
    save_only_btn.click(fn=on_save_only, inputs=all_inputs, outputs=[status_md])
    save_restart_btn.click(fn=on_save_restart, inputs=all_inputs, outputs=[status_md])

    # ---- Versioning (general / non-secret env) ----
    gr.Markdown(
        "### Versions\n"
        "Snapshot the current non-secret env values. Tokens (e.g. "
        "`OPENROUTER_API_KEY`) are **never** stored in a version."
    )
    with gr.Row():
        version_dd = gr.Dropdown(
            label="Existing versions",
            choices=version_choices("general"),
            value=None,
            interactive=True,
            scale=3,
        )
        load_version_btn = gr.Button("Load into form", size="sm", scale=1)
        refresh_versions_btn = gr.Button("Refresh", size="sm", scale=1)

    version_label_in = gr.Textbox(
        label="Label (optional)",
        placeholder="e.g. baseline, low-temp, eval-v3",
    )
    version_desc_in = gr.Textbox(label="Description (optional)", lines=2)
    save_version_btn = gr.Button("Save current values as new version")
    version_status_md = gr.Markdown("")

    all_keys = live_keys + restart_keys

    def on_save_version(label, desc, *values):
        try:
            updates = _collect_updates(all_keys, list(values))
        except ValueError as exc:
            return f"❌ {exc}", gr.update()
        # Filter to allowlist (excludes secrets) and drop empty strings.
        allowed = set(general_allowed_keys())
        content = {k: v for k, v in updates.items() if k in allowed and v != ""}
        ver = save_version("general", content, label=label, description=desc)
        logger.info("Saved general config version=%s keys=%d", ver.id, len(content))
        msg = (
            f"📌 Snapshot saved as `{ver.id}`"
            + (f" (`{ver.label}`)" if ver.label else "")
            + f" — {len(content)} key(s)."
        )
        return msg, gr.update(choices=version_choices("general"), value=ver.id)

    def on_load_version(version_id):
        if not version_id:
            return [gr.update() for _ in all_inputs] + ["Select a version to load."]
        v = get_version("general", version_id)
        if v is None:
            return [gr.update() for _ in all_inputs] + [f"Version `{version_id}` not found."]
        content = v.content or {}
        updates = []
        for key in all_keys:
            var = next((vv for vv in ENV_VARS if vv.key == key), None)
            if var is None:
                updates.append(gr.update())
                continue
            raw = content.get(key, "")
            updates.append(gr.update(value=_coerce_for_input(var, str(raw))))
        return updates + [f"Loaded version `{v.id}` into form — click **Save** to make it active."]

    def on_refresh_versions():
        return gr.update(choices=version_choices("general"))

    save_version_btn.click(
        fn=on_save_version,
        inputs=[version_label_in, version_desc_in, *all_inputs],
        outputs=[version_status_md, version_dd],
    )
    load_version_btn.click(
        fn=on_load_version,
        inputs=[version_dd],
        outputs=[*all_inputs, version_status_md],
    )
    refresh_versions_btn.click(fn=on_refresh_versions, outputs=[version_dd])

    return status_md
