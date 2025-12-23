from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.services.llm.server import app


@pytest.fixture
def client():
    return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@patch("src.services.llm.server.ollama")
def test_generate(mock_ollama, client):
    mock_ollama.generate.return_value = {
        "response": "Hello there!",
        "eval_count": 5,
    }
    resp = client.post("/generate", json={"prompt": "Hi"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["text"] == "Hello there!"
    assert data["tokens"] == 5
    assert "time_s" in data


@patch("src.services.llm.server.ollama")
def test_generate_custom_temp(mock_ollama, client):
    mock_ollama.generate.return_value = {"response": "Test", "eval_count": 1}
    client.post("/generate", json={"prompt": "Hi", "temperature": 0.9})
    mock_ollama.generate.assert_called_once()
    call_args = mock_ollama.generate.call_args
    assert call_args.kwargs["options"]["temperature"] == 0.9
