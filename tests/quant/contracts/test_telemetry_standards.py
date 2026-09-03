# tests/quant/contracts/test_telemetry_standards.py
import pytest
from app.infrastructure.metrics import MetricsCollector
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


def test_collector_snapshot_contract():
    c = MetricsCollector()
    c.reset()
    c.record_tick(); c.record_tick()
    c.record_signal("LONG")
    c.record_pnl(12.345)
    c.record_cache_hit(); c.record_cache_miss()
    c.record_regime_change()
    snap = MetricsCollector().snapshot()  # same singleton
    assert snap["ticks_processed"] == 2
    assert snap["signals"] == {"LONG": 1}
    assert snap["total_pnl"] == 12.35
    assert snap["cache"] == {"hits": 1, "misses": 1, "hit_rate": 0.5}
    assert snap["regime_changes"] == 1
    assert snap["uptime_seconds"] >= 0
    c.reset()


def test_collector_reset_isolation():
    c = MetricsCollector()
    c.record_tick()
    c.reset()
    assert MetricsCollector().snapshot()["ticks_processed"] == 0


def test_registry_counter_names():
    from app.core.metrics import metrics
    assert hasattr(metrics, "counter")
    c1 = metrics.counter("ticks_processed_total", "Total ticks processed")
    c2 = metrics.counter("signals_generated_total", "Signals generated")
    assert c1.value >= 0 and c2.value >= 0
