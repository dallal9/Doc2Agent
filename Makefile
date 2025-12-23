.PHONY: lint lint-check test

lint:
	uv run black . --line-length 100
	uv run isort . --profile black

lint-check:
	uv run black --check . --line-length 100
	uv run isort --check-only . --profile black

test:
	uv run pytest

