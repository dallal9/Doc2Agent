# myagent

## Setup

1. Install Ollama: https://ollama.com/download

2. Pull a model:
```bash
ollama pull ministral-3:3b
```

3. Install deps:
```bash
uv sync
```

4. Configure:
```bash
cp env.example .env
```

## Run Chat

**Web UI (Chainlit):**
```bash
uv run chainlit run app/chainlit_app.py
```

**CLI:**
```bash
uv run python app/cli.py
```

- Load a PDF: `/load /path/to/file.pdf`
- Paste text: `/text`
- Clear chat: `/reset`

## Configure (env)

- **Local (Ollama)**: `OLLAMA_BASE_URL` (defaults to `http://localhost:11434/v1`)
- **Cloud (OpenRouter)**: set `OPENROUTER_API_KEY` and switch agent backend to `openrouter` in `src/agents_config/agents.json`
- **Personal info** (optional): `PERSONAL_INFO_JSON='{"name":"...","email":"..."}'`
- **Inline document context** (optional): `INLINE_DOC_MAX_CHARS=20000` (when the loaded text is small, the full text is inlined into the prompt)

Note: `env.example` is the canonical template in this repo. If you have a `.env.example` locally, treat it as legacy.

## Development

```bash
make lint       # Format code
make lint-check # Check formatting
make test       # Run tests
```
