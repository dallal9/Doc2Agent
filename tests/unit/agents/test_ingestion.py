import asyncio
from unittest.mock import MagicMock, patch

from src.agents.ingestion import create_ingestion_agent, ingest_page
from src.agents_config import AgentsConfigFile, BackendConfig, PromptsConfigFile
from src.schemas import PageSchema


def test_create_ingestion_agent():
    agents_config = AgentsConfigFile(
        default_backend="local",
        backends={"local": BackendConfig(type="ollama", base_url="http://localhost:11434/v1")},
        agents={
            "ingestion": {
                "model": "test-model",
                "backend": "local",
                "temperature": 0.0,
            }
        },
    )
    prompts = PromptsConfigFile(
        main="Main prompt",
        reviewer="Reviewer prompt",
        validator="Validator prompt",
        ingestion="Ingestion prompt",
    )
    with patch("src.agents.ingestion.create_agent") as mock_create:
        mock_agent = MagicMock()
        mock_create.return_value = mock_agent
        agent = create_ingestion_agent(agents_config, prompts)
        mock_create.assert_called_once()
        assert agent == mock_agent


def test_ingest_page():
    mock_agent = MagicMock()
    mock_result = MagicMock()
    mock_result.output = PageSchema(
        page_num=1,
        char_count=100,
        word_count=20,
        has_tables=False,
        has_images=False,
        text="Test page",
    )
    with patch("src.agents.ingestion.run_agent", return_value=mock_result):
        page_input = {
            "page_num": 1,
            "char_count": 100,
            "word_count": 20,
            "has_tables": False,
            "has_images": False,
            "text": "Test page",
        }
        result = asyncio.run(ingest_page(mock_agent, page_input))
        assert isinstance(result, PageSchema)
        assert result.page_num == 1
