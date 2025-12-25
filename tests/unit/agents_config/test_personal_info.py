import os


def test_personal_info_from_env(monkeypatch):
    monkeypatch.setenv("PERSONAL_INFO_JSON", '{"name":"Abdelrhman","email":"a@b.com"}')

    from src.agents_config import load_personal_info

    pi = load_personal_info()
    assert pi.data["name"] == "Abdelrhman"
    assert pi.data["email"] == "a@b.com"


def test_personal_info_prompt_context_empty():
    from src.agents_config.schemas import PersonalInfo

    assert PersonalInfo(data={}).to_prompt_context() == ""


def test_personal_info_prompt_context_content():
    from src.agents_config.schemas import PersonalInfo

    pi = PersonalInfo(data={"name": "Abdelrhman", "company": "Acme"})
    ctx = pi.to_prompt_context()
    assert "User's personal information:" in ctx
    assert "- name: Abdelrhman" in ctx
    assert "- company: Acme" in ctx
