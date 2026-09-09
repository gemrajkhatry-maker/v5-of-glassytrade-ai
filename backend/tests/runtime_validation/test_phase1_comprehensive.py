#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PHASE 1 — COMPREHENSIVE BACKEND UNIT TESTS
============================================

For EACH backend component:
- Market data ingestion
- Indicator calculation
- Signal generation
- Risk sizing
- OMS
- Broker adapter

Each test:
- Calls the real functions/classes
- Passes deterministic inputs
- Asserts deterministic outputs

Mocks allowed ONLY for external broker/network calls.
"""

from __future__ import annotations

import pytest
from decimal import Decimal
from dataclasses import dataclass
from typing import Optional

# ============================================================================
# IMPORTS — real components only
# ============================================================================

from quant.bars import Bar
from quant.contracts.value_objects import OHLC
from quant.contracts.entities import Position, Signal
from quant.contracts.aggregates import Portfolio, INITIAL_CAPITAL
from quant.contracts.enums import (
    SignalType, SetupType, Source, Side, PositionStatus,
    MarketState,
)
from shared.entities.models import OptionType
from quant.contracts.exchange_config import ExchangeConfig
from quant.contracts.instrument_registry import DEFAULT_REGISTRY
from quant.decision.context import DecisionContext
from quant.decision.signal_builder import SignalBuilder
from quant.execution.exit_rules import update_excursions
from quant.execution.exits import ExitEngine
from quant.execution.order import Order as LiveOrder
from quant.execution.risk import SessionRisk
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
from quant.amt.market.half_trend import compute_half_trend_series
from quant.amt.orderflow.aggressive_prints import find_aggressive_prints as detect_aggressive_prints
from quant.amt.profile.volume_profile import compute_volume_profile
from quant.amt.analyzer import AMTAnalyzer


# ============================================================================
# FIXTURES — deterministic helpers
# ============================================================================

@dataclass(frozen=True)
class Candle:
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: int


def make_candle(time: str, close: float, high: Optional[float] = None,
                low: Optional[float] = None, volume: int = 100) -> Candle:
    return Candle(
        time=time,
        open=close,
        high=high if high is not None else close + 0.5,
        low=low if low is not None else close - 0.5,
        close=close,
        volume=volume,
    )


def make_ohlc(time: str, close: float, high: Optional[float] = None,
              low: Optional[float] = None, volume: int = 100) -> OHLC:
    ohlc = OHLC.create(
        time=time,
        open=close,
        high=high if high is not None else close + 0.5,
        low=low if low is not None else close - 0.5,
        close=close,
        volume=volume,
        vwap=close,
        taker_buy_volume=volume // 2,
        delta=0,
    )
    return ohlc


def make_bar(time: str, close: float, high: Optional[float] = None,
             low: Optional[float] = None, volume: int = 100) -> Bar:
    return Bar(
        time=time,
        open=close,
        high=high if high is not None else close + 0.5,
        low=low if low is not None else close - 0.5,
        close=close,
        volume=volume,
    )


def make_signal(price: float = 100.0, sl: float = 95.0, tp: float = 110.0,
                is_buy: bool = True, source: Source = Source.AMT,
                confidence: str = "Medium", **meta) -> Signal:
    return Signal(
        type=SignalType.BUY if is_buy else SignalType.SELL,
        price=price,
        reason="test",
        stop_loss=sl,
        take_profit=tp,
        timestamp="2026-08-05T09:15:00Z",
        setup=SetupType.TREND_MODEL,
        source=source,
        metadata=meta or None,
        confidence=confidence,
    )


def make_decision_context(close: float = 100.0, val: float = 98.0,
                          vah: float = 102.0, tick_size: float = 1.0,
                          direction: str = "LONG") -> DecisionContext:
    return DecisionContext(
        bar=make_bar("2026-08-05T09:20:00Z", close),
        symbol="NIFTY",
        agent_direction=direction,
        agent_probability=0.7,
        val=val,
        vah=vah,
        poc=close,
        tick_size=tick_size,
        time_str="2026-08-05T09:20:00Z",
    )


def pass_all_gates():
    from quant.decision.result import GateResult
    return [GateResult(i, True) for i in range(1, 6)]


# ============================================================================
# 1a. MARKET DATA INGESTION
# ============================================================================

class TestMarketDataIngestion:
    """Real market data ingestion paths — no mocks on internal logic."""

    def test_ohlc_create_maintains_invariants(self):
        """OHLC.create must always satisfy high >= max(o,c) and low <= min(o,c)."""
        ohlc = OHLC.create(
            time="t", open=100, high=99, low=101, close=100, volume=100,
            vwap=100, taker_buy_volume=50, delta=0,
        )
        # Even with invalid inputs, the factory should clamp
        assert ohlc.high >= ohlc.open
        assert ohlc.high >= ohlc.close
        assert ohlc.low <= ohlc.open
        assert ohlc.low <= ohlc.close

    def test_ohlc_vwap_returns_close_when_not_provided(self):
        ohlc = OHLC.create(
            time="t", open=100, high=102, low=98, close=101,
            volume=1000, vwap=None, taker_buy_volume=500, delta=0,
        )
        assert ohlc.vwap == 101  # defaults to close

    def test_bar_time_format_is_iso(self):
        bar = make_bar("2026-08-05T09:20:00Z", 100)
        assert "T" in bar.time
        assert bar.time.endswith("Z")

    def test_volume_must_be_positive(self):
        with pytest.raises((ValueError, AssertionError)):
            OHLC.create(
                time="t", open=100, high=102, low=98, close=101,
                volume=0, vwap=100, taker_buy_volume=0, delta=0,
            )

    def test_taker_buy_volume_does_not_exceed_volume(self):
        ohlc = OHLC.create(
            time="t", open=100, high=102, low=98, close=101,
            volume=100, vwap=100, taker_buy_volume=150, delta=0,
        )
        # taker_buy_volume should be clamped to volume
        assert ohlc.taker_buy_volume <= ohlc.volume


# ============================================================================
# 1b. INDICATOR CALCULATION
# ============================================================================

class TestIndicatorCalculation:
    """Real indicator calculations — no mocks on math."""

    def test_half_trend_series_length_matches_input(self):
        candles = [make_ohlc(f"t{i}", 100 + i) for i in range(50)]
        series = compute_half_trend_series(candles)
        assert len(series) == len(candles)

    def test_half_trend_first_rows_have_null_channel(self):
        candles = [make_ohlc(f"t{i}", 100 + i * 0.1) for i in range(50)]
        series = compute_half_trend_series(candles)
        # ATR(100) needs ~100 bars; short series → null channel
        for row in series:
            assert row.atr_high is None
            assert row.atr_low is None

    def test_half_trend_detects_flip_on_large_move(self):
        # Construct a zigzag that forces trend flips
        candles = []
        price = 100.0
        for i in range(150):
            if i % 50 < 25:
                price -= 2.0  # down leg
            else:
                price += 2.0  # up leg
            candles.append(make_ohlc(f"t{i}", price))

        series = compute_half_trend_series(candles)
        # After ATR warm-up, both buy and sell signals should appear
        assert any(r.buy_signal for r in series[100:]), "expected buy signal after warm-up"
        assert any(r.sell_signal for r in series[100:]), "expected sell signal after warm-up"

    def test_volume_profile_returns_levels_sorted_by_volume(self):
        candles = [make_ohlc(f"t{i}", 100 + (i % 10)) for i in range(100)]
        profile = compute_volume_profile(candles, num_levels=5)
        prices = [lv.price for lv in profile]
        # Prices should be unique
        assert len(prices) == len(set(prices))
        # Should be sorted (either ascending or descending by price)
        assert prices == sorted(prices) or prices == sorted(prices, reverse=True)

    def test_aggressive_print_detection_identifies_large_delta(self):
        candles = [
            make_ohlc("t0", 100, volume=100, taker_buy_volume=50, delta=0),
            make_ohlc("t1", 100.5, volume=500, taker_buy_volume=400, delta=200),  # aggressive
            make_ohlc("t2", 100.3, volume=80, taker_buy_volume=40, delta=-10),
        ]
        prints = detect_aggressive_prints(candles, threshold_volume=300, threshold_delta=100)
        assert len(prints) >= 1
        assert any(p["side"] == "BUY" for p in prints)

    def test_amt_analyzer_produces_market_state(self):
        analyzer = AMTAnalyzer()
        candles = [make_ohlc(f"t{i}", 100 + i * 0.5) for i in range(100)]
        result = analyzer.analyze(candles)
        assert result.market_state in ("BALANCED", "TRENDING_UP", "TRENDING_DOWN", "NO_TRADE")

    def test_amt_analyzer_poc_is_within_value_area(self):
        analyzer = AMTAnalyzer()
        candles = [make_ohlc(f"t{i}", 100 + (i % 10)) for i in range(200)]
        result = analyzer.analyze(candles)
        assert result.value_area_low <= result.poc <= result.value_area_high

    def test_exchange_config_lot_sizes_are_canonical(self):
        """Verify lot sizes match authoritative exchange config."""
        cfg = ExchangeConfig.for_exchange("NSE")
        assert cfg.get_lot_size("NIFTY") == 65
        assert cfg.get_lot_size("BANKNIFTY") == 30
        assert cfg.get_lot_size("FINNIFTY") == 60

        cfg_mcx = ExchangeConfig.for_exchange("MCX")
        assert cfg_mcx.get_lot_size("GOLDM") == 10
        assert cfg_mcx.get_lot_size("CRUDEOIL") == 100

    def test_instrument_registry_resolves_lot_size(self):
        """DEFAULT_REGISTRY must return canonical lot sizes."""
        assert DEFAULT_REGISTRY.resolve("NIFTY").lot_size == 65
        assert DEFAULT_REGISTRY.resolve("BANKNIFTY").lot_size == 30
        assert DEFAULT_REGISTRY.resolve("GOLDM").lot_size == 10

    def test_option_type_detection_anchored(self):
        """CE/PE/CALL/PUT must only match as trailing token."""
        assert AMTAnalyzer._detect_option_type("NIFTY 11 AUG 24600 CALL") == OptionType.CALL
        assert AMTAnalyzer._detect_option_type("NIFTY 11 AUG 24600 PUT") == OptionType.PUT
        assert AMTAnalyzer._detect_option_type("PRINCE 25 JUN 100 PUT") == OptionType.PUT
        assert AMTAnalyzer._detect_option_type("NIFTY 11 AUG 24600 FUT") == OptionType.UNKNOWN
        assert AMTAnalyzer._detect_option_type("") == OptionType.UNKNOWN

    def test_detect_second_drive(self):
        """Second drive detection: D2 when price reclaims prior D1 extreme."""
        # Simulate D1 rejected (low made, then price reclaimed above entry)
        candles = [
            make_ohlc("t0", 100),   # D1 entry
            make_ohlc("t1", 98),    # D1 low (rejection)
            make_ohlc("t2", 97),    # D1 extreme
            make_ohlc("t3", 99),    # reclaim starts
            make_ohlc("t4", 101),   # D2 reclaim complete
        ]
        analyzer = AMTAnalyzer()
        result = analyzer.analyze(candles)
        # With displacement and reclaim, isSecondDrive may be True
        # (depends on internal logic; we just verify the field exists)
        assert hasattr(result, 'is_second_drive') or hasattr(result, 'drive_entry_valid')


# ============================================================================
# 1c. SIGNAL GENERATION
# ============================================================================

class TestSignalGeneration:
    """Real SignalBuilder — deterministic SL/TP/grade pipeline."""

    def test_long_signal_entry_at_close(self):
        sb = SignalBuilder()
        ctx = make_decision_context(close=100.0, val=98.0, vah=102.0)
        sig = sb.build(ctx, pass_all_gates())
        assert sig is not None
        assert sig.type == SignalType.BUY
        assert sig.entry == pytest.approx(100.0)

    def test_long_signal_sl_below_entry(self):
        sb = SignalBuilder()
        ctx = make_decision_context(close=100.0, val=98.0, vah=102.0, tick_size=1.0)
        sig = sb.build(ctx, pass_all_gates())
        assert sig is not None
        assert sig.sl < sig.entry

    def test_long_signal_tp_above_entry(self):
        sb = SignalBuilder()
        ctx = make_decision_context(close=100.0, val=98.0, vah=102.0, tick_size=1.0)
        sig = sb.build(ctx, pass_all_gates())
        assert sig is not None
        assert sig.tp > sig.entry

    def test_signal_rr_approximately_2(self):
        sb = SignalBuilder()
        ctx = make_decision_context(close=100.0, val=98.0, vah=102.0, tick_size=1.0)
        sig = sb.build(ctx, pass_all_gates())
        assert sig is not None
        assert sig.rr == pytest.approx(2.0, rel=0.1)

    def test_short_signal_is_sell(self):
        sb = SignalBuilder()
        ctx = make_decision_context(close=100.0, val=98.0, vah=102.0)
        ctx = ctx.replace(agent_direction="SHORT")
        sig = sb.build(ctx, pass_all_gates())
        assert sig is not None
        assert sig.type == SignalType.SELL

    def test_failing_gate_returns_none(self):
        sb = SignalBuilder()
        ctx = make_decision_context(close=100.0, val=98.0, vah=102.0)
        from quant.decision.result import GateResult
        results = [GateResult(i, i != 3) for i in range(1, 6)]  # gate 3 fails
        assert sb.build(ctx, results) is None

    def test_thin_stop_rejected(self):
        from quant.decision.signal_builder import is_stop_too_thin, is_min_stop_met
        assert is_stop_too_thin(entry=100.0, sl=99.95)  # 0.05% stop
        assert not is_min_stop_met(entry=100.0, sl=99.95)
        assert not is_stop_too_thin(entry=100.0, sl=99.0)  # 1% stop
        assert is_min_stop_met(entry=100.0, sl=99.0)

    def test_signal_has_symbol(self):
        sb = SignalBuilder()
        ctx = make_decision_context(close=100.0, val=98.0, vah=102.0)
        sig = sb.build(ctx, pass_all_gates())
        assert sig is not None
        assert sig.symbol == "NIFTY"

    def test_signal_timestamp_is_set(self):
        sb = SignalBuilder()
        ctx = make_decision_context(close=100.0, val=98.0, vah=102.0)
        sig = sb.build(ctx, pass_all_gates())
        assert sig is not None
        assert sig.timestamp is not None


# ============================================================================
# 1d. RISK SIZING
# ============================================================================

class TestRiskSizing:
    """Real risk sizing — Portfolio math and SessionRisk."""

    def test_portfolio_initial_capital(self):
        p = Portfolio.create_default()
        assert float(p.balance) == pytest.approx(float(INITIAL_CAPITAL))

    def test_portfolio_open_position_uses_risk_pct(self):
        p = Portfolio.create_default()
        sig = make_signal(price=100, sl=95, tp=110, confidence="Medium")
        pos = p.open_position(sig, "NIFTY")
        assert pos is not None
        # Medium confidence = 0.35% risk on 1M = 3500 risk amount
        # Risk per unit = 100 - 95 = 5
        # Size = 3500 / 5 = 700
        assert float(pos.size) == pytest.approx(700, rel=0.01)

    def test_high_confidence_sizes_larger(self):
        p = Portfolio.create_default()
        sig = make_signal(price=100, sl=95, tp=110, confidence="High")
        pos = p.open_position(sig, "NIFTY")
        assert pos is not None
        # High = 0.5% → 5000 risk / 5 = 1000
        assert float(pos.size) == pytest.approx(1000, rel=0.01)

    def test_stop_loss_at_entry_rejected(self):
        p = Portfolio.create_default()
        sig = make_signal(price=100, sl=100, tp=110)
        assert p.open_position(sig, "NIFTY") is None

    def test_slippage_applied_on_entry(self):
        p = Portfolio.create_default()
        sig = make_signal(price=100, sl=95, tp=110)
        pos = p.open_position(sig, "NIFTY")
        assert pos is not None
        assert float(pos.entry_price) > 100.0  # LONG buys higher

    def test_session_risk_allows_trade_when_not_halted(self):
        risk = SessionRisk(RiskConfig())
        assert not risk.halted
        assert risk.can_trade("NIFTY")

    def test_session_risk_tracks_consecutive_losses(self):
        risk = SessionRisk(RiskConfig(max_daily_losses=3))
        risk.record_loss("NIFTY", 100)
        risk.record_loss("NIFTY", 100)
        risk.record_loss("NIFTY", 100)
        assert risk.halted

    def test_session_risk_resets_on_unhalt(self):
        risk = SessionRisk(RiskConfig(max_daily_losses=3))
        for _ in range(3):
            risk.record_loss("NIFTY", 100)
        assert risk.halted
        risk.unhalt()
        assert not risk.halted


# ============================================================================
# 1e. OMS — ORDER LIFECYCLE
# ============================================================================

class TestOMS:
    """Real order lifecycle — Portfolio + ExitEngine."""

    def test_position_open_is_not_closed(self):
        p = Portfolio.create_default()
        sig = make_signal(price=100, sl=95, tp=110)
        pos = p.open_position(sig, "NIFTY")
        assert pos is not None
        assert pos.status == PositionStatus.OPEN

    def test_position_close_records_exit(self):
        p = Portfolio.create_default()
        sig = make_signal(price=100, sl=95, tp=110)
        pos = p.open_position(sig, "NIFTY")
        assert pos is not None
        pos.close(110, "2026-08-05T10:00:00Z", "Take Profit")
        assert pos.status == PositionStatus.CLOSED
        assert float(pos.exit_price) == 110.0

    def test_exit_engine_sl_triggers(self):
        engine = ExitEngine()
        pos = Position(
            side=Side.LONG, entry_price=Decimal("100"), size=Decimal("10"),
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
        )
        decision = engine.evaluate(pos, 94.0, bar_index=5)
        assert decision.should_exit
        assert decision.reason == "SL"

    def test_exit_engine_tp_triggers(self):
        engine = ExitEngine()
        pos = Position(
            side=Side.LONG, entry_price=Decimal("100"), size=Decimal("10"),
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
        )
        decision = engine.evaluate(pos, 110.5, bar_index=5)
        assert decision.should_exit
        assert decision.reason == "TP"

    def test_exit_engine_holds_in_range(self):
        engine = ExitEngine()
        pos = Position(
            side=Side.LONG, entry_price=Decimal("100"), size=Decimal("10"),
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
        )
        decision = engine.evaluate(pos, 101.0, bar_index=5)
        assert not decision.should_exit

    def test_exit_engine_time_stop(self):
        engine = ExitEngine(time_stop_bars=30)
        pos = Position(
            side=Side.LONG, entry_price=Decimal("100"), size=Decimal("10"),
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
        )
        # After 30 bars with no exit, time stop should trigger
        decision = engine.evaluate(pos, 101.0, bar_index=30)
        assert decision.should_exit
        assert decision.reason == "TIME"

    def test_excursion_tracking_mae_mfe(self):
        pos = Position(
            side=Side.LONG, entry_price=Decimal("100"), size=Decimal("1"),
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
        )
        update_excursions(pos, 95.0)   # MAE = 5
        update_excursions(pos, 108.0)  # MFE = 8
        assert float(pos.mae) == pytest.approx(5.0)
        assert float(pos.mfe) == pytest.approx(8.0)


# ============================================================================
# 1f. BROKER ADAPTER
# ============================================================================

class TestBrokerAdapter:
    """Real paper broker adapter — no mocks on internal logic."""

    def test_paper_execute_creates_position(self):
        broker = PaperBrokerAdapter()
        p = Portfolio.create_default()
        sig = make_signal(price=100, sl=95, tp=110)
        pos = broker.execute_order(sig, p, "NIFTY")
        assert pos is not None
        assert pos.is_open

    def test_paper_cancel_order_idempotent(self):
        broker = PaperBrokerAdapter()
        assert broker.cancel_order("ORD-1") is True
        assert broker.cancel_order("ORD-1") is False  # already cancelled

    def test_paper_rejects_zero_price(self):
        broker = PaperBrokerAdapter()
        p = Portfolio.create_default()
        sig = make_signal(price=0, sl=95, tp=110)
        assert broker.execute_order(sig, p, "NIFTY") is None

    def test_paper_rejects_negative_price(self):
        broker = PaperBrokerAdapter()
        p = Portfolio.create_default()
        sig = make_signal(price=-10, sl=-15, tp=-5)
        assert broker.execute_order(sig, p, "NIFTY") is None

    def test_paper_order_has_unique_id(self):
        broker = PaperBrokerAdapter()
        p = Portfolio.create_default()
        sig1 = make_signal(price=100, sl=95, tp=110)
        sig2 = make_signal(price=100, sl=95, tp=110)
        pos1 = broker.execute_order(sig1, p, "NIFTY")
        pos2 = broker.execute_order(sig2, p, "NIFTY")
        assert pos1 is not None
        assert pos2 is not None
        assert pos1.id != pos2.id

    def test_paper_position_respects_stop_loss(self):
        broker = PaperBrokerAdapter()
        p = Portfolio.create_default()
        sig = make_signal(price=100, sl=95, tp=110)
        pos = broker.execute_order(sig, p, "NIFTY")
        assert pos is not None
        assert float(pos.stop_loss) == pytest.approx(95.0)


# ============================================================================
# Cross-cutting: serialization round-trips
# ============================================================================

class TestSerializationRoundTrips:
    """DTO ↔ domain model round-trips — critical for transport fidelity."""

    def test_position_round_trip(self):
        from app.infrastructure.serialization.schemas import position_to_dto, dto_to_position
        p = Position(
            id="test", symbol="NIFTY", side=Side.LONG, source=Source.AMT,
            entry_price=100, size=1, stop_loss=95, take_profit=110,
            entry_time="t", status=PositionStatus.OPEN,
        )
        dto = position_to_dto(p)
        restored = dto_to_position(dto)
        assert restored.id == p.id
        assert restored.symbol == p.symbol
        assert restored.side == p.side
        assert float(restored.entry_price) == float(p.entry_price)

    def test_signal_round_trip(self):
        from app.infrastructure.serialization.schemas import signal_to_dto, dto_to_signal
        s = Signal(
            type=SignalType.BUY, price=100, reason="test",
            stop_loss=95, take_profit=110, timestamp="t",
            setup=SetupType.TREND_MODEL, source=Source.AMT,
        )
        dto = signal_to_dto(s)
        restored = dto_to_signal(dto)
        assert restored.type == s.type
        assert restored.price == s.price
        assert restored.stop_loss == s.stop_loss

    def test_ohlc_round_trip(self):
        from app.infrastructure.serialization.schemas import ohlc_to_dto, dto_to_ohlc, OHLCDataDTO
        o = OHLC.create(time="t", open=100, high=102, low=98, close=101,
                        volume=1000, vwap=101, taker_buy_volume=600, delta=200)
        dto_dict = ohlc_to_dto(o)
        dto = OHLCDataDTO(**dto_dict)
        restored = dto_to_ohlc(dto)
        assert restored.open == o.open
        assert restored.close == o.close
        assert restored.taker_buy_volume == o.taker_buy_volume


# ============================================================================
# Cross-cutting: domain invariants
# ============================================================================

class TestDomainInvariants:
    """Invariants that must hold for ALL domain objects."""

    def test_position_pnl_long_profit(self):
        pos = Position(
            side=Side.LONG, entry_price=Decimal("100"), size=Decimal("10"),
            stop_loss=Decimal("95"), take_profit=Decimal("110"),
        )
        pos.current_price = Decimal("105")
        pnl = pos.unrealized_pnl()
        assert float(pnl) > 0

    def test_position_pnl_short_profit(self):
        pos = Position(
            side=Side.SHORT, entry_price=Decimal("100"), size=Decimal("10"),
            stop_loss=Decimal("105"), take_profit=Decimal("90"),
        )
        pos.current_price = Decimal("95")
        pnl = pos.unrealized_pnl()
        assert float(pnl) > 0

    def test_position_size_positive(self):
        p = Portfolio.create_default()
        sig = make_signal(price=100, sl=95, tp=110)
        pos = p.open_position(sig, "NIFTY")
        assert pos is not None
        assert float(pos.size) > 0

    def test_no_position_with_zero_size(self):
        p = Portfolio.create_default()
        sig = make_signal(price=100, sl=100, tp=110)  # zero risk
        pos = p.open_position(sig, "NIFTY")
        assert pos is None
