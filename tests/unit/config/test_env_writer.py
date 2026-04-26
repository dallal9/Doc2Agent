from pathlib import Path

from src.config.env_writer import write_env


def _read(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8").splitlines()


def test_write_env_replaces_existing_key_in_place(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# Header\nFOO=old\nBAR=keep\n# trailing\n",
        encoding="utf-8",
    )
    write_env({"FOO": "new"}, env_path=env, example_path=tmp_path / "missing.example")
    lines = _read(env)
    assert lines[0] == "# Header"
    assert lines[1] == "FOO=new"
    assert lines[2] == "BAR=keep"
    assert lines[3] == "# trailing"


def test_write_env_uncomments_when_setting_value(tmp_path):
    env = tmp_path / ".env"
    env.write_text("# FOO=\n", encoding="utf-8")
    write_env({"FOO": "abc"}, env_path=env)
    assert _read(env) == ["FOO=abc"]


def test_write_env_comments_out_empty_value(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=abc\n", encoding="utf-8")
    write_env({"FOO": ""}, env_path=env)
    assert _read(env) == ["# FOO="]


def test_write_env_appends_unknown_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=abc\n", encoding="utf-8")
    write_env({"NEW_KEY": "v"}, env_path=env)
    lines = _read(env)
    assert lines[0] == "FOO=abc"
    assert "NEW_KEY=v" in lines


def test_write_env_quotes_values_with_spaces_or_hash(tmp_path):
    env = tmp_path / ".env"
    env.write_text("FOO=\nBAR=\n", encoding="utf-8")
    write_env({"FOO": "hello world", "BAR": "abc#def"}, env_path=env)
    text = env.read_text(encoding="utf-8")
    assert 'FOO="hello world"' in text
    assert 'BAR="abc#def"' in text


def test_write_env_seeds_from_example_when_missing(tmp_path):
    env = tmp_path / ".env"
    example = tmp_path / "env.example"
    example.write_text("FOO=fromexample\n", encoding="utf-8")
    write_env({"FOO": "new"}, env_path=env, example_path=example)
    assert env.exists()
    assert _read(env) == ["FOO=new"]
