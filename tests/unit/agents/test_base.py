import os


def test_get_model_string_ollama_sets_base_url(monkeypatch):
    from src.agents.base import get_model_string
    from src.agents_config import BackendConfig

    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    cfg = BackendConfig(type="ollama", base_url="http://localhost:11434")
    ms = get_model_string(cfg, "gemma2:2b")
    assert ms == "ollama:gemma2:2b"
    assert os.environ["OLLAMA_BASE_URL"] == "http://localhost:11434"


def test_get_model_string_openrouter_sets_openai_env(monkeypatch):
    from src.agents.base import get_model_string
    from src.agents_config import BackendConfig

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "x")

    cfg = BackendConfig(type="openrouter", api_key_env="OPENROUTER_API_KEY")
    ms = get_model_string(cfg, "openai/gpt-4o-mini")
    assert ms == "openai:openai/gpt-4o-mini"
    assert os.environ["OPENAI_API_KEY"] == "x"
    assert os.environ["OPENAI_BASE_URL"] == "https://openrouter.ai/api/v1"
