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


def _enriched_doc(n_pages: int):
    from src.schemas.document import DocumentMetadata, DocumentSchema, PageSchema

    pages = [
        PageSchema(
            page_num=i + 1,
            char_count=10,
            word_count=2,
            has_tables=False,
            has_images=False,
            text=f"page {i + 1} body",
        )
        for i in range(n_pages)
    ]
    meta = DocumentMetadata(
        doc_id="d",
        file_path="/tmp/d.pdf",
        file_name="d.pdf",
        file_size_bytes=10,
        page_count=n_pages,
    )
    return DocumentSchema(metadata=meta, pages=pages)


def test_inline_pages_when_doc_within_page_limit(monkeypatch):
    monkeypatch.setenv("INLINE_DOC_MAX_PAGES", "3")

    from src.chat import assistant as assistant_mod

    main = _DummyAgent(lambda prompt, deps: "draft")
    monkeypatch.setattr(assistant_mod, "create_main_agent", lambda *args, **kwargs: main)

    a = assistant_mod.ChatAssistant()
    a.enriched_doc = _enriched_doc(2)
    asyncio.run(a.chat("hi"))

    assert "Document pages:" in main.last_prompt
    assert "[Page 1] page 1 body" in main.last_prompt
    assert "[Page 2] page 2 body" in main.last_prompt
    assert "Document overview" not in main.last_prompt


def test_manifest_when_doc_exceeds_page_limit(monkeypatch):
    monkeypatch.setenv("INLINE_DOC_MAX_PAGES", "3")

    from src.chat import assistant as assistant_mod

    main = _DummyAgent(lambda prompt, deps: "draft")
    monkeypatch.setattr(assistant_mod, "create_main_agent", lambda *args, **kwargs: main)

    a = assistant_mod.ChatAssistant()
    a.enriched_doc = _enriched_doc(5)
    asyncio.run(a.chat("hi"))

    assert "Document overview (5 pages" in main.last_prompt
    # Manifest lists each page by number, not full body
    assert "Page 1:" in main.last_prompt
    assert "Page 5:" in main.last_prompt
    assert "Document pages:" not in main.last_prompt


def test_manifest_fallback_when_only_raw_text(monkeypatch):
    from src.chat import assistant as assistant_mod

    main = _DummyAgent(lambda prompt, deps: "draft")
    monkeypatch.setattr(assistant_mod, "create_main_agent", lambda *args, **kwargs: main)

    a = assistant_mod.ChatAssistant()
    a.set_text("0123456789ABCDEFGHIJ")
    asyncio.run(a.chat("hi"))

    assert "Use the available tools" in main.last_prompt
    assert "Document pages:" not in main.last_prompt


def test_chat_returns_main_output(monkeypatch):
    from src.chat import assistant as assistant_mod

    main = _DummyAgent(lambda prompt, deps: "hello world")
    monkeypatch.setattr(assistant_mod, "create_main_agent", lambda *args, **kwargs: main)

    a = assistant_mod.ChatAssistant()
    reply = asyncio.run(a.chat("hi"))

    assert reply == "hello world"
