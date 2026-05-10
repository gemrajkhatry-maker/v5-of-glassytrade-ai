"""Tests for unified config loader.

Characterization tests for config loading before consolidation.
"""
from __future__ import annotations

from pathlib import Path

from app.infrastructure.config.loader import (
    _deep_merge,
    _read_yaml,
    resolve_environment,
    load_settings_from_yaml,
)


class TestDeepMerge:
    """Tests for _deep_merge utility."""

    def test_merge_flat_dicts(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 3, "c": 4}

    def test_merge_nested_dicts(self):
        base = {"a": {"x": 1, "y": 2}, "b": 3}
        override = {"a": {"y": 20, "z": 30}}
        result = _deep_merge(base, override)
        assert result == {"a": {"x": 1, "y": 20, "z": 30}, "b": 3}

    def test_merge_empty_override(self):
        base = {"a": 1}
        result = _deep_merge(base, {})
        assert result == {"a": 1}

    def test_merge_empty_base(self):
        override = {"a": 1}
        result = _deep_merge({}, override)
        assert result == {"a": 1}

    def test_merge_does_not_mutate_base(self):
        base = {"a": {"x": 1}}
        override = {"a": {"y": 2}}
        result = _deep_merge(base, override)
        assert base == {"a": {"x": 1}}  # Base unchanged
        assert result == {"a": {"x": 1, "y": 2}}


class TestReadYaml:
    """Tests for _read_yaml utility."""

    def test_reads_valid_yaml(self, tmp_path):
        yaml_file = tmp_path / "test.yaml"
        yaml_file.write_text("key: value\nnested:\n  sub: 42\n")
        result = _read_yaml(yaml_file)
        assert result == {"key": "value", "nested": {"sub": 42}}

    def test_returns_empty_for_missing_file(self, tmp_path):
        result = _read_yaml(tmp_path / "missing.yaml")
        assert result == {}

    def test_returns_empty_for_invalid_yaml(self, tmp_path):
        yaml_file = tmp_path / "bad.yaml"
        yaml_file.write_text("not valid yaml: [")
        result = _read_yaml(yaml_file)
        assert result == {}

    def test_returns_empty_for_non_dict_yaml(self, tmp_path):
        yaml_file = tmp_path / "list.yaml"
        yaml_file.write_text("- item1\n- item2\n")
        result = _read_yaml(yaml_file)
        assert result == {}


class TestResolveEnvironment:
    """Tests for resolve_environment utility."""

    def test_defaults_to_development(self, monkeypatch):
        monkeypatch.delenv("GLASSYTRADE_ENV", raising=False)
        assert resolve_environment() == "development"

    def test_respects_env_var(self, monkeypatch):
        monkeypatch.setenv("GLASSYTRADE_ENV", "live")
        assert resolve_environment() == "live"

    def test_aliases_dev_to_development(self, monkeypatch):
        monkeypatch.setenv("GLASSYTRADE_ENV", "dev")
        assert resolve_environment() == "development"

    def test_aliases_prod_to_production(self, monkeypatch):
        monkeypatch.setenv("GLASSYTRADE_ENV", "prod")
        assert resolve_environment() == "production"

    def test_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("GLASSYTRADE_ENV", "LIVE")
        assert resolve_environment() == "live"

    def test_unknown_fallback(self, monkeypatch):
        monkeypatch.setenv("GLASSYTRADE_ENV", "staging")
        assert resolve_environment() == "development"


class TestLoadSettingsFromYaml:
    """Tests for load_settings_from_yaml."""

    def test_loads_base_and_env(self, tmp_path):
        base = tmp_path / "base.yaml"
        base.write_text("app:\n  name: test\n  version: 1\n")
        
        env_dir = tmp_path / "environments"
        env_dir.mkdir()
        dev = env_dir / "development.yaml"
        dev.write_text("app:\n  version: 2\n  debug: true\n")
        
        result = load_settings_from_yaml(tmp_path, env="development")
        assert result["app"]["name"] == "test"      # From base
        assert result["app"]["version"] == 2        # Overridden
        assert result["app"]["debug"] is True        # From env

    def test_missing_env_file_uses_base_only(self, tmp_path):
        base = tmp_path / "base.yaml"
        base.write_text("app:\n  name: test\n")
        
        result = load_settings_from_yaml(tmp_path, env="missing")
        assert result == {"app": {"name": "test"}}

    def test_missing_base_file_returns_env_only(self, tmp_path):
        env_dir = tmp_path / "environments"
        env_dir.mkdir()
        dev = env_dir / "development.yaml"
        dev.write_text("app:\n  debug: true\n")
        
        result = load_settings_from_yaml(tmp_path, env="development")
        assert result == {"app": {"debug": True}}
