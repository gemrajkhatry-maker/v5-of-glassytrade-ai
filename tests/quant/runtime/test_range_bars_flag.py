"""Task 8 — GLASSYTRADE_USE_RANGE_BARS flag: micro geometry + live warmup."""

from __future__ import annotations

from quant.bars import Bar
from quant.decision.context_builder import DecisionContextBuilder
from quant.runtime import QuantEngine
from quant.brokers.gateway import Tick
from tests.helpers.synthetic import SyntheticGateway


class _DummyRisk:
    equity = 1_000_000.0
    risk_per_trade_pct = 0.01
    halted = False
    consecutive_losses = 0
    consecutive_wins = 0


def _bar(close: float = 100.5) -> Bar:
    return Bar(
        time="2026-09-23T10:00:00+05:30",
        open=100.0, high=101.0, low=99.0, close=close,
        volume=1000.0, buy_volume=600.0, sell_volume=400.0, delta=200.0,
    )


def _warmup(**kw) -> bool:
    """Build a context and return warmup_complete for the given warmup inputs."""
    builder = DecisionContextBuilder()
    ctx = builder.build(
        bar=_bar(),
        symbol="NIFTY",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
        bar_index=int(kw.pop("bar_index", 0)),
        warm_bars=int(kw.pop("warm_bars", 0)),
        cooldown_remaining_sec=0.0,
        risk_state=_DummyRisk(),
        **kw,
    )
    return bool(ctx.warmup_complete)


# ---------------------------------------------------------------------------
# Flag default off → time micro unchanged
# ---------------------------------------------------------------------------


def test_flag_off_keeps_time_micro():
    eng = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=300)
    assert eng.range_bars_enabled is False
    assert eng._micro_aggregator is not None
    assert eng._micro_aggregator.range_size is None
    assert eng._micro_aggregator.interval_seconds == 60
    assert eng.live_range_bars == 0
    # macro stays time-based
    assert eng._aggregator.range_size is None
    assert eng._aggregator.interval_seconds == 300


def test_range_flag_builds_range_micro(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_USE_RANGE_BARS", "1")
    eng = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=300)
    assert eng.range_bars_enabled is True
    assert eng._micro_aggregator is not None
    assert eng._micro_aggregator.range_size is not None
    assert eng._micro_aggregator.range_size > 0
    # 5m macro stays time-based even when range mode is on
    assert eng._aggregator.range_size is None
    assert eng._aggregator.interval_seconds == 300
    assert eng.live_range_bars == 0


def test_range_flag_kwarg_overrides_env(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_USE_RANGE_BARS", "1")
    eng_off = QuantEngine(
        SyntheticGateway([]), "SYM", interval_seconds=300, range_bars_enabled=False,
    )
    assert eng_off.range_bars_enabled is False
    assert eng_off._micro_aggregator.range_size is None

    monkeypatch.delenv("GLASSYTRADE_USE_RANGE_BARS", raising=False)
    eng_on = QuantEngine(
        SyntheticGateway([]), "SYM", interval_seconds=300, range_bars_enabled=True,
    )
    assert eng_on.range_bars_enabled is True
    assert eng_on._micro_aggregator.range_size is not None


def test_flag_env_accepts_truthy_spellings(monkeypatch):
    for raw in ("true", "yes", "on", "TRUE"):
        monkeypatch.setenv("GLASSYTRADE_USE_RANGE_BARS", raw)
        eng = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=300)
        assert eng.range_bars_enabled is True, raw
    for raw in ("", "0", "false", "off"):
        monkeypatch.setenv("GLASSYTRADE_USE_RANGE_BARS", raw)
        eng = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=300)
        assert eng.range_bars_enabled is False, raw


# ---------------------------------------------------------------------------
# warmup_complete: time path unchanged; range path = 15 live bars AND 15 min
# ---------------------------------------------------------------------------


def test_time_bar_warmup_unchanged():
    # (bar_index + warm_bars) >= 15
    assert _warmup(bar_index=15, warm_bars=0) is True
    assert _warmup(bar_index=10, warm_bars=5) is True
    assert _warmup(bar_index=5, warm_bars=5) is False
    assert _warmup(bar_index=0, warm_bars=14) is False
    # explicit range kwargs must not disturb the time path when flag is off
    assert _warmup(
        bar_index=0, warm_bars=14,
        range_bars_enabled=False, live_range_bars=99, live_minutes=99.0,
    ) is False


def test_range_warmup_needs_15_live_and_15_min():
    # 14 live bars, 20 min → False
    assert _warmup(
        range_bars_enabled=True, live_range_bars=14, live_minutes=20.0,
        bar_index=999, warm_bars=999,
    ) is False
    # 15 live bars, 0 min → False
    assert _warmup(
        range_bars_enabled=True, live_range_bars=15, live_minutes=0.0,
        bar_index=999, warm_bars=999,
    ) is False
    # 15 live bars, 14.9 min → False
    assert _warmup(
        range_bars_enabled=True, live_range_bars=15, live_minutes=14.9,
        bar_index=999, warm_bars=999,
    ) is False
    # 15 live + 15 min → True (bar_index/warm_bars must be ignored in range mode)
    assert _warmup(
        range_bars_enabled=True, live_range_bars=15, live_minutes=15.0,
        bar_index=0, warm_bars=0,
    ) is True
    # 16 live + 16 min → True
    assert _warmup(
        range_bars_enabled=True, live_range_bars=16, live_minutes=16.0,
        bar_index=0, warm_bars=0,
    ) is True


# ---------------------------------------------------------------------------
# Live counter increments only on live range micro closes
# ---------------------------------------------------------------------------


def test_live_range_bars_increment_on_range_micro_close(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_USE_RANGE_BARS", "1")
    ticks = [
        Tick(time="t0", price=100.00, volume=1.0, buy_volume=1.0, sell_volume=0.0),
        Tick(time="t1", price=100.10, volume=1.0, buy_volume=1.0, sell_volume=0.0),
        Tick(time="t2", price=99.90, volume=1.0, buy_volume=0.0, sell_volume=1.0),
        Tick(time="t3", price=100.20, volume=1.0, buy_volume=1.0, sell_volume=0.0),
    ]
    eng = QuantEngine(SyntheticGateway(ticks), "SYM", interval_seconds=300)
    eng.run()
    # provisional H = tick (0.05): each subsequent tick spans >= H and closes a bar
    assert eng.live_range_bars >= 2
    # range mode captured a start timestamp for wall-clock minutes
    assert eng._range_mode_started_at is not None
    assert eng._live_range_minutes() >= 0.0


def test_time_mode_live_range_bars_stay_zero(monkeypatch):
    monkeypatch.delenv("GLASSYTRADE_USE_RANGE_BARS", raising=False)
    ticks = [
        Tick(time="t0", price=100.00, volume=1.0, buy_volume=1.0, sell_volume=0.0),
        Tick(time="t1", price=100.10, volume=1.0, buy_volume=1.0, sell_volume=0.0),
    ]
    eng = QuantEngine(SyntheticGateway(ticks), "SYM", interval_seconds=300)
    eng.run()
    assert eng.range_bars_enabled is False
    assert eng.live_range_bars == 0
    assert eng._range_mode_started_at is None
