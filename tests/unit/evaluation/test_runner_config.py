from src.evaluation.runner import _env_defaults, normalize_config


def test_env_defaults_reads_env(monkeypatch):
    monkeypatch.setenv("EVAL_CONCURRENCY", "8")
    monkeypatch.setenv("EVAL_MAX_SAMPLES", "50")
    monkeypatch.setenv("EVAL_SHUFFLE", "true")
    monkeypatch.setenv("EVAL_SEED", "7")
    monkeypatch.setenv("EVAL_CONTEXT_MODE", "spans_only")

    d = _env_defaults()
    assert d == {
        "concurrency": 8,
        "max_samples": 50,
        "shuffle": True,
        "seed": 7,
        "context_mode": "spans_only",
    }


def test_env_defaults_invalid_context_mode_falls_back(monkeypatch):
    monkeypatch.setenv("EVAL_CONTEXT_MODE", "bogus")
    assert _env_defaults()["context_mode"] == "full_doc"


def test_normalize_config_user_overrides_env_defaults(monkeypatch):
    monkeypatch.setenv("EVAL_CONCURRENCY", "8")
    cfg = normalize_config({"concurrency": 2})
    assert cfg["concurrency"] == 2


def test_normalize_config_uses_env_when_user_omits(monkeypatch):
    monkeypatch.setenv("EVAL_CONCURRENCY", "4")
    monkeypatch.setenv("EVAL_SHUFFLE", "true")
    cfg = normalize_config(None)
    assert cfg["concurrency"] == 4
    assert cfg["shuffle"] is True


def test_normalize_config_clamps_concurrency_minimum(monkeypatch):
    monkeypatch.setenv("EVAL_CONCURRENCY", "0")
    cfg = normalize_config(None)
    assert cfg["concurrency"] == 1
