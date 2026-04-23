from orchestrator.config import Settings


def test_settings_do_not_require_keys_at_import_time():
    settings = Settings()

    assert settings.anthropic_api_key is None
    assert settings.openai_api_key is None
    assert settings.codex_model
