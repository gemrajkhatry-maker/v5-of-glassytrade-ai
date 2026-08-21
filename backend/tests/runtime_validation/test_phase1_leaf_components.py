"""PHASE 1 — LEAF COMPONENT TESTS (rewritten against the LIVE pipeline, 2026-08-09).

Originally tested legacy dead modules (confirmation_bundle.compute_atr,
gates.signal_builder.build_entry_signal, execution.exit_engine). Those were
deleted in Phase C (C1/C2). This rewrite exercises the canonical runtime path:
live `quant.decision.signal_builder.SignalBuilder`, live
`quant.execution.exits.ExitEngine`, live `Portfolio`, and the real paper broker
adapter. Leaves with no live equivalent (standalone ATR) are dropped.

Coverage per component:
  1a. Market data ingestion   -> tests.helpers.market_data.generate_market_data + OHLC invariants
  1b. Indicator/excursions    -> update_excursions (live exit_rules MAE/MFE tracking)
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
from quant.execution.exit_rules import update_excursions
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
# 1b. Excursion tracking (live exit_rules.update_excursions)
# ---------------------------------------------------------------------------


class TestIndicators:
    def test_excursions_track_mae_mfe(self):
        pos = Position(
            side=Side.LONG, entry_price=Decimal("100"), size=Decimal("1"),
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
        )
        update_excursions(pos, 95.0)   # adverse move of 5
        update_excursions(pos, 108.0)  # favorable move of 8
        assert float(pos.mae) == pytest.approx(5.0)
        assert float(pos.mfe) == pytest.approx(8.0)

    def test_short_position_excursion_sign(self):
        pos = Position(
            side=Side.SHORT, entry_price=Decimal("100"), size=Decimal("1"),
            stop_loss=Decimal("105"), take_profit=Decimal("90"),
        )
        update_excursions(pos, 103.0)  # adverse move of 3
        update_excursions(pos, 96.0)   # favorable move of 4
        assert float(pos.mae) == pytest.approx(3.0)
        assert float(pos.mfe) == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# 1c. Signal generation (live SignalBuilder)
# ---------------------------------------------------------------------------


class TestSignalGeneration:
    def test_long_signal_builds_valid_rr(self):
        sb = SignalBuilder()
        # close 100, VAL 98, step 1; SL sits 2 NSE-option ticks INSIDE the
        # value-area edge (98 - 2*0.05 = 97.9), not a full bucket outside.
        state = _state(close=100.0, val=98.0, step=1.0, nearest=98.0)
        sig = sb.build(_ctx(state, "LONG"), _pass_results())
        assert sig is not None
        assert sig.type == "LONG"
        assert sig.entry == pytest.approx(100.0)
        assert sig.sl < sig.entry < sig.tp
        assert sig.sl == pytest.approx(97.9)
        assert sig.tp == pytest.approx(104.2)
        assert sig.rr == pytest.approx(2.0)

    def test_short_signal_is_sell(self):
        sb = SignalBuilder()
        # close 100, anchor level 102 (nearest, above entry); SL sits 2 ticks
        # INSIDE it (102 + 2*0.05 = 102.1), TP 2R below entry.
        state = _state(close=100.0, val=98.0, step=1.0, nearest=102.0)
        sig = sb.build(_ctx(state, "SHORT"), _pass_results())
        assert sig is not None
        assert sig.type == "SHORT"
        assert sig.sl > sig.entry > sig.tp
        assert sig.sl == pytest.approx(102.1)
        assert sig.tp == pytest.approx(95.8)

    def test_thin_stop_rejected(self):
        from quant.decision.signal_builder import (
            is_min_stop_met,
            is_stop_too_thin,
        )

        # A razor-thin stop (VA-fade SL at VAL-step: 0.02 on a 104.92 entry,
        # ~0.02%) is noise and must not clear the 0.1% structural-stop floor.
        assert is_stop_too_thin(entry=104.92, sl=104.90)
        assert not is_min_stop_met(entry=104.92, sl=104.90)
        # The Triple-A builder's 2-tick-inside SL (104.81, ~0.105% away)
        # clears the floor and emits a signal.
        sb = SignalBuilder()
        state = _state(close=104.92, val=104.91, step=0.01, nearest=104.9)
        sig = sb.build(_ctx(state, "LONG"), _pass_results())
        assert sig is not None
        assert sig.sl == pytest.approx(104.81)

    def test_failing_gate_returns_none(self):
        sb = SignalBuilder()
        state = _state(close=100.0, val=98.0, step=1.0, nearest=98.0)
        results = [GateResult(i, i != 3) for i in range(1, 6)]  # gate 3 fails
        assert sb.build(_ctx(state, "LONG"), results) is None

    def test_size_clamped_to_max(self):
        sb = SignalBuilder()
        qty = sb.size(equity=100_000.0, entry=100.0, sl=99.9,
                      risk_per_trade_pct=0.01)
        assert qty == 1000  # MAX_POSITION_QUANTITY


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
    def test_sl_breach_closes_via_process_tick(self):
        p = Portfolio.create_default()
        sig = _signal(price=100, sl=95, tp=120)
        pos = p.open_position(sig, "NIFTY")
        assert pos is not None
        tick = OHLC.create("2026-08-05T09:25:00Z", 94, 95, 93, 94.2, 900)
        closed = p.process_tick(tick)
        assert len(closed) == 1
        assert closed[0].close_reason == "STOP_LOSS"
        assert closed[0].status == PositionStatus.CLOSED
        assert len(p.positions) == 0
        assert len(p.closed_trades) == 1

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

    def test_closed_trade_accounts_commission(self):
        p = Portfolio.create_default()
        sig = _signal(price=100, sl=95, tp=120)
        pos = p.open_position(sig, "NIFTY")
        initial_balance = p.balance
        p.process_tick(OHLC.create("2026-08-05T09:25:00Z", 94, 95, 93, 94.2, 900))
        assert p.balance < initial_balance  # loss + commission deducted


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
