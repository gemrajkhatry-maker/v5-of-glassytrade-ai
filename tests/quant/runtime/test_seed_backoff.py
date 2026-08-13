# tests/quant/runtime/test_seed_backoff.py
"""History-seed startup backoff.

Startup spawns one AMT history-seed thread per engine almost simultaneously;
a burst of concurrent get_historical calls trips Dhan's server-side rate limit
([DH-3001]) and opens the broker circuit breaker before the first seed
succeeds. These tests pin the two mitigations in quant/runtime:
  1. ``_reserve_seed_slot`` staggers first-fetch starts across engines.
  2. the seed thread retries failed/empty fetches with jittered backoff.
"""

import threading
import time

import quant.runtime as rt
from quant.contracts.value_objects import OHLC
from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway
from tests.quant.runtime.test_runtime import _ticks


def _reset_seed_gate():
    rt._SEED_NEXT_START = 0.0


def test_seed_starts_staggered_across_engines():
    """3 engines reserving slots back-to-back must not fetch simultaneously."""
    _reset_seed_gate()
    starts = []
    lock = threading.Lock()

    def worker():
        rt._reserve_seed_slot()
        with lock:
            starts.append(time.monotonic())

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(starts) == 3
    # Adjacent starts are >= stagger apart minus the previous slot's max
    # jitter (delay is target - now + jitter, so spacing >= stagger - jitter).
    min_spacing = rt._SEED_STAGGER_SEC - rt._SEED_STAGGER_JITTER - 0.01
    assert starts[1] - starts[0] >= min_spacing
    assert starts[2] - starts[1] >= min_spacing


class _FlakyHistory:
    """History source that returns [] (as the Dhan adapter does when the
    rate-limit error is swallowed) for the first ``fail_times`` calls, then a
    single today-scoped candle."""

    def __init__(self, fail_times: int = 0):
        self.fail_times = fail_times
        self.calls = 0

    async def fetch_history(self, symbol, interval="5m", limit=500):
        self.calls += 1
        if self.calls <= self.fail_times:
            return []
        from datetime import datetime, timedelta

        from quant.contracts.timezones import IST

        now = datetime.now(IST)
        return [
            OHLC(
                time=(now - timedelta(minutes=5)).isoformat(),
                open=100.0, high=101.0, low=99.5, close=100.5,
                volume=1000.0, vwap=100.2, taker_buy_volume=0.0, delta=10.0,
            )
        ]


def _engine_with_history(history):
    eng = QuantEngine(
        SyntheticGateway(_ticks()), "SYM", interval_seconds=1,
        history_source=history,
    )
    # Seed directly (without run()) so no live bars flow and abort the seed.
    eng._start_amt_seed()
    return eng


def test_seed_retries_rate_limited_fetch():
    """A rate-limited (empty) first fetch must be retried with backoff until
    the data lands — never given up on after a single attempt."""
    _reset_seed_gate()
    history = _FlakyHistory(fail_times=2)
    eng = _engine_with_history(history)

    deadline = time.time() + 15
    while time.time() < deadline and eng._warm_bars == 0:
        time.sleep(0.2)

    assert history.calls == 3, f"expected 3 attempts, got {history.calls}"
    assert eng._warm_bars == 1
    assert len(eng._amt_candles) == 1


def test_seed_succeeds_on_first_attempt():
    _reset_seed_gate()
    history = _FlakyHistory(fail_times=0)
    eng = _engine_with_history(history)

    deadline = time.time() + 10
    while time.time() < deadline and eng._warm_bars == 0:
        time.sleep(0.2)

    assert history.calls == 1
    assert eng._warm_bars == 1


def test_seed_gives_up_after_max_retries():
    _reset_seed_gate()
    history = _FlakyHistory(fail_times=999)
    eng = _engine_with_history(history)

    # Max attempts = 1 + 2 backoff retries; give the retries time to finish.
    deadline = time.time() + 15
    while time.time() < deadline and history.calls < rt._SEED_FETCH_RETRIES:
        time.sleep(0.2)

    assert history.calls == rt._SEED_FETCH_RETRIES
    assert eng._warm_bars == 0
