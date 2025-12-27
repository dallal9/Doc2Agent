from unittest.mock import MagicMock, patch

from src.agents.main import MainDeps, create_main_agent
from src.agents_config import AgentsConfigFile, BackendConfig, PersonalInfo, PromptsConfigFile
from src.schemas import StructuredDocument


def test_main_deps_initialization():
    deps = MainDeps(
        document=None,
        text="test text",
        personal_info=None,
        document_id="doc1",
        store=None,
    )
    assert deps.text == "test text"
    assert deps.document_id == "doc1"
    assert deps.document is None
    assert deps.personal_info is None
    assert deps.store is None


def test_main_deps_with_all_fields():
    doc = StructuredDocument(pages=[], sections=[], citable_spans=[])
    personal_info = PersonalInfo(data={"name": "Test"})
    deps = MainDeps(
        document=doc,
        text="full text",
        personal_info=personal_info,
        document_id="doc2",
        store=None,
    )
    assert deps.document == doc
    assert deps.personal_info == personal_info


def test_create_main_agent():
    agents_config = AgentsConfigFile(
        default_backend="local",
        backends={"local": BackendConfig(type="ollama", base_url="http://localhost:11434/v1")},
        agents={
            "main": {
                "model": "test-model",
                "backend": "local",
                "temperature": 0.2,
            },
            "reviewer": {
                "model": "test-model",
                "backend": "local",
                "temperature": 0.1,
            },
            "validator": {
                "model": "test-model",
                "backend": "local",
                "temperature": 0.1,
            },
        },
    )
    prompts = PromptsConfigFile(
        main="Main prompt",
        reviewer="Reviewer prompt",
        validator="Validator prompt",
        ingestion="Ingestion prompt",
    )
    with (
        patch("src.agents.main.create_agent") as mock_create,
        patch("src.agents.main.create_reviewer_agent") as mock_reviewer,
        patch("src.agents.main.register_reader_tools"),
        patch("src.agents.main.register_extraction_tools"),
        patch("src.agents.main.register_database_tools"),
    ):
        mock_agent = MagicMock()
        mock_reviewer_agent = MagicMock()
        mock_create.return_value = mock_agent
        mock_reviewer.return_value = mock_reviewer_agent
        agent = create_main_agent(agents_config, prompts)
        assert agent == mock_agent
