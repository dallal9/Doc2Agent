import asyncio
import json

import httpx
import pytest


def test_build_model_ollama(monkeypatch):
    from src.agents.base import build_model
    from src.agents_config import BackendConfig

    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    cfg = BackendConfig(type="ollama", base_url="http://localhost:11434/v1")
    model = build_model(cfg, "gemma2:2b")
    assert model.model_name == "gemma2:2b"
    assert "ollama" in str(model.base_url) or "11434" in str(model.base_url)


def test_build_model_openrouter(monkeypatch):
    from src.agents.base import build_model
    from src.agents_config import BackendConfig

    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    cfg = BackendConfig(type="openrouter", api_key_env="OPENROUTER_API_KEY")
    model = build_model(cfg, "openai/gpt-4o-mini")
    assert model.model_name == "openai/gpt-4o-mini"
    assert "openrouter.ai" in str(model.base_url)


def test_build_model_openrouter_missing_key(monkeypatch):
    from src.agents.base import build_model
    from src.agents_config import BackendConfig

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    cfg = BackendConfig(type="openrouter", api_key_env="OPENROUTER_API_KEY")
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        build_model(cfg, "openai/gpt-4o-mini")


def test_coerce_null_assistant_content_replaces_null():
    from src.agents.base import _coerce_null_assistant_content

    body = {
        "messages": [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": None},
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [{"id": "x", "type": "function"}],
            },
        ]
    }
    raw = json.dumps(body).encode("utf-8")
    req = httpx.Request(
        "POST",
        "http://localhost:11434/v1/chat/completions",
        content=raw,
        headers={"content-type": "application/json"},
    )
    asyncio.run(_coerce_null_assistant_content(req))

    patched = json.loads(req.content)
    # Bare null-content assistant gets coerced to empty string.
    assert patched["messages"][2]["content"] == ""
    # Assistant with tool_calls is left alone (null content is valid there).
    assert patched["messages"][3]["content"] is None
    assert req.headers["content-length"] == str(len(req.content))


def test_coerce_null_assistant_content_skips_non_chat_endpoints():
    from src.agents.base import _coerce_null_assistant_content

    body = {"messages": [{"role": "assistant", "content": None}]}
    raw = json.dumps(body).encode("utf-8")
    req = httpx.Request("GET", "http://localhost:11434/v1/models", content=raw)
    asyncio.run(_coerce_null_assistant_content(req))
    assert json.loads(req.content)["messages"][0]["content"] is None


def test_is_retriable_classifies_correctly():
    from pydantic_ai.exceptions import ModelHTTPError

    from src.agents.base import _is_retriable

    assert _is_retriable(ModelHTTPError(status_code=503, model_name="m", body=None))
    assert _is_retriable(ModelHTTPError(status_code=429, model_name="m", body=None))
    assert not _is_retriable(ModelHTTPError(status_code=400, model_name="m", body=None))
    assert not _is_retriable(ModelHTTPError(status_code=401, model_name="m", body=None))
    assert _is_retriable(httpx.ConnectTimeout("timeout"))
    assert not _is_retriable(ValueError("nope"))


def test_run_agent_retries_on_transient_then_succeeds(monkeypatch):
    from pydantic_ai.exceptions import ModelHTTPError

    from src.agents import base as base_mod

    monkeypatch.setenv("LLM_MAX_RETRIES", "2")
    monkeypatch.setenv("LLM_RETRY_BACKOFF_S", "0")

    calls = {"n": 0}

    class FakeUsage:
        input_tokens = 1
        output_tokens = 1

    class FakeResult:
        output = "ok"

        def usage(self):
            return FakeUsage()

    class FakeAgent:
        async def run(self, prompt):
            calls["n"] += 1
            if calls["n"] < 3:
                raise ModelHTTPError(status_code=503, model_name="m", body=None)
            return FakeResult()

    result = asyncio.run(base_mod.run_agent(FakeAgent(), "hi"))
    assert calls["n"] == 3
    assert result.output == "ok"


def test_run_agent_does_not_retry_400(monkeypatch):
    from pydantic_ai.exceptions import ModelHTTPError

    from src.agents import base as base_mod

    monkeypatch.setenv("LLM_MAX_RETRIES", "5")
    monkeypatch.setenv("LLM_RETRY_BACKOFF_S", "0")

    calls = {"n": 0}

    class FakeAgent:
        async def run(self, prompt):
            calls["n"] += 1
            raise ModelHTTPError(status_code=400, model_name="m", body=None)

    with pytest.raises(ModelHTTPError):
        asyncio.run(base_mod.run_agent(FakeAgent(), "hi"))
    assert calls["n"] == 1
