import src.bootstrap as bootstrap_mod


def test_init_app_is_idempotent():
    """init_app should only run once."""
    bootstrap_mod._initialized = False
    bootstrap_mod.init_app()
    assert bootstrap_mod._initialized is True

    # Second call should not error
    bootstrap_mod.init_app()
    assert bootstrap_mod._initialized is True


def test_init_app_works_without_env_file(monkeypatch, tmp_path):
    """init_app should work when no .env file exists."""
    monkeypatch.chdir(tmp_path)
    bootstrap_mod._initialized = False
    bootstrap_mod.init_app()
    assert bootstrap_mod._initialized is True
