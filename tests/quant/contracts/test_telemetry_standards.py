# tests/quant/contracts/test_telemetry_standards.py
import pytest
from brokers.broker.dhan.application.config import DhanConfig
from brokers.broker.dhan.domain.errors import DhanConfigError, DhanError, DhanMissingConfigError


def test_missing_client_id_typed(monkeypatch):
    monkeypatch.delenv("TESTDHAN_CLIENT_ID", raising=False)
    monkeypatch.setenv("TESTDHAN_ACCESS_TOKEN", "tok")
    with pytest.raises(DhanMissingConfigError):
        DhanConfig.from_env(prefix="TESTDHAN_")


def test_missing_token_without_totp_typed(monkeypatch):
    monkeypatch.setenv("TESTDHAN_CLIENT_ID", "cid")
    monkeypatch.delenv("TESTDHAN_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("TESTDHAN_TOTP_SECRET", raising=False)
    monkeypatch.delenv("TOTP_SECRET", raising=False)
    monkeypatch.delenv("TESTDHAN_PIN", raising=False)
    monkeypatch.delenv("PIN", raising=False)
    with pytest.raises(DhanMissingConfigError):
        DhanConfig.from_env(prefix="TESTDHAN_")


def test_bad_numeric_typed(monkeypatch):
    monkeypatch.setenv("TESTDHAN_CLIENT_ID", "cid")
    monkeypatch.setenv("TESTDHAN_ACCESS_TOKEN", "tok")
    monkeypatch.setenv("TESTDHAN_TIMEOUT", "not-a-number")
    with pytest.raises(DhanConfigError):
        DhanConfig.from_env(prefix="TESTDHAN_")


def test_backward_compat_valueerror(monkeypatch):
    assert issubclass(DhanConfigError, ValueError)
    assert issubclass(DhanMissingConfigError, ValueError)
    assert issubclass(DhanConfigError, DhanError)
    monkeypatch.delenv("TESTDHAN_CLIENT_ID", raising=False)
    monkeypatch.setenv("TESTDHAN_ACCESS_TOKEN", "tok")
    with pytest.raises(ValueError):
        DhanConfig.from_env(prefix="TESTDHAN_")
