from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    with (
        patch("src.services.translation.server.M2M100Tokenizer") as mock_tok,
        patch("src.services.translation.server.M2M100ForConditionalGeneration") as mock_model,
    ):
        mock_tok.from_pretrained.return_value = MagicMock()
        mock_model.from_pretrained.return_value.to.return_value = MagicMock()

        from src.services.translation.server import app

        return TestClient(app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@patch("src.services.translation.server.tokenizer")
@patch("src.services.translation.server.model")
def test_translate(mock_model, mock_tokenizer):
    mock_tokenizer.return_value.to.return_value = {"input_ids": MagicMock()}
    mock_tokenizer.get_lang_id.return_value = 1
    mock_tokenizer.decode.return_value = "Hallo"
    mock_model.generate.return_value = [MagicMock()]

    with (
        patch("src.services.translation.server.M2M100Tokenizer"),
        patch("src.services.translation.server.M2M100ForConditionalGeneration"),
    ):
        from src.services.translation.server import app

        client = TestClient(app)
        resp = client.post(
            "/translate", json={"text": "Hello", "source_lang": "en", "target_lang": "de"}
        )
        assert resp.status_code == 200
