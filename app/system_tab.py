"""Config → System tab — view & edit .env values from the UI.

Versions are immutable. **Save new version** writes `.env`, snapshots a new
version, and restarts the app so all settings (live + restart-required) are
applied uniformly. **Delete current version** removes the selected snapshot;
the last one cannot truly disappear — a fresh default is auto-recreated.

Secrets (env vars declared as `secret` in env_schema, e.g. OPENROUTER_API_KEY)
are never included in a version snapshot, but they ARE still written to `.env`.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import gradio as gr

from src.config.env_schema import ENV_VARS, EnvVar, vars_by_group
from src.config.env_writer import write_env
from src.config_versions import (
    delete_version,
    ensure_default_version,
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


def _schedule_restart() -> None:
    import threading
    import time

    def _restart() -> None:
        time.sleep(1.0)
        os.execv(sys.executable, [sys.executable, *sys.argv])

    threading.Thread(target=_restart, daemon=True).start()


def build_system_tab(assistant_state: gr.State | None = None):
    default_v = ensure_default_version("general")

    gr.Markdown(
        "## System — environment configuration\n"
        "Versions are immutable snapshots stored under "
        "`data/config_versions/general/`. Pick a version to load it into the "
        "form; **Save new version** writes `.env`, snapshots a new version, "
        "and restarts the app."
    )

    # ---- Versions block (top) ----
    gr.Markdown("### Versions")
    with gr.Row():
        version_dd = gr.Dropdown(
            label="Version",
            choices=version_choices("general"),
            value=default_v.id,
            interactive=True,
            scale=4,
        )
        refresh_btn = gr.Button("Refresh", size="sm", scale=1)

    status_md = gr.Markdown("")

    # ---- Env-var editors ----
    gr.Markdown("### Editor")

    live_keys: list[str] = []
    live_inputs: list[gr.components.Component] = []
    restart_keys: list[str] = []
    restart_inputs: list[gr.components.Component] = []

    with gr.Accordion("Live settings", open=True):
        for group, vars_in_group in vars_by_group(reload="live").items():
            with gr.Group():
                gr.Markdown(f"#### {group}")
                for v in vars_in_group:
                    comp = _make_input(v)
                    live_keys.append(v.key)
                    live_inputs.append(comp)

    with gr.Accordion("Restart-required settings", open=False):
        for group, vars_in_group in vars_by_group(reload="restart").items():
            with gr.Group():
                gr.Markdown(f"#### {group}")
                for v in vars_in_group:
                    comp = _make_input(v)
                    restart_keys.append(v.key)
                    restart_inputs.append(comp)

    all_inputs = live_inputs + restart_inputs
    all_keys = live_keys + restart_keys

    gr.Markdown("### New version metadata")
    with gr.Row():
        new_keyword_in = gr.Textbox(
            label="Keyword (optional)",
            placeholder="e.g. baseline / low-temp / eval-v3",
            scale=2,
        )
        new_name_in = gr.Textbox(
            label="Name (optional)",
            placeholder="Leave blank to use the auto-generated id",
            scale=2,
        )
    with gr.Row():
        new_label_in = gr.Textbox(label="Label (optional)", scale=1)
        new_desc_in = gr.Textbox(label="Description (optional)", scale=2)

    with gr.Row():
        save_btn = gr.Button("Save new version", variant="primary")
        delete_btn = gr.Button("Delete current version", variant="stop")
    gr.Markdown(
        "_**Save new version** writes the form values to `.env`, creates an "
        "immutable snapshot, and **restarts the app** so all settings (including "
        "restart-required ones) take effect cleanly. The OpenRouter token is "
        "written to `.env` but never stored in a version snapshot._"
    )

    # ---- handlers ----

    def on_save(keyword, name, label, desc, *values):
        live_values = list(values[: len(live_keys)])
        restart_values = list(values[len(live_keys) :])
        try:
            live_updates = _collect_updates(live_keys, live_values)
            restart_updates = _collect_updates(restart_keys, restart_values)
        except ValueError as exc:
            return f"❌ {exc}", gr.update()
        all_updates = {**live_updates, **restart_updates}
        path = _save_to_env(all_updates)

        allowed = set(general_allowed_keys())
        snapshot_content = {k: v for k, v in all_updates.items() if k in allowed and v != ""}
        ver = save_version(
            "general",
            snapshot_content,
            keyword=keyword,
            name=name,
            label=label,
            description=desc,
        )
        logger.warning(
            "System tab: save new version=%s, %d keys -> env=%s. Restarting.",
            ver.id,
            len(all_updates),
            path,
        )
        _schedule_restart()
        return (
            f"♻️ Saved to `{path}`, snapshotted as `{ver.id}`. "
            "Restarting now — reconnect in a few seconds.",
            gr.update(choices=version_choices("general"), value=ver.id),
        )

    def on_select_version(version_id):
        if not version_id:
            return [gr.update() for _ in all_inputs] + [""]
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
        return updates + [f"Loaded `{v.id}` into form — click **Save new version** to apply."]

    def on_delete(version_id):
        if not version_id:
            return [gr.update(), *(gr.update() for _ in all_inputs), "Select a version first."]
        removed = delete_version("general", version_id)
        if not removed:
            return [
                gr.update(),
                *(gr.update() for _ in all_inputs),
                f"Version `{version_id}` not found.",
            ]
        logger.info("Deleted general config version=%s", version_id)
        latest = ensure_default_version("general")
        # Reload the latest version into the form so the UI matches the new active version.
        content = latest.content or {}
        field_updates = []
        for key in all_keys:
            var = next((vv for vv in ENV_VARS if vv.key == key), None)
            if var is None:
                field_updates.append(gr.update())
                continue
            raw = content.get(key, "")
            field_updates.append(gr.update(value=_coerce_for_input(var, str(raw))))
        return [
            gr.update(choices=version_choices("general"), value=latest.id),
            *field_updates,
            f"🗑️ Deleted `{version_id}`. Active version: `{latest.id}`.",
        ]

    def on_refresh():
        return gr.update(choices=version_choices("general"))

    # ---- wiring ----

    save_btn.click(
        fn=on_save,
        inputs=[new_keyword_in, new_name_in, new_label_in, new_desc_in, *all_inputs],
        outputs=[status_md, version_dd],
    )
    delete_btn.click(
        fn=on_delete,
        inputs=[version_dd],
        outputs=[version_dd, *all_inputs, status_md],
    )
    version_dd.change(
        fn=on_select_version,
        inputs=[version_dd],
        outputs=[*all_inputs, status_md],
    )
    refresh_btn.click(fn=on_refresh, outputs=[version_dd])

    return status_md
