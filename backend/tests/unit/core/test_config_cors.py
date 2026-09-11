"""CORS origin settings parsing (backend/app/core/config.py)."""

import pytest

from backend.app.core.config import Settings


@pytest.mark.unit
class TestCorsOriginsSettings:
    def test_comma_separated_env_value_is_split(self, monkeypatch):
        """The documented `.env.example` form must not crash settings parsing."""
        monkeypatch.setenv(
            "CORS_ORIGINS", "http://localhost:3100, http://localhost:3200"
        )
        settings = Settings(_env_file=None)
        assert settings.CORS_ORIGINS == [
            "http://localhost:3100",
            "http://localhost:3200",
        ]

    def test_empty_env_value_yields_empty_list(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", "")
        settings = Settings(_env_file=None)
        assert settings.CORS_ORIGINS == []

    def test_dev_settings_env_override_is_split_too(self, monkeypatch):
        """DevSettings redefines the field; the NoDecode annotation must survive."""
        from backend.app.core.config import DevSettings

        monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3200")
        settings = DevSettings(_env_file=None)
        assert settings.CORS_ORIGINS == ["http://localhost:3200"]

    def test_dev_settings_default_allows_shoplab_port(self):
        from backend.app.core.config import DevSettings

        assert "http://localhost:3200" in DevSettings(_env_file=None).CORS_ORIGINS

    def test_json_list_is_still_accepted(self, monkeypatch):
        monkeypatch.setenv("CORS_ORIGINS", '["http://a.example", "http://b.example"]')
        settings = Settings(_env_file=None)
        assert settings.CORS_ORIGINS == ["http://a.example", "http://b.example"]
