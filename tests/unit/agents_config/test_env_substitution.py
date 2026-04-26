import json

import pytest

from src.agents_config.schemas import load_agents_config


def _write_agents_json(path, model_value: str) -> None:
    payload = {
        "default_backend": "local",
        "backends": {"local": {"type": "ollama", "base_url": "http://x/v1"}},
        "agents": {
            "main": {
                "model": model_value,
                "temperature": 0.2,
                "backend": "local",
                "max_turns": 4,
            }
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_env_placeholder_resolved(tmp_path, monkeypatch):
    monkeypatch.setenv("DEFAULT_MID", "ollama-x:7b")
    cfg_path = tmp_path / "agents.json"
    _write_agents_json(cfg_path, "${DEFAULT_MID}")

    cfg = load_agents_config(cfg_path)
    assert cfg.agents["main"].model == "ollama-x:7b"


def test_env_placeholder_missing_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("DEFAULT_MID", raising=False)
    cfg_path = tmp_path / "agents.json"
    _write_agents_json(cfg_path, "${DEFAULT_MID}")

    with pytest.raises(ValueError, match="DEFAULT_MID"):
        load_agents_config(cfg_path)


def test_literal_model_unchanged(tmp_path):
    cfg_path = tmp_path / "agents.json"
    _write_agents_json(cfg_path, "hardcoded:7b")

    cfg = load_agents_config(cfg_path)
    assert cfg.agents["main"].model == "hardcoded:7b"
