"""Tests for RiskLoadStatus — distinguishing missing/corrupt/storage-error states.

Phase 0.1 of the architecture refactor: risk-state load status must be truthful.
The previous SessionRisk._load() caught all exceptions and logged the same
"failed to load persisted state" warning for every cause — a missing current-day
key (legitimate new day) was indistinguishable from corrupt data or storage
failure. A trader reading logs would see a scary warning on every fresh start.
"""
import json
import logging
import pytest

from quant.execution.risk import RiskLoadStatus, SessionRisk


class MemKV:
    """Test double for the kv_get/kv_set storage contract."""

    def __init__(self, initial=None):
        self.m = dict(initial or {})
        self.get_count = 0
        self.set_count = 0

    def kv_set(self, k, v):
        if isinstance(v, (dict, list, tuple)):
            v = json.dumps(v)
        self.m[k] = v
        self.set_count += 1

    def kv_get(self, k):
        self.get_count += 1
        return self.m.get(k)


class FailingKV:
    """Storage that raises on every operation (simulates disk/connection failure)."""

    def __init__(self, exc=RuntimeError("disk failure")):
        self._exc = exc

    def kv_get(self, k):
        raise self._exc

    def kv_set(self, k, v):
        raise self._exc


def test_risk_load_status_enum_exists():
    """RiskLoadStatus must define the canonical load outcomes."""
    assert RiskLoadStatus.MISSING_INITIALIZED.value == "MISSING_INITIALIZED"
    assert RiskLoadStatus.LOADED.value == "LOADED"
    assert RiskLoadStatus.CORRUPT.value == "CORRUPT"
    assert RiskLoadStatus.STORAGE_ERROR.value == "STORAGE_ERROR"
    assert RiskLoadStatus.MEMORY_ONLY.value == "MEMORY_ONLY"


def test_load_status_exposed_on_session_risk():
    """SessionRisk exposes the load outcome for telemetry/readiness."""
    r = SessionRisk()
    assert r.load_status == RiskLoadStatus.MEMORY_ONLY

    kv = MemKV()
    r2 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-09-07")
    assert r2.load_status == RiskLoadStatus.MISSING_INITIALIZED


def test_missing_current_day_key_is_not_an_error():
    """A missing key for the current day is a legitimate new session, not an error.

    Previously this logged a scary 'failed to load persisted state' warning.
    After the fix: MISSING_INITIALIZED at INFO level, never WARNING/ERROR.
    """
    kv = MemKV()
    r = SessionRisk(storage=kv, symbol="NIFTY", date="2026-09-07")
    assert r.load_status == RiskLoadStatus.MISSING_INITIALIZED
    assert r.state().daily_pnl == 0.0
    assert r.state().halted is False
    assert r.can_trade()[0] is True


def test_missing_key_does_not_log_warning(caplog):
    """Fresh start must not produce a warning-level log — that is the bug."""
    kv = MemKV()
    with caplog.at_level(logging.WARNING):
        SessionRisk(storage=kv, symbol="NIFTY", date="2026-09-07")
    # No warning about "failed to load" for a legitimate new day
    assert "failed to load" not in caplog.text


def test_corrupt_json_quarantines_state():
    """Corrupt persisted JSON must be classified CORRUPT, not silently reset.

    A corrupt value in storage is a real signal: disk corruption, partial write,
    or cross-process race. Silently resetting and starting fresh hides the problem
    and can allow a position-sizing or halt state to be lost.
    """
    kv = MemKV({"daily_risk:NIFTY:2026-09-07": "{not-json"})
    r = SessionRisk(storage=kv, symbol="NIFTY", date="2026-09-07")
    assert r.load_status == RiskLoadStatus.CORRUPT
    # Money-safety: corrupt state must not allow trading
    assert r.can_trade()[0] is False


def test_corrupt_json_logs_error(caplog):
    """Corrupt state is a real error — it must be logged loudly."""
    kv = MemKV({"daily_risk:NIFTY:2026-09-07": "{not-json"})
    with caplog.at_level(logging.ERROR):
        SessionRisk(storage=kv, symbol="NIFTY", date="2026-09-07")
    assert "corrupt" in caplog.text.lower() or "failed to load" in caplog.text.lower()


def test_storage_error_blocks_trades():
    """A storage failure (disk/connection) must block new entries.

    If the store is down, we cannot persist the next trade's outcome. Allowing
    entries in that state risks losing the halt/sizing state on the next restart.
    """
    kv = FailingKV()
    r = SessionRisk(storage=kv, symbol="NIFTY", date="2026-09-07")
    assert r.load_status == RiskLoadStatus.STORAGE_ERROR
    allowed, reason = r.can_trade()
    assert allowed is False
    assert "storage" in reason.lower() or "persist" in reason.lower()


def test_storage_error_logs_critical(caplog):
    """Storage failure is a critical operational event."""
    kv = FailingKV()
    with caplog.at_level(logging.CRITICAL):
        SessionRisk(storage=kv, symbol="NIFTY", date="2026-09-07")
    assert "storage" in caplog.text.lower() or "persist" in caplog.text.lower()


def test_successful_load_is_classified_loaded():
    """When prior state is present and valid, it loads cleanly."""
    kv = MemKV()
    r1 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-09-07")
    r1.record_trade(-500.0)

    r2 = SessionRisk(storage=kv, symbol="NIFTY", date="2026-09-07")
    assert r2.load_status == RiskLoadStatus.LOADED
    assert r2.state().daily_pnl == -500.0


def test_memory_only_when_no_storage():
    """No storage wired — used in tests/replay. Always allowed to trade."""
    r = SessionRisk()
    assert r.load_status == RiskLoadStatus.MEMORY_ONLY
    assert r.can_trade()[0] is True


def test_corrupt_daily_pnl_exceeding_equity_clamp_is_corrupt():
    """Cross-scale corruption (crore-scale P&L on lakh-scale equity) is caught."""
    kv = MemKV({
        "daily_risk:NIFTY:2026-09-07": json.dumps({
            "daily_pnl": 999_999_999.0,
            "consecutive_losses": 0,
            "consecutive_wins": 0,
            "trades_today": 0,
            "halted": False,
            "halt_reason": "",
            "equity": 1_000_000.0,
        })
    })
    r = SessionRisk(storage=kv, symbol="NIFTY", date="2026-09-07",
                    starting_equity=1_000_000.0)
    # The existing clamp logic resets to 0; this should be classified CORRUPT
    assert r.load_status == RiskLoadStatus.CORRUPT
    assert r.state().daily_pnl == 0.0


def test_new_day_missing_key_after_prior_day_trades():
    """After trading yesterday, starting a new day must be MISSING_INITIALIZED
    even though the store has keys for other dates."""
    kv = MemKV()
    r_yesterday = SessionRisk(storage=kv, symbol="NIFTY", date="2026-09-06")
    r_yesterday.record_trade(1000.0)

    r_today = SessionRisk(storage=kv, symbol="NIFTY", date="2026-09-07")
    assert r_today.load_status == RiskLoadStatus.MISSING_INITIALIZED
    assert r_today.state().daily_pnl == 0.0
    assert r_today.state().trades_today == 0
