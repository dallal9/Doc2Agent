from unittest.mock import MagicMock

from src.agents.tooling import (
    register_database_tools,
    register_extraction_tools,
    register_reader_tools,
)


def test_register_reader_tools():
    mock_agent = MagicMock()
    register_reader_tools(mock_agent)
    assert mock_agent.tool.call_count >= 3


def test_register_extraction_tools():
    mock_agent = MagicMock()
    register_extraction_tools(mock_agent)
    assert mock_agent.tool.called


def test_register_database_tools():
    mock_agent = MagicMock()
    register_database_tools(mock_agent)
    assert mock_agent.tool.call_count >= 3
