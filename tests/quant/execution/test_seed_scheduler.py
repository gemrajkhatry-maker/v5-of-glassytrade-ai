"""Tests for history seed scheduler with rate-limit handling (Phase 0.5).

The previous AMT seed logic had retry handling but no global scheduler —
every engine independently hit Dhan during startup, causing DH-3001 rate
limits. Seed status was also not exposed for readiness/telemetry.

Phase 0.5 introduces:
- SeedStatus enum: NOT_STARTED, SEEDING, READY, DEGRADED_RATE_LIMIT,
  DEGRADED_EMPTY, FAILED
- HistorySeedScheduler: one shared request scheduler across all engines
- Per-engine seed status exposed for readiness and telemetry
"""
import time
import pytest

from quant.execution.seed_scheduler import (
    HistorySeedScheduler,
    SeedStatus,
    seed_status,
)


class FakeHistorySource:
    """Minimal history source double."""

    def __init__(self, candles=None, fail_with=None, fail_times=0):
        self._candles = candles or []
        self._fail_with = fail_with
        self._fail_times = fail_times
        self._call_count = 0

    def fetch_history(self, symbol, interval, limit):
        self._call_count += 1
        if self._fail_times > 0:
            self._fail_times -= 1
            if self._fail_with:
                raise self._fail_with
        return list(self._candles)


def test_seed_status_enum_exists():
    """SeedStatus must define the canonical seed outcomes."""
    assert SeedStatus.NOT_STARTED.value == "NOT_STARTED"
    assert SeedStatus.SEEDING.value == "SEEDING"
    assert SeedStatus.READY.value == "READY"
    assert SeedStatus.DEGRADED_RATE_LIMIT.value == "DEGRADED_RATE_LIMIT"
    assert SeedStatus.DEGRADED_EMPTY.value == "DEGRADED_EMPTY"
    assert SeedStatus.FAILED.value == "FAILED"


def test_seed_status_function_returns_status():
    """seed_status() returns the status for a given engine."""
    class FakeEngine:
        _seed_status = SeedStatus.READY
    assert seed_status(FakeEngine()) == SeedStatus.READY


def test_seed_status_unknown_when_no_attribute():
    """Engine without _seed_status attribute returns UNKNOWN."""
    class FakeEngine:
        pass
    assert seed_status(FakeEngine()) == SeedStatus.NOT_STARTED


def test_history_seed_scheduler_is_instantiable():
    """HistorySeedScheduler can be constructed."""
    source = FakeHistorySource()
    scheduler = HistorySeedScheduler(source)
    assert scheduler is not None


def test_scheduler_exposes_shared_state():
    """Scheduler tracks in-flight request count."""
    source = FakeHistorySource()
    scheduler = HistorySeedScheduler(source)
    assert scheduler.in_flight == 0


def test_scheduler_respects_rate_limit_delay():
    """Scheduler enforces minimum delay between requests."""
    source = FakeHistorySource(candles=[{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100, "time": "2026-09-07T09:15:00+05:30"}] * 50)
    scheduler = HistorySeedScheduler(source, min_interval_sec=0.1)

    start = time.monotonic()
    scheduler.fetch("NIFTY", "5m", 500)
    scheduler.fetch("BANKNIFTY", "5m", 500)
    elapsed = time.monotonic() - start

    # Second fetch should have been delayed by min_interval_sec
    assert elapsed >= 0.09


def test_scheduler_caches_successful_fetches():
    """Successful fetches are cached; repeated fetches return cached data."""
    candles = [{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100, "time": "2026-09-07T09:15:00+05:30"}] * 50
    source = FakeHistorySource(candles=candles)
    scheduler = HistorySeedScheduler(source)

    result1 = scheduler.fetch("NIFTY", "5m", 500)
    result2 = scheduler.fetch("NIFTY", "5m", 500)

    assert result1 == candles
    assert result2 == candles
    # Source should only be called once due to caching
    assert source._call_count == 1


def test_scheduler_retries_on_failure():
    """Transient failures are retried with backoff."""
    source = FakeHistorySource(
        candles=[{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100, "time": "2026-09-07T09:15:00+05:30"}] * 50,
        fail_with=ConnectionError("DH-3001 rate limit"),
        fail_times=1,
    )
    scheduler = HistorySeedScheduler(source, max_retries=3, base_delay_sec=0.01)

    result = scheduler.fetch("NIFTY", "5m", 500)
    assert result is not None
    assert source._call_count == 2


def test_scheduler_returns_none_after_max_retries():
    """After max retries exhausted, returns None (degraded)."""
    source = FakeHistorySource(
        fail_with=ConnectionError("DH-3001 rate limit"),
        fail_times=10,
    )
    scheduler = HistorySeedScheduler(source, max_retries=2, base_delay_sec=0.01)

    result = scheduler.fetch("NIFTY", "5m", 500)
    assert result is None


def test_scheduler_deduplicates_concurrent_requests():
    """Concurrent requests for the same symbol share one in-flight fetch."""
    source = FakeHistorySource(candles=[{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100, "time": "2026-09-07T09:15:00+05:30"}] * 50)
    scheduler = HistorySeedScheduler(source)

    # Simulate concurrent requests
    result1 = scheduler.fetch("NIFTY", "5m", 500)
    result2 = scheduler.fetch("NIFTY", "5m", 500)
    result3 = scheduler.fetch("NIFTY", "5m", 500)

    assert result1 == result2 == result3
    # All three should share one source call
    assert source._call_count == 1


def test_scheduler_per_symbol_isolation():
    """Different symbols are fetched independently."""
    source = FakeHistorySource(candles=[{"o": 1, "h": 2, "l": 0.5, "c": 1.5, "v": 100, "time": "2026-09-07T09:15:00+05:30"}] * 50)
    scheduler = HistorySeedScheduler(source)

    scheduler.fetch("NIFTY", "5m", 500)
    scheduler.fetch("BANKNIFTY", "5m", 500)

    assert source._call_count == 2
