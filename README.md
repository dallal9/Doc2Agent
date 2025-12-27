# myagent

PDF assistant with multi-agent architecture for document ingestion and querying.

## Setup

1. Install Ollama: https://ollama.com/download

2. Pull models:
```bash
ollama pull ministral-3:3b
ollama pull deepseek-r1:8b
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

- Upload a PDF via the UI to load and ingest
- Ask questions about the document
- Use `/reset` to clear chat

## Features

- **PDF Ingestion**: PyMuPDF-based parser with LLM enrichment (names, dates, headings, keywords)
- **SQLite Storage**: Large documents stored in SQLite with full-text search
- **Multi-Agent System**: Main agent, reviewer, validator, and ingestion agents
- **Personal Info Validation**: Compare document data against user-provided info

## Configure (env)

- **Local (Ollama)**: `OLLAMA_BASE_URL` (defaults to `http://localhost:11434/v1`)
- **Cloud (OpenRouter)**: set `OPENROUTER_API_KEY` and switch backend in `agents.json`
- **Personal info**: `PERSONAL_INFO_JSON='{"name":"...","email":"..."}'`
- **PDF ingestion**:
  - `PDF_JSON_MAX_BYTES=2000000` - max file size for JSON storage
  - `PDF_SQLITE_DIR=data` - Directory for SQLite database files
  - `PDF_STORAGE_DIR=data/pdfs` - Directory for permanent PDF file storage
- **Inline context**: `INLINE_DOC_MAX_CHARS=20000`
- **Reasoning traces**: `SHOW_REASONING=true` - displays `<think>` tags
- **Logging**: `LOG_LEVEL`, `LOG_FILE`, `LOG_TO_FILE`
- **Query caching**:
  - `QUERY_CACHE_ENABLED=true` - Enable/disable query caching (default: true)
  - `QUERY_CACHE_MAX_PER_FILE=10` - Max cached queries per document (default: 10)
  - Cached queries are automatically deleted when documents are removed
  - Use "Flush Cache" button in UI to clear cached queries

## Development

```bash
make lint       # Format code
make lint-check # Check formatting
make test       # Run tests
```
