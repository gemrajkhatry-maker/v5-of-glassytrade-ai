"""Runtime mode must be resolved once and fail closed on ambiguity."""

import pytest

from app.shared.mode import is_live_mode, resolve_runtime_mode


def test_conflicting_mode_sources_are_rejected(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    monkeypatch.setenv("TRADING_MODE", "paper")

    with pytest.raises(ValueError, match="conflicting runtime modes"):
        resolve_runtime_mode()


def test_invalid_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "staging")
    monkeypatch.delenv("TRADING_MODE", raising=False)

    with pytest.raises(ValueError, match="unsupported runtime mode"):
        resolve_runtime_mode()


def test_is_live_mode_uses_validated_mode(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "paper")
    monkeypatch.setenv("TRADING_MODE", "paper")

    assert is_live_mode() is False
