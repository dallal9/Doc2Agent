#!/bin/bash
set -e

cd "$(dirname "$0")/.."

# Load env
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

LLM_PORT=${LLM_PORT:-8001}
TRANSLATION_PORT=${TRANSLATION_PORT:-8002}

echo "Starting LLM service on port $LLM_PORT..."
uv run uvicorn src.services.llm.server:app --host 0.0.0.0 --port "$LLM_PORT" &

echo "Starting Translation service on port $TRANSLATION_PORT..."
uv run uvicorn src.services.translation.server:app --host 0.0.0.0 --port "$TRANSLATION_PORT" &

wait
