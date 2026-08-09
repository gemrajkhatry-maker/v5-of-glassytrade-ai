"""PHASE 1 — LEAF COMPONENT TESTS (independent of pre-existing tests).

Every test below calls the REAL production class/function with deterministic
inputs and asserts deterministic outputs.  No internal logic is mocked.
The only boundary faked is the broker, and only via PaperBrokerAdapter (the
real in-process adapter used by paper mode) — no network.

Coverage per component:
  1a. Market data ingestion   -> tests.helpers.market_data.generate_market_data + OHLC invariants
  1b. Indicator calculation   -> compute_atr (confirmation bundle), update_excursions
  1c. Signal generation       -> build_entry_signal (real SL/TP/grade pipeline)
  1d. Risk sizing             -> Portfolio.open_position (tiered risk sizing math)
  1e. OMS                     -> Portfolio order lifecycle + ExitEngine stop-loss rule
  1f. Broker adapter          -> PaperBrokerAdapter.execute_order / cancel_order
"""
from __future__ import annotations

import math
from decimal import Decimal

import pytest

pytest.skip(
    "C4-deferred: rewrite against live pipeline (confirmation_bundle + gates.signal_builder "
    "deleted in C1; full rewrite planned in C4)",
    allow_module_level=True,
)

from tests.helpers.market_data import generate_market_data
from quant.contracts.value_objects import OHLC, AMTResult
from quant.contracts.entities import Position, Signal
from quant.contracts.aggregates import Portfolio, INITIAL_CAPITAL
from quant.contracts.enums import SignalType, SetupType, Source, Side, PositionStatus
from quant.decision.gates.confirmation_bundle import compute_atr
from quant.execution.exit_rules import update_excursions
from quant.decision.gates.signal_builder import build_entry_signal
from quant.execution.exit_engine import ExitEngine, ExitReason
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
# 1b. Indicator calculation
# ---------------------------------------------------------------------------


class TestIndicators:
    def test_atr_positive_finite(self):
        data = generate_market_data(days=50, start_price=100.0, regime="volatile")
        atr = compute_atr(data, 14)
        assert atr > 0
        assert math.isfinite(atr)

    def test_excursions_track_mae_mfe(self):
        pos = Position(
            side=Side.LONG, entry_price=Decimal("100"), size=Decimal("1"),
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
        )
        update_excursions(pos, 95.0)   # adverse move of 5
        update_excursions(pos, 108.0)  # favorable move of 8
        assert float(pos.mae) == pytest.approx(5.0)
        assert float(pos.mfe) == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# 1c. Signal generation (real SL/TP builder)
# ---------------------------------------------------------------------------


class TestSignalGeneration:
    def _amt(self) -> AMTResult:
        return AMTResult(
            market_state="BALANCED",
            poc=102.0,
            value_area_high=105.0,
            value_area_low=99.0,
            prior_poc=101.0,
            session_vwap=101.5,
            npoc_above=0.0,
            npoc_below=0.0,
            aggressive_prints=(),
            profile_shape="D",
            setup="MEAN_REVERSION",
            ib_high=106.0,
            ib_low=98.0,
            ib_complete=True,
        )

    def test_long_signal_builds_valid_rr(self):
        tick = OHLC.create("2026-08-05T09:20:00Z", 100.0, 101.0, 99.5, 100.5, 1200, vwap=100.8)
        sig = build_entry_signal(
            direction="LONG",
            tick=tick,
            amt_result=self._amt(),
            ai_result={"rationale": "phase1", "market_state": "BALANCED"},
            setup_type=SetupType.MEAN_REVERSION,
            data=[tick],
            confidence="High",
            tick_size=0.05,
        )
        assert sig.type == SignalType.BUY
        assert float(sig.price) == pytest.approx(100.5)
        assert float(sig.stop_loss) < float(sig.price) < float(sig.take_profit)
        assert sig.metadata.get("scale_in") is True
        assert ExitEngine.is_valid_rr(float(sig.price), float(sig.stop_loss), float(sig.take_profit)) is True

    def test_short_signal_is_sell(self):
        tick = OHLC.create("2026-08-05T09:20:00Z", 100.0, 101.0, 99.5, 99.5, 1200, vwap=100.8)
        sig = build_entry_signal(
            direction="SHORT",
            tick=tick,
            amt_result=self._amt(),
            ai_result={"rationale": "phase1", "market_state": "BALANCED"},
            setup_type=SetupType.MEAN_REVERSION,
            data=[tick],
            confidence="Medium",
            tick_size=0.05,
        )
        assert sig.type == SignalType.SELL
        assert float(sig.stop_loss) > float(sig.price) > float(sig.take_profit)


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
# 1e. OMS — order lifecycle
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

    def test_exit_engine_stop_loss_signal(self):
        engine = ExitEngine()
        sig = _signal(price=100, sl=95, tp=120)
        pos = Position.from_signal(sig, "NIFTY", Decimal("10"))
        pos.entry_time = "2026-08-05T09:00:00Z"
        engine.register_position("P1", "NIFTY", "LONG", 100, 95, 120)
        exit_sig = engine.check_position(
            pos, current_price=94.0, current_time=9999999999.0
        )
        assert exit_sig is not None
        assert exit_sig.reason == ExitReason.STOP_LOSS

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
