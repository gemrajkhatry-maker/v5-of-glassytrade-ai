"""Tests for AAA Precondition Engine wiring in SessionRuntime.

Covers:
- AAA engine and phase gate are instantiated
- LONG/SHORT signals evaluated against preconditions
- Failed preconditions downgrade signal to NO_TRADE
- NO_TRADE signals skip AAA check
- Missing data causes graceful pass (no blocking)
- _evaluate_aaa gathers correct inputs from pipeline state
"""

from __future__ import annotations

import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.runtime.orchestrator.session import SessionRuntime
from app.runtime.pipeline.events import Signal, Candle, CandleTimeframe, MarketStructureResult, Tick


def _make_tick(symbol: str = "NIFTY", price: float = 22000.0, ts: float = 1_700_000_000.0) -> Tick:
    return Tick(
        symbol=symbol, price=price, volume=10.0, timestamp=ts,
        bid=price - 0.5, ask=price + 0.5,
    )


def _session(symbols: list[str] | None = None) -> SessionRuntime:
    feed = MagicMock()
    feed.stream.return_value = iter([])
    feed.snapshot.return_value = {"running": False, "ticks_seen": 0, "state": "idle"}
    storage = MagicMock()
    return SessionRuntime(feed=feed, symbols=symbols or ["NIFTY"], storage=storage)


def _make_long_signal(symbol: str = "NIFTY", ts: float = 1_700_000_000.0) -> Signal:
    return Signal(
        symbol=symbol, timestamp=ts, type="LONG", entry=22000.0,
        sl=21950.0, tp=22100.0, rr=2.0, confidence=0.7,
        reason="Test long", source="pipeline", ofi=0.2,
    )


def _make_short_signal(symbol: str = "NIFTY", ts: float = 1_700_000_000.0) -> Signal:
    return Signal(
        symbol=symbol, timestamp=ts, type="SHORT", entry=22000.0,
        sl=22050.0, tp=21900.0, rr=2.0, confidence=0.7,
        reason="Test short", source="pipeline", ofi=-0.4,
    )


def _make_no_trade_signal(symbol: str = "NIFTY", ts: float = 1_700_000_000.0) -> Signal:
    return Signal(
        symbol=symbol, timestamp=ts, type="NO_TRADE", entry=0.0,
        sl=0.0, tp=0.0, rr=0.0, confidence=0.0,
        reason="No edge", source="pipeline", ofi=0.0,
    )


def _make_candle(symbol: str = "NIFTY", close: float = 22000.0, ts: float = 1_700_000_000.0) -> Candle:
    return Candle(
        symbol=symbol, timeframe=CandleTimeframe.M1,
        open=21990.0, high=22010.0, low=21980.0, close=close,
        volume=500.0, timestamp=ts,
    )


def _make_market_result(
    symbol: str = "NIFTY",
    market_state: str = "IMBALANCED",
    profile_shape: str = "P",
    poc: float = 22000.0,
    val: float = 21990.0,
    vah: float = 22010.0,
    ts: float = 1_700_000_000.0,
) -> MarketStructureResult:
    return MarketStructureResult(
        symbol=symbol, timestamp=ts,
        poc=poc, val=val, vah=vah,
        market_state=market_state,
        profile_shape=profile_shape,
    )


# ---------------------------------------------------------------------------
# 1. Stage instantiation
# ---------------------------------------------------------------------------

class TestAAAInstantiation:
    def test_aaa_engine_instantiated(self):
        session = _session()
        assert hasattr(session, "_aaa_engine")
        assert session._aaa_engine is not None

    def test_phase_gate_instantiated(self):
        session = _session()
        assert hasattr(session, "_phase_gate")
        assert session._phase_gate is not None

    def test_last_candle_dict_exists(self):
        session = _session()
        assert hasattr(session, "_last_candle")
        assert isinstance(session._last_candle, dict)

    def test_aaa_engine_in_snapshot(self):
        session = _session()
        snap = session.snapshot()
        assert "aaa_engine" in snap
        assert "buffer_pct" in snap["aaa_engine"]

    def test_phase_gate_in_snapshot(self):
        session = _session()
        snap = session.snapshot()
        assert "phase_gate" in snap
        assert "friday_skip" in snap["phase_gate"]


# ---------------------------------------------------------------------------
# 2. _run_signal_flow — AAA precondition gating
# ---------------------------------------------------------------------------

class TestAAASignalFlow:
    def test_no_trade_skips_aaa_check(self):
        """NO_TRADE signals should not be evaluated by AAA engine."""
        session = _session()
        events = []
        signal = _make_no_trade_signal()

        # Should not crash — NO_TRADE skips AAA
        session._run_signal_flow(signal, events)
        # NO_TRADE signals may not produce gate events, just verify no AAA downgrade
        for evt in events:
            if isinstance(evt, Signal):
                assert "AAA" not in evt.reason

    def test_long_signal_with_missing_candle_passes_gracefully(self):
        """When no candle is available, AAA should gracefully pass."""
        session = _session()
        events = []
        signal = _make_long_signal()

        # No candle tracked yet — should pass through to gates
        session._run_signal_flow(signal, events)
        # Signal flows to gates (produces gate events)
        assert len(events) > 0
        # No NO_TRADE downgrade due to missing candle
        for evt in events:
            if isinstance(evt, Signal):
                assert evt.type != "NO_TRADE" or "AAA" not in evt.reason

    def test_long_signal_with_balanced_market_downgraded(self):
        """LONG signal with BALANCED market state should fail PRE1 and be downgraded."""
        session = _session()
        ts = time.time()
        candle = _make_candle(ts=ts)
        session._last_candle["NIFTY"] = candle

        market = _make_market_result(market_state="BALANCED", ts=ts)
        session._market_structure._states["NIFTY"] = MagicMock()
        session._market_structure._states["NIFTY"].last_result = market

        events = []
        signal = _make_long_signal(ts=ts)
        session._run_signal_flow(signal, events)

        # Should be downgraded to NO_TRADE
        signal_events = [e for e in events if isinstance(e, Signal)]
        assert len(signal_events) >= 1
        assert signal_events[0].type == "NO_TRADE"
        assert "AAA" in signal_events[0].reason

    def test_short_signal_with_wrong_shape_downgraded(self):
        """SHORT signal with P-shape (wrong for short) should fail PRE3."""
        session = _session()
        ts = time.time()
        candle = _make_candle(ts=ts)
        session._last_candle["NIFTY"] = candle

        market = _make_market_result(
            market_state="IMBALANCED",
            profile_shape="P",  # P-shape is for longs, not shorts
            ts=ts,
        )
        session._market_structure._states["NIFTY"] = MagicMock()
        session._market_structure._states["NIFTY"].last_result = market

        events = []
        signal = _make_short_signal(ts=ts)
        session._run_signal_flow(signal, events)

        signal_events = [e for e in events if isinstance(e, Signal)]
        assert len(signal_events) >= 1
        assert signal_events[0].type == "NO_TRADE"
        assert "AAA" in signal_events[0].reason


# ---------------------------------------------------------------------------
# 3. _evaluate_aaa helper
# ---------------------------------------------------------------------------

class TestEvaluateAAA:
    def test_returns_pass_when_no_candle(self):
        """Should return passing result when no candle data exists."""
        session = _session()
        signal = _make_long_signal()
        result = session._evaluate_aaa(signal)
        assert result.all_passed is True
        assert "candle" in result.reason.lower()

    def test_returns_pass_when_no_market_state(self):
        """Should return passing result when market state is empty."""
        session = _session()
        ts = time.time()
        session._last_candle["NIFTY"] = _make_candle(ts=ts)

        market = _make_market_result(market_state="", ts=ts)
        session._market_structure._states["NIFTY"] = MagicMock()
        session._market_structure._states["NIFTY"].last_result = market

        signal = _make_long_signal(ts=ts)
        result = session._evaluate_aaa(signal)
        assert result.all_passed is True
        assert "market state" in result.reason.lower()

    def test_gathers_correct_inputs_for_long(self):
        """Should call aaa_engine.evaluate with correct LONG inputs."""
        session = _session()
        # Use a timestamp during AAA window (Tuesday 10:00 AM)
        ts = datetime(2024, 1, 9, 10, 0, 0).timestamp()

        candle = _make_candle(close=22000.0, ts=ts)
        session._last_candle["NIFTY"] = candle

        market = _make_market_result(
            market_state="IMBALANCED",
            profile_shape="P",
            poc=22000.0, val=21995.0, vah=22005.0,
            ts=ts,
        )
        session._market_structure._states["NIFTY"] = MagicMock()
        session._market_structure._states["NIFTY"].last_result = market

        # Inject orderflow data
        ofi_metric = MagicMock()
        ofi_metric.ofi = 0.2
        ofi_metric.cumulative_delta = 500.0
        session._signal._last_orderflow["NIFTY"] = ofi_metric

        signal = _make_long_signal(ts=ts)
        result = session._evaluate_aaa(signal)

        # All 5 preconditions should be evaluated (may pass or fail on PRE4/PRE5)
        assert len(result.passed) + len(result.failed) == 5

    def test_phase_gate_evaluated_from_signal_timestamp(self):
        """Phase state should be derived from signal timestamp."""
        session = _session()
        # Use a timestamp during AAA window (e.g. Tuesday 10:00 AM)
        ts = datetime(2024, 1, 9, 10, 0, 0).timestamp()  # Tuesday

        session._last_candle["NIFTY"] = _make_candle(ts=ts)
        market = _make_market_result(market_state="IMBALANCED", profile_shape="P", ts=ts)
        session._market_structure._states["NIFTY"] = MagicMock()
        session._market_structure._states["NIFTY"].last_result = market

        signal = _make_long_signal(ts=ts)
        result = session._evaluate_aaa(signal)

        # PRE2_TIME should pass during AAA window
        from app.domain.services.session_phase_gate import AllowedAction
        pre2_passed = any(
            str(p) == "Precondition.PRE2_TIME" for p in result.passed
        )
        # During AAA window, phase should allow trading
        assert pre2_passed is True


# ---------------------------------------------------------------------------
# 4. Warmup clears candle cache
# ---------------------------------------------------------------------------

class TestAAAWarmup:
    def test_warmup_clears_last_candle(self):
        session = _session()
        session._last_candle["NIFTY"] = _make_candle()
        assert "NIFTY" in session._last_candle

        session.warmup()
        assert "NIFTY" not in session._last_candle
        assert len(session._last_candle) == 0
