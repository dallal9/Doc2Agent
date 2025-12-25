import asyncio


class _DummyResult:
    def __init__(self, output: str):
        self.output = output


class _DummyAgent:
    def __init__(self, output_fn):
        self._output_fn = output_fn
        self.last_prompt = None

    async def run(self, prompt: str, deps=None):
        self.last_prompt = prompt
        return _DummyResult(self._output_fn(prompt, deps))


def test_parse_reviewer_ok():
    from src.chat.assistant import _parse_reviewer

    verdict, final, fixes = _parse_reviewer("VERDICT: OK\nFINAL: hello\n")
    assert verdict == "OK"
    assert final == "hello"
    assert fixes == []


def test_parse_reviewer_needs_work():
    from src.chat.assistant import _parse_reviewer

    verdict, final, fixes = _parse_reviewer(
        "VERDICT: NEEDS_WORK\nFIXES:\n- add citations\n- clarify scope\n"
    )
    assert verdict == "NEEDS_WORK"
    assert final == ""
    assert fixes[:2] == ["add citations", "clarify scope"]


def test_inline_full_text_in_prompt_when_small(monkeypatch):
    monkeypatch.setenv("INLINE_DOC_MAX_CHARS", "50")

    from src.chat import assistant as assistant_mod

    main = _DummyAgent(lambda prompt, deps: "draft")
    reviewer = _DummyAgent(lambda prompt, deps: "VERDICT: OK\nFINAL: ok")
    monkeypatch.setattr(assistant_mod, "create_main_agent", lambda *args, **kwargs: main)
    monkeypatch.setattr(assistant_mod, "create_reviewer_agent", lambda *args, **kwargs: reviewer)

    a = assistant_mod.ChatAssistant()
    a.set_text("short text")
    asyncio.run(a.chat("hi"))

    assert "Document text (full):" in main.last_prompt
    assert "short text" in main.last_prompt


def test_inline_truncated_text_in_prompt_when_large(monkeypatch):
    monkeypatch.setenv("INLINE_DOC_MAX_CHARS", "10")

    from src.chat import assistant as assistant_mod

    main = _DummyAgent(lambda prompt, deps: "draft")
    reviewer = _DummyAgent(lambda prompt, deps: "VERDICT: OK\nFINAL: ok")
    monkeypatch.setattr(assistant_mod, "create_main_agent", lambda *args, **kwargs: main)
    monkeypatch.setattr(assistant_mod, "create_reviewer_agent", lambda *args, **kwargs: reviewer)

    a = assistant_mod.ChatAssistant()
    a.set_text("0123456789ABCDEFGHIJ")
    asyncio.run(a.chat("hi"))

    assert "Document text (truncated):" in main.last_prompt
    assert "0123456789" in main.last_prompt
    assert "ABCDEFGHIJ" not in main.last_prompt
