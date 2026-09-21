"""PHASE 1 — LEAF COMPONENT TESTS (rewritten against the LIVE pipeline, 2026-08-09).

Originally tested legacy dead modules (confirmation_bundle.compute_atr,
gates.signal_builder.build_entry_signal, execution.exit_engine). Those were
deleted in Phase C (C1/C2). This rewrite exercises the canonical runtime path:
live `quant.decision.signal_builder.SignalBuilder`, live
`quant.execution.exits.ExitEngine`, live `Portfolio`, and the real paper broker
adapter. Leaves with no live equivalent (standalone ATR) are dropped.

Coverage per component:
  1a. Market data ingestion   -> tests.helpers.market_data.generate_market_data + OHLC invariants
  1b. Indicators              -> (excursion tracking removed: exit_rules.update_excursions had no production caller)
  1c. Signal generation       -> SignalBuilder.build (real SL/TP/grade pipeline)
  1d. Risk sizing             -> Portfolio.open_position (tiered risk sizing math)
  1e. OMS                     -> Portfolio order lifecycle + ExitEngine stop-loss rule
  1f. Broker adapter          -> PaperBrokerAdapter.execute_order / cancel_order
"""
from __future__ import annotations

import pytest
from dataclasses import replace as _dc_replace
from decimal import Decimal

from tests.helpers.market_data import generate_market_data
from quant.decision.result import GateResult
from quant.bars import Bar
from quant.contracts.value_objects import OHLC
from quant.contracts.entities import Position, Signal
from quant.contracts.aggregates import Portfolio, INITIAL_CAPITAL
from quant.contracts.enums import SignalType, SetupType, Source, Side, PositionStatus
from quant.decision.context import DecisionContext
from quant.decision.signal_builder import SignalBuilder
from quant.execution.exits import ExitEngine as LiveExitEngine
from quant.execution.order import Order as LiveOrder
from quant.execution.order import Position as LivePosition
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter


def _signal(price=100.0, sl=95.0, tp=110.0, is_buy=True, source=Source.AMT, **meta) -> Signal:
    return Signal(
        type=SignalType.BUY if is_buy else SignalType.SELL,
        price=price,
        reason="phase1",
        stop_loss=sl,
        take_profit=tp,
        timestamp="2026-08-05T09:15:00Z",
        setup=SetupType.TREND_MODEL,
        source=source,
        metadata=meta or None,
    )


def _bar(close, low=None, high=None) -> Bar:
    return Bar(time="2026-08-05T09:20:00Z", open=close, high=high or close + 0.1,
               low=low or close - 0.1, close=close, volume=100)


def _state(close, val, step, nearest) -> DecisionContext:
    """Live-API context: SignalBuilder anchors SL on ctx.val/vah/tick_size,
    so the fixture sets those directly (the old AuctionState shape is gone)."""
    return DecisionContext(
        bar=_bar(close), symbol="NIFTY", agent_direction=None,
        val=val,
        # An overhead `nearest` level is the short side's SL anchor in the
        # live API (ctx.vah); below-price nearest levels don't affect it.
        vah=max(nearest, val + 2 * step) if nearest > close else val + 2 * step,
        poc=close, tick_size=step,
        time_str="2026-08-05T09:20:00Z",
    )


def _ctx(state, direction="LONG") -> DecisionContext:
    return _dc_replace(state, agent_direction=direction, agent_probability=0.7)


def _pass_results():
    return [GateResult(i, True) for i in range(1, 5)]


# ---------------------------------------------------------------------------
# 1a. Market data ingestion
# ---------------------------------------------------------------------------


class TestMarketDataIngestion:
    def test_generator_is_deterministic(self):
        a = generate_market_data(days=20, start_price=100.0, regime="sideways")
        b = generate_market_data(days=20, start_price=100.0, regime="sideways")
        assert [(c.time, c.close) for c in a] == [(c.time, c.close) for c in b]

    def test_ohlc_invariants_hold_for_volatile_regime(self):
        data = generate_market_data(days=30, start_price=100.0, regime="volatile")
        assert len(data) == 30
        for c in data:
            assert c.high >= max(c.open, c.close), f"high<max(o,c) {c}"
            assert c.low <= min(c.open, c.close), f"low>min(o,c) {c}"
            assert c.volume > 0
            assert c.close > 0

    def test_bullish_regime_drifts_up(self):
        data = generate_market_data(days=50, start_price=100.0, regime="bullish")
        assert data[-1].close > data[0].open

    def test_bearish_regime_drifts_down(self):
        data = generate_market_data(days=50, start_price=100.0, regime="bearish")
        assert data[-1].close < data[0].open


# ---------------------------------------------------------------------------
# 1c. Signal generation (live SignalBuilder)
# ---------------------------------------------------------------------------


class TestSignalGeneration:
    def test_long_signal_builds_valid_rr(self):
        sb = SignalBuilder()
        # close 100, VAL 98 (anchor), step 0.5; SL sits 2 ticks (1.0 point) INSIDE
        # the structural level toward entry: 98 + 2 * 0.5 = 99.0, satisfying min_stop_distance.
        state = _state(close=100.0, val=98.0, step=0.5, nearest=98.0)
        sig = sb.build(_ctx(state, "LONG"), _pass_results())
        assert sig is not None
        assert sig.type == "LONG"
        assert sig.entry == pytest.approx(100.0)
        assert sig.sl < sig.entry < sig.tp
        assert sig.sl == pytest.approx(99.0)
        assert sig.tp == pytest.approx(102.0)
        assert sig.rr == pytest.approx(2.0)

    def test_short_signal_is_sell(self):
        sb = SignalBuilder()
        # close 100, anchor level 102 (nearest, above entry), step 0.5; SL sits 2 ticks
        # (1.0 point) INSIDE it toward entry: 102 - 2 * 0.5 = 101.0, satisfying min_stop_distance.
        state = _state(close=100.0, val=98.0, step=0.5, nearest=102.0)
        sig = sb.build(_ctx(state, "SHORT"), _pass_results())
        assert sig is not None
        assert sig.type == "SHORT"
        assert sig.sl > sig.entry > sig.tp
        assert sig.sl == pytest.approx(101.0)
        assert sig.tp == pytest.approx(98.0)

    def test_thin_stop_rejected(self):
        from quant.decision.signal_builder import (
            is_min_stop_met,
            is_stop_too_thin,
        )

        # A razor-thin stop (VA-fade SL at VAL-step: 0.02 on a 104.92 entry,
        # ~0.02%) is noise and must not clear the 0.1% structural-stop floor.
        assert is_stop_too_thin(entry=104.92, sl=104.90)
        assert not is_min_stop_met(entry=104.92, sl=104.90)
        # The Triple-A builder's SL must clear the 0.1% floor and emit a
        # signal. Anchor=104.50 (VAH, entry > vah >= val), entry=104.92,
        # step=0.1; 2-tick offset (0.2) fits inside entry, so
        # sl = 104.50 + 0.2 = 104.70 (~0.21% away) — clears the 0.1% floor.
        sb = SignalBuilder()
        state = _state(close=104.92, val=104.30, step=0.1, nearest=104.9)
        sig = sb.build(_ctx(state, "LONG"), _pass_results())
        assert sig is not None
        assert sig.sl == pytest.approx(104.70)

    def test_failing_gate_returns_none(self):
        sb = SignalBuilder()
        state = _state(close=100.0, val=98.0, step=1.0, nearest=98.0)
        results = [GateResult(i, i != 3) for i in range(1, 6)]  # gate 3 fails
        assert sb.build(_ctx(state, "LONG"), results) is None

    # NOTE: SignalBuilder.size was removed (duplicate sizing authority — the
    # engine sizes through SessionRisk.position_size + clamp_quantity). The
    # clamp ceiling itself is still covered by tests/quant/decision tests.


# ---------------------------------------------------------------------------
# 1d. Risk sizing (real Portfolio math)
# ---------------------------------------------------------------------------


class TestRiskSizing:
    def test_deterministic_size_medium_confidence(self):
        p = Portfolio.create_default()
        sig = _signal(price=100, sl=95, tp=110)  # no metadata -> Medium -> 0.35%
        pos = p.open_position(sig, "NIFTY")
        assert pos is not None
        # risk_amount = 1,000,000 * 0.0035 = 3,500 ; risk_per_unit = 5 -> 700
        assert float(pos.size) == pytest.approx(700, rel=0.01)

    def test_high_confidence_sizes_larger(self):
        p = Portfolio.create_default()
        sig = _signal(price=100, sl=95, tp=110, confidence="High")  # 0.5%
        pos = p.open_position(sig, "NIFTY")
        assert pos is not None
        # risk_amount = 1,000,000 * 0.005 = 5,000 ; risk_per_unit = 5 -> 1,000
        assert float(pos.size) == pytest.approx(1000, rel=0.01)

    def test_zero_risk_rejected(self):
        p = Portfolio.create_default()
        sig = _signal(price=100, sl=100, tp=110)
        assert p.open_position(sig, "NIFTY") is None

    def test_slippage_applied_on_entry(self):
        p = Portfolio.create_default()
        sig = _signal(price=100, sl=95, tp=110)
        pos = p.open_position(sig, "NIFTY")
        assert pos is not None
        assert float(pos.entry_price) > 100.0  # LONG buys higher (adverse slippage)


# ---------------------------------------------------------------------------
# 1e. OMS — order lifecycle (Portfolio + live ExitEngine)
# ---------------------------------------------------------------------------


class TestOMS:
    def test_live_exit_engine_sl_signal(self):
        sig = _signal(price=100, sl=95, tp=120)
        live_sig = type("LiveSig", (), {
            "entry": 100.0, "sl": 95.0, "tp": 120.0, "rr": 2.0,
            "confidence": 0.8, "symbol": "NIFTY", "timestamp": "t0",
            "type": "LONG",
        })()
        pos = LivePosition(order=LiveOrder(live_sig, 10),
                           open_price=100.0, open_time="t0", size=10)
        engine = LiveExitEngine()
        dec = engine.evaluate(pos, 94.0, bar_index=5)
        assert dec.should_exit
        assert dec.reason == "SL"

    def test_live_exit_engine_holds_in_range(self):
        sig = _signal(price=100, sl=95, tp=120)
        live_sig = type("LiveSig", (), {
            "entry": 100.0, "sl": 95.0, "tp": 120.0, "rr": 2.0,
            "confidence": 0.8, "symbol": "NIFTY", "timestamp": "t0",
            "type": "LONG",
        })()
        pos = LivePosition(order=LiveOrder(live_sig, 10),
                           open_price=100.0, open_time="t0", size=10)
        engine = LiveExitEngine(time_stop_bars=30)
        dec = engine.evaluate(pos, 101.0, bar_index=5)
        assert not dec.should_exit

# ---------------------------------------------------------------------------
# 1f. Broker adapter (real paper adapter)
# ---------------------------------------------------------------------------


class TestBrokerAdapter:
    def test_paper_execute_creates_position(self):
        broker = PaperBrokerAdapter()
        p = Portfolio.create_default()
        sig = _signal(price=100, sl=95, tp=110)
        pos = broker.execute_order(sig, p, "NIFTY")
        assert pos is not None
        assert pos.is_open
        assert float(pos.entry_price) > 100.0  # entry slippage applied

    def test_paper_cancel_order_idempotent(self):
        broker = PaperBrokerAdapter()
        assert broker.cancel_order("ORD-1") is True
        assert broker.cancel_order("ORD-1") is False  # already cancelled

    def test_paper_rejects_invalid_price(self):
        broker = PaperBrokerAdapter()
        p = Portfolio.create_default()
        sig = _signal(price=0, sl=95, tp=110)
        assert broker.execute_order(sig, p, "NIFTY") is None
