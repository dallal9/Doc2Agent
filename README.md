# myagent

## Setup (Ollama)

1. Install Ollama: https://ollama.com/download

2. Pull a model:
```bash
ollama pull gemma2:2b
```

3. Install deps and run:
```bash
uv sync
uv run python src/scripts/run_model.py
```

Set `MODEL_NAME` env var to use a different model.
