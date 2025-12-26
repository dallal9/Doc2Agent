import asyncio


class _DummyUsage:
    def __init__(self, input_tokens: int = 0, output_tokens: int = 0):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _DummyResult:
    def __init__(self, output: str):
        self.output = output

    def usage(self):
        return _DummyUsage()


class _DummyAgent:
    def __init__(self, output_fn):
        self._output_fn = output_fn
        self.last_prompt = None

    async def run(self, prompt: str, deps=None):
        self.last_prompt = prompt
        return _DummyResult(self._output_fn(prompt, deps))


def test_inline_full_text_in_prompt_when_small(monkeypatch):
    monkeypatch.setenv("INLINE_DOC_MAX_CHARS", "50")

    from src.chat import assistant as assistant_mod

    main = _DummyAgent(lambda prompt, deps: "draft")
    monkeypatch.setattr(assistant_mod, "create_main_agent", lambda *args, **kwargs: main)

    a = assistant_mod.ChatAssistant()
    a.set_text("short text")
    asyncio.run(a.chat("hi"))

    assert "Document text (full):" in main.last_prompt
    assert "short text" in main.last_prompt


def test_inline_truncated_text_in_prompt_when_large(monkeypatch):
    monkeypatch.setenv("INLINE_DOC_MAX_CHARS", "10")

    from src.chat import assistant as assistant_mod

    main = _DummyAgent(lambda prompt, deps: "draft")
    monkeypatch.setattr(assistant_mod, "create_main_agent", lambda *args, **kwargs: main)

    a = assistant_mod.ChatAssistant()
    a.set_text("0123456789ABCDEFGHIJ")
    asyncio.run(a.chat("hi"))

    assert "Document text (truncated):" in main.last_prompt
    assert "0123456789" in main.last_prompt
    assert "ABCDEFGHIJ" not in main.last_prompt


def test_chat_returns_main_output(monkeypatch):
    from src.chat import assistant as assistant_mod

    main = _DummyAgent(lambda prompt, deps: "hello world")
    monkeypatch.setattr(assistant_mod, "create_main_agent", lambda *args, **kwargs: main)

    a = assistant_mod.ChatAssistant()
    reply = asyncio.run(a.chat("hi"))

    assert reply == "hello world"
