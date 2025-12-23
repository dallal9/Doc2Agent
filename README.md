# myagent

## Setup

1. Install Ollama: https://ollama.com/download

2. Pull a model:
```bash
ollama pull gemma2:2b
```

3. Install deps:
```bash
uv sync
```

4. Configure:
```bash
cp env.example .env
```

## Run Services

```bash
./scripts/start_services.sh           # Start all
./scripts/start_services.sh llm       # LLM only
./scripts/start_services.sh -h        # Help
```

## Example

```bash
# Terminal 1: Start LLM service
./scripts/start_services.sh llm

# Terminal 2: Run example client
uv run python src/scripts/example_llm_client.py
```

## Development

```bash
make lint       # Format code
make lint-check # Check formatting
make test       # Run tests
```
