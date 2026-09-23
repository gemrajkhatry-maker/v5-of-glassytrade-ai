# tests/quant/contracts/test_telemetry_standards.py
import pytest

from quant.contracts.ports.telemetry import NULL_TELEMETRY, ITelemetry, NullTelemetry

from brokers.broker.dhan.application.config import DhanConfig
from brokers.broker.dhan.domain.errors import (
    DhanConfigError,
    DhanError,
    DhanMissingConfigError,
)


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


def test_registry_counter_names():
    from app.core.metrics import metrics
    assert hasattr(metrics, "counter")
    c1 = metrics.counter("ticks_processed_total", "Total ticks processed")
    c2 = metrics.counter("signals_generated_total", "Signals generated")
    assert c1.value >= 0 and c2.value >= 0


# ---------------------------------------------------------------------------
# The port the brain counts through (quant -> host direction, no host import)
# ---------------------------------------------------------------------------
#
# quant counts bars and signals through quant.contracts.ports.telemetry and
# installs nothing itself: the host supplies the sink at composition time and a
# standalone brain (replay, script, CI) gets the no-op. The reverse direction —
# quant importing the host — is gated in tests/architecture/test_no_layer_bypass.py.

def test_telemetry_port_cannot_be_instantiated():
    """ITelemetry is an interface: no record methods, no instance."""
    with pytest.raises(TypeError):
        ITelemetry()  # type: ignore[abstract]


def test_telemetry_port_requires_both_record_methods():
    assert ITelemetry.__abstractmethods__ == frozenset(
        {"record_tick", "record_signal"}
    )


def test_null_telemetry_is_a_port_implementation():
    assert isinstance(NULL_TELEMETRY, NullTelemetry)
    assert isinstance(NULL_TELEMETRY, ITelemetry)


def test_null_telemetry_records_nothing():
    sink = NullTelemetry()
    assert sink.record_tick() is None
    assert sink.record_signal("LONG") is None


def test_null_telemetry_carries_no_state():
    """One shared instance is safe: no dict to accumulate on."""
    NULL_TELEMETRY.record_tick()
    NULL_TELEMETRY.record_signal("SHORT")
    assert not hasattr(NullTelemetry(), "__dict__")


def test_null_telemetry_never_raises_on_any_direction():
    for direction in ("", "UNKNOWN", "FLAT", "LONG", "SHORT"):
        NullTelemetry().record_signal(direction)
