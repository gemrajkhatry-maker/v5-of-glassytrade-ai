from pathlib import Path

from app.config_models import settings_adapter


def test_settings_adapter_does_not_load_user_dotenv_in_hermetic_mode(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_HERMETIC", "1")
    loaded = []
    real_exists = Path.exists

    def fake_exists(path):
        if path.name == ".env":
            return True
        return real_exists(path)

    monkeypatch.setattr(settings_adapter.Path, "exists", fake_exists)
    monkeypatch.setattr(settings_adapter, "load_dotenv", lambda *args, **kwargs: loaded.append((args, kwargs)))

    settings_adapter.SettingsAdapter()

    assert loaded == []
