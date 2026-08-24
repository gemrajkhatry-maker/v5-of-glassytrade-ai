"""Domain clock vocabulary tests (P0-1).

``SystemClock`` is the wall clock for live/paper; ``TestClock`` is the
deterministic, engine-driven clock for backtest/replay. Both satisfy the
``Clock`` protocol.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from tradex_domain.clock import Clock, SystemClock, TestClock


def _ts(h: int, m: int = 0) -> datetime:
    return datetime(2026, 8, 1, h, m, tzinfo=UTC)


def test_system_clock_returns_utc_now() -> None:
    before = datetime.now(UTC)
    now = SystemClock().now()
    after = datetime.now(UTC)
    assert now.tzinfo is UTC
    assert before <= now <= after


def test_test_clock_starts_at_given_instant() -> None:
    start = _ts(9, 15)
    clock = TestClock(start=start)
    assert clock.now() == start


def test_test_clock_advance() -> None:
    clock = TestClock(start=_ts(9, 15))
    clock.advance(timedelta(minutes=5))
    assert clock.now() == _ts(9, 20)


def test_test_clock_set() -> None:
    clock = TestClock(start=_ts(9, 15))
    clock.set(_ts(10, 0))
    assert clock.now() == _ts(10, 0)


def test_test_clock_advance_to_is_monotonic() -> None:
    """advance_to only moves forward — a replay tape never rewinds time."""
    clock = TestClock(start=_ts(9, 15))
    clock.advance_to(_ts(10, 0))
    assert clock.now() == _ts(10, 0)
    # Earlier target is a no-op.
    clock.advance_to(_ts(9, 30))
    assert clock.now() == _ts(10, 0)
    # Equal target is a no-op.
    clock.advance_to(_ts(10, 0))
    assert clock.now() == _ts(10, 0)


def test_clocks_satisfy_protocol() -> None:
    """Both implementations are structurally valid Clock instances."""
    assert isinstance(SystemClock(), Clock)
    assert isinstance(TestClock(), Clock)


def test_test_clock_exposed_via_domain_package() -> None:
    from tradex_domain import SystemClock as PkgSystemClock
    from tradex_domain import TestClock as PkgTestClock

    assert PkgSystemClock is SystemClock
    assert PkgTestClock is TestClock
