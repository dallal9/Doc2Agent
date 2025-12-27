from unittest.mock import MagicMock, patch

from src.agents.reviewer import create_reviewer_agent
from src.agents_config import AgentsConfigFile, BackendConfig, PromptsConfigFile


def test_create_reviewer_agent():
    agents_config = AgentsConfigFile(
        default_backend="local",
        backends={"local": BackendConfig(type="ollama", base_url="http://localhost:11434/v1")},
        agents={
            "reviewer": {
                "model": "test-model",
                "backend": "local",
                "temperature": 0.1,
            }
        },
    )
    prompts = PromptsConfigFile(
        main="Main prompt",
        reviewer="Reviewer prompt",
        validator="Validator prompt",
        ingestion="Ingestion prompt",
    )
    with patch("src.agents.reviewer.create_agent") as mock_create:
        mock_agent = MagicMock()
        mock_create.return_value = mock_agent
        agent = create_reviewer_agent(agents_config, prompts)
        mock_create.assert_called_once()
        assert agent == mock_agent
