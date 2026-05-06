"""Unit tests for scanner-related configuration loading."""
from __future__ import annotations

from pathlib import Path

import yaml

from app.infrastructure.config import AppSettings, settings
from app.api.routers.health import _load_active_symbols


def _write_yaml(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(payload, fh)


def test_scanner_settings_load_from_yaml(tmp_path, monkeypatch):
    base = tmp_path / "base.yaml"
    env = tmp_path / "environments" / "development.yaml"
    _write_yaml(base, {"scanner": {"top_n": 4}, "exchanges": {"NSE": {"symbols": {"NIFTY": {}}}}})
    _write_yaml(env, {})

    monkeypatch.setattr(settings, "_CONFIG_DIR", tmp_path)
    loaded = AppSettings.from_yaml_file(profile="development")
    assert loaded.scanner is not None
    assert loaded.scanner.top_n == 4


def test_active_symbols_reads_from_enabled_exchange_symbols(tmp_path, monkeypatch):
    base = tmp_path / "base.yaml"
    env = tmp_path / "environments" / "development.yaml"
    _write_yaml(
        base,
        {
            "exchanges": {
                "NSE": {
                    "enabled": True,
                    "symbols": {
                        "NIFTY": {},
                        "BANKNIFTY": {"enabled": False},
                        "FINNIFTY": {},
                    },
                },
                "MCX": {"enabled": False, "symbols": {"CRUDEOIL": {}}},
            }
        },
    )
    _write_yaml(env, {})
    monkeypatch.setattr(settings, "_CONFIG_DIR", tmp_path)
    symbols, exchange = _load_active_symbols(profile="development")
    assert exchange == "NSE"
    assert symbols == ["NIFTY", "FINNIFTY"]
