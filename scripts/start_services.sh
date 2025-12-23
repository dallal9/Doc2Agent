#!/bin/bash
set -e

cd "$(dirname "$0")/.."

# Load env
if [ -f .env ]; then
    set -a
    source .env
    set +a
fi

LLM_PORT=${LLM_PORT:-8001}
TRANSLATION_PORT=${TRANSLATION_PORT:-8002}

usage() {
    echo "Usage: $0 [service...]"
    echo ""
    echo "Services:"
    echo "  llm          LLM service (port $LLM_PORT)"
    echo "  translation  Translation service (port $TRANSLATION_PORT)"
    echo ""
    echo "If no service specified, starts all services."
    exit 0
}

start_llm() {
    echo "Starting LLM service on port $LLM_PORT..."
    uv run uvicorn src.services.llm.server:app --host 0.0.0.0 --port "$LLM_PORT" &
}

start_translation() {
    echo "Starting Translation service on port $TRANSLATION_PORT..."
    uv run uvicorn src.services.translation.server:app --host 0.0.0.0 --port "$TRANSLATION_PORT" &
}

# Show help
[[ "$1" == "-h" || "$1" == "--help" ]] && usage

# No args = start all
if [ $# -eq 0 ]; then
    start_llm
    start_translation
else
    for svc in "$@"; do
        case "$svc" in
            llm) start_llm ;;
            translation) start_translation ;;
            *) echo "Unknown service: $svc"; usage ;;
        esac
    done
fi

wait
