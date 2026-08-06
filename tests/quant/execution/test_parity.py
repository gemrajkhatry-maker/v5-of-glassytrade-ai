"""Parity tests — prove moved quant.execution.* modules match their legacy twins.

Each test drives the legacy module via its re-export shim (``app.domain.*``)
and the moved module (``quant.execution.*``) with identical inputs and asserts
byte-identical observable output via ``assert_parity``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.quant.parity import assert_parity

from quant.contracts.entities import Position
from quant.contracts.enums import Side, CushionState
from quant.execution.trail import TrailEngine as QuantTrailEngine


# ---------------------------------------------------------------------------
# TrailEngine
# ---------------------------------------------------------------------------


def _trail_position(side: Side = Side.LONG) -> Position:
    pos = Position(
        symbol="CRUDEOIL",
        side=side,
        entry_price=Decimal("6500.0"),
        size=Decimal("100"),
        stop_loss=Decimal("6480.0"),
        initial_stop=Decimal("6480.0"),
        take_profit=Decimal("6540.0"),
    )
    pos.partial_taken = True
    return pos


def _run_atr_trail(engine_cls) -> dict:
    engine = engine_cls()
    pos = _trail_position()
    engine.apply_atr_trail(pos, 6520.0)  # arm at 1R
    engine.apply_atr_trail(pos, 6540.0)  # trail to 2R
    return {
        "stop_loss": float(pos.stop_loss),
        "peak_profit": float(pos.peak_profit),
        "atr_trail_active": pos.atr_trail_active,
        "cushion_state": pos.cushion_state.value,
    }


def _run_vwap_trail(engine_cls) -> dict:
    engine = engine_cls()
    pos = _trail_position()
    engine.apply_vwap_trail(
        pos, current_price=6530.0,
        vwap=6495.0, vwap_upper_1=6505.0, vwap_lower_1=6485.0,
        vwap_upper_2=6515.0, vwap_lower_2=6475.0,
    )
    return {"stop_loss": float(pos.stop_loss)}


def _run_imbalance_tighten(engine_cls) -> dict:
    engine = engine_cls()
    pos = _trail_position()
    imbalances = [type("Imbalance", (), {"direction": "SELL"})()]
    tightened = engine.apply_imbalance_tighten(pos, imbalances, current_price=6510.0)
    return {"tightened": tightened, "stop_loss": float(pos.stop_loss)}


def _run_cvd_breakeven(engine_cls) -> dict:
    engine = engine_cls()
    pos = _trail_position()
    moved = engine.apply_cvd_breakeven(pos, cvd_slope=0.6)
    return {"moved": moved, "stop_loss": float(pos.stop_loss), "breakeven_set": pos.breakeven_set}


def _run_adjust_sl(engine_cls) -> dict:
    engine = engine_cls()
    pos = _trail_position()
    ok = engine.adjust_stop_loss(pos, 6485.123)
    return {"ok": ok, "stop_loss": float(pos.stop_loss)}


def test_trail_atr_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.trail_engine").TrailEngine
    assert_parity(
        lambda: _run_atr_trail(legacy),
        lambda: _run_atr_trail(QuantTrailEngine),
    )


def test_trail_vwap_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.trail_engine").TrailEngine
    assert_parity(
        lambda: _run_vwap_trail(legacy),
        lambda: _run_vwap_trail(QuantTrailEngine),
    )


def test_trail_imbalance_tighten_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.trail_engine").TrailEngine
    assert_parity(
        lambda: _run_imbalance_tighten(legacy),
        lambda: _run_imbalance_tighten(QuantTrailEngine),
    )


def test_trail_cvd_breakeven_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.trail_engine").TrailEngine
    assert_parity(
        lambda: _run_cvd_breakeven(legacy),
        lambda: _run_cvd_breakeven(QuantTrailEngine),
    )


def test_trail_adjust_sl_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.trail_engine").TrailEngine
    assert_parity(
        lambda: _run_adjust_sl(legacy),
        lambda: _run_adjust_sl(QuantTrailEngine),
    )


# ---------------------------------------------------------------------------
# ScaleManager
# ---------------------------------------------------------------------------


def _scale_position() -> Position:
    pos = Position(
        id="test_scale",
        symbol="NIFTY",
        side=Side.LONG,
        entry_price=Decimal("24800"),
        stop_loss=Decimal("24700"),
        take_profit=Decimal("24900"),
    )
    pos.scale_step = 1
    pos.scale_confirm_price = Decimal("24850")
    pos.scale_breakout_price = Decimal("24900")
    return pos


def _run_scale_sequence(engine_cls) -> dict:
    engine = engine_cls()
    pos = _scale_position()
    step2 = engine.check_scale_in(pos, 24850.0)
    status2 = engine.get_scale_status(pos)
    step3 = engine.check_scale_in(pos, 24900.0)
    status3 = engine.get_scale_status(pos)
    return {
        "step2": step2,
        "step3": step3,
        "scale_step": pos.scale_step,
        "remaining2": status2["remaining_fraction"],
        "remaining3": status3["remaining_fraction"],
    }


def test_scale_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.scale_manager").ScaleManager
    from quant.execution.scale import ScaleManager as QuantScale
    assert_parity(
        lambda: _run_scale_sequence(legacy),
        lambda: _run_scale_sequence(QuantScale),
    )


# ---------------------------------------------------------------------------
# PyramidManager
# ---------------------------------------------------------------------------


def _run_pyramid(engine_cls) -> dict:
    engine = engine_cls()
    result = engine.check_pyramid(
        entry_price=100.0, current_price=101.0, is_long=True,
        aggression_score=3.5, add_count=0, entry_lvns=[99.0],
        current_lvn=101.0, current_sl=99.0,
    )
    if result is None:
        return {"none": True}
    return {"mult": result.size_multiplier, "level": result.level, "sl": result.unified_sl}


def test_pyramid_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.pyramid_manager").PyramidManager
    from quant.execution.pyramid import PyramidManager as QuantPyramid
    assert_parity(
        lambda: _run_pyramid(legacy),
        lambda: _run_pyramid(QuantPyramid),
    )


# ---------------------------------------------------------------------------
# PartitionExitManager
# ---------------------------------------------------------------------------


def _run_partition(engine_cls, state_cls) -> dict:
    engine = engine_cls()
    state = state_cls()
    signals = engine.check_exits(
        entry_price=100.0, initial_stop=99.0, take_profit=102.0,
        current_price=101.0, is_long=True, cvd_slope=1.0, state=state,
    )
    return {
        "types": [s.exit_type for s in signals],
        "p1_taken": state.p1_taken,
        "p2_taken": state.p2_taken,
        "trail_sl": state.trail_sl,
        "be_set": state.breakeven_set,
    }


def test_partition_parity():
    import importlib
    legacy_mod = importlib.import_module("app.domain.fabio_ai.services.partition_exit_manager")
    from quant.execution.partition import (
        PartitionExitManager as QuantPartition,
        PartitionState as QuantState,
    )
    assert_parity(
        lambda: _run_partition(legacy_mod.PartitionExitManager, legacy_mod.PartitionState),
        lambda: _run_partition(QuantPartition, QuantState),
    )


# ---------------------------------------------------------------------------
# LossTracker
# ---------------------------------------------------------------------------


def _loss_sequence(engine_cls) -> dict:
    tracker = engine_cls(max_daily_losses=3)
    tracker.record_loss("NIFTY", stop_price=100.0)
    tracker.record_loss("NIFTY", stop_price=99.0)
    tracker.record_loss("NIFTY", stop_price=98.0)
    return {
        "limit_nifty": tracker.is_daily_limit_reached("NIFTY"),
        "limit_bn": tracker.is_daily_limit_reached("BANKNIFTY"),
        "blocked": tracker.should_block_entry("NIFTY", current_price=98.5, current_atr=1.0),
        "state": tracker.get_state(),
    }


def _dynamic_risk(engine_cls) -> dict:
    tracker = engine_cls()
    return {
        "neg": tracker.compute_dynamic_risk(100_000.0, -1000.0),
        "profit": tracker.compute_dynamic_risk(100_000.0, 5000.0),
        "huge": tracker.compute_dynamic_risk(100_000.0, 500_000.0),
    }


def test_loss_tracker_daily_limit_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.loss_tracker").LossTracker
    from quant.execution.loss_tracker import LossTracker as QuantLossTracker
    assert_parity(
        lambda: _loss_sequence(legacy),
        lambda: _loss_sequence(QuantLossTracker),
    )


def test_loss_tracker_dynamic_risk_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.loss_tracker").LossTracker
    from quant.execution.loss_tracker import LossTracker as QuantLossTracker
    assert_parity(
        lambda: _dynamic_risk(legacy),
        lambda: _dynamic_risk(QuantLossTracker),
    )


# ---------------------------------------------------------------------------
# SessionRiskManager
# ---------------------------------------------------------------------------


def _session_sequence(engine_cls) -> dict:
    mgr = engine_cls()
    mgr.record_trade(-10)
    mgr.record_trade(-10)
    halted = mgr.can_trade
    mgr.record_trade(50)
    return {
        "tier": mgr.risk_tier.value,
        "halted": halted,
        "can_trade": mgr.can_trade,
        "sl_pct": mgr.stop_loss_pct,
        "consec_losses": mgr.consecutive_losses,
        "state": mgr.to_dict(),
    }


def test_session_risk_manager_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.session_risk_manager").SessionRiskManager
    from quant.execution.session_risk_manager import SessionRiskManager as QuantSrm
    assert_parity(
        lambda: _session_sequence(legacy),
        lambda: _session_sequence(QuantSrm),
    )


# ---------------------------------------------------------------------------
# KillSwitch
# ---------------------------------------------------------------------------


def _kill_switch_sequence(engine_cls) -> dict:
    ks = engine_cls()
    ks.halt()
    halted = ks.is_halted
    ks.resume()
    return {"halted": halted, "resumed": ks.is_halted}


def test_kill_switch_parity():
    import importlib
    legacy = importlib.import_module("app.domain.trading.services.kill_switch").KillSwitch
    from quant.execution.kill_switch import KillSwitch as QuantKillSwitch
    assert_parity(
        lambda: _kill_switch_sequence(legacy),
        lambda: _kill_switch_sequence(QuantKillSwitch),
    )


# ---------------------------------------------------------------------------
# RiskManager
# ---------------------------------------------------------------------------


def _make_signal(price="100", sl="95"):
    from quant.contracts.enums import SignalType, Source, SetupType
    return (
        SignalType.BUY, price, sl, "110", "2026-01-01T10:00:00Z",
        SetupType.TREND_MODEL, Source.AMT,
    )


def _rm_validate(engine_cls) -> dict:
    from quant.contracts.enums import SignalType, Source, SetupType
    from quant.contracts.entities import Signal
    from quant.contracts.aggregates import Portfolio

    rm = engine_cls()
    portfolio = Portfolio.create_default()
    sig = Signal(
        type=SignalType.BUY, price=100, reason="test",
        stop_loss=95, take_profit=110, timestamp="t",
        setup=SetupType.TREND_MODEL, source=Source.AMT,
    )
    result = {}
    result["clean"] = rm.validate(sig, portfolio)
    portfolio.open_position(sig, "BTCUSDT")
    sig2 = Signal(
        type=SignalType.BUY, price=100, reason="test",
        stop_loss=95, take_profit=110, timestamp="t",
        setup=SetupType.TREND_MODEL, source=Source.AMT,
    )
    result["dup_source"] = rm.validate(sig2, portfolio)
    result["zero_risk"] = rm.validate(
        Signal(
            type=SignalType.BUY, price=100, reason="test",
            stop_loss=100, take_profit=110, timestamp="t",
            setup=SetupType.TREND_MODEL, source=Source.PREDICTION,
        ),
        portfolio,
    )
    return result


def _rm_record_trade(engine_cls) -> dict:
    from quant.contracts.aggregates import Portfolio
    rm = engine_cls()
    portfolio = Portfolio.create_default()
    rm.record_trade_result(-100.0, portfolio)
    rm.record_trade_result(-100.0, portfolio)
    rm.record_trade_result(-100.0, portfolio)
    return {
        "halted": rm.is_halted,
        "reason": rm.halt_reason,
        "consec": rm._daily.consecutive_losses,
        "total_trades": rm._daily.total_trades,
    }


def test_risk_manager_validate_parity():
    import importlib
    legacy = importlib.import_module("app.domain.trading.services.risk_manager").RiskManager
    from quant.execution.risk_manager import RiskManager as QuantRiskManager
    assert_parity(
        lambda: _rm_validate(legacy),
        lambda: _rm_validate(QuantRiskManager),
    )


def test_risk_manager_record_trade_result_parity():
    import importlib
    legacy = importlib.import_module("app.domain.trading.services.risk_manager").RiskManager
    from quant.execution.risk_manager import RiskManager as QuantRiskManager
    assert_parity(
        lambda: _rm_record_trade(legacy),
        lambda: _rm_record_trade(QuantRiskManager),
    )


# ---------------------------------------------------------------------------
# SignalValidator
# ---------------------------------------------------------------------------


def _run_signal_validator(validator_cls) -> dict:
    from quant.contracts.enums import SignalType, SetupType, Source
    from quant.contracts.entities import Signal
    from quant.contracts.value_objects import OHLC

    signal = Signal(
        type=SignalType.BUY, price=100, reason="test",
        stop_loss=90, take_profit=110, timestamp="2026-01-01T10:00:00Z",
        setup=SetupType.TREND_MODEL, source=Source.AMT,
    )
    tick = OHLC(
        time="2026-01-01T10:05:00Z",
        open=100.0, high=101.0, low=99.0, close=100.0,
        volume=1000, vwap=100.0,
        taker_buy_volume=600, delta=200,
    )
    return {
        "stale": validator_cls.validate_staleness(signal, tick, max_age_seconds=60),
        "fresh": validator_cls.validate_staleness(signal, tick),
        "direction_ok": validator_cls.validate_direction(signal, "LONG"),
        "direction_bad": validator_cls.validate_direction(signal, "SHORT"),
        "vwap_ok": validator_cls.validate_vwap_extreme(signal, 0.0, 0.0),
        "vwap_extreme": validator_cls.validate_vwap_extreme(signal, 50.0, 25.0),
        "all": validator_cls.validate_all(signal, tick, "LONG"),
    }


def test_signal_validator_parity():
    import importlib
    legacy = importlib.import_module("app.domain.trading.services.signal_validator").SignalValidator
    from quant.execution.signal_validator import SignalValidator as QuantSignalValidator
    assert_parity(
        lambda: _run_signal_validator(legacy),
        lambda: _run_signal_validator(QuantSignalValidator),
    )


# ---------------------------------------------------------------------------
# CircuitBreakers
# ---------------------------------------------------------------------------


def _run_circuit_breakers(engine_cls, reason_cls) -> dict:
    cb = engine_cls(equity=1_000_000.0)
    results = []
    for losses, pnl, cumulative in [(3, -100.0, 0.0), (2, -100.0, 0.0), (5, 100.0, 0.0)]:
        r = cb.evaluate(consecutive_losses=losses, session_pnl=pnl, cumulative_account_pnl=cumulative)
        results.append({"locked": r.is_locked, "reason": r.reason.value, "detail": r.detail})
    account_breach = cb.evaluate(
        consecutive_losses=1, session_pnl=1000.0, cumulative_account_pnl=-30_000.0
    )
    results.append({"locked": account_breach.is_locked, "reason": account_breach.reason.value})
    return {"results": results}


def test_circuit_breakers_parity():
    import importlib
    legacy_mod = importlib.import_module("app.domain.services.circuit_breakers")
    from quant.execution.circuit_breakers import (
        CircuitBreakers as QuantCircuitBreakers,
        BreakerReason as QuantBreakerReason,
    )
    assert_parity(
        lambda: _run_circuit_breakers(legacy_mod.CircuitBreakers, legacy_mod.BreakerReason),
        lambda: _run_circuit_breakers(QuantCircuitBreakers, QuantBreakerReason),
    )


# ---------------------------------------------------------------------------
# RiskSizingEngine
# ---------------------------------------------------------------------------


def _run_risk_sizing(engine_cls) -> dict:
    engine = engine_cls()
    result = engine.calculate(
        equity=1_000_000,
        session_pnl=0,
        consecutive_losses=0,
        underlying="NIFTY",
        entry_price=24000,
        stop_price=23900,
        target_price=24400,
        direction="LONG",
    )
    import dataclasses
    return dataclasses.asdict(result)


def test_risk_sizing_calculate_parity():
    import importlib
    legacy = importlib.import_module("app.domain.services.risk_sizing_engine").RiskSizingEngine
    from quant.execution.risk_sizing import RiskSizingEngine as QuantRiskSizing
    assert_parity(
        lambda: _run_risk_sizing(legacy),
        lambda: _run_risk_sizing(QuantRiskSizing),
    )


# ---------------------------------------------------------------------------
# RiskTierEngine
# ---------------------------------------------------------------------------


def _run_risk_tier(engine_cls, premium_cls) -> dict:
    engine = engine_cls(capital=5_000_000)
    engine.record_trade(1.5)
    engine.record_trade(1.5)
    premium = premium_cls(
        aggression_score=4.0,
        lvn_strength=0.9,
        cvd_divergence=True,
        is_second_drive=True,
        ml_probability=0.70,
    )
    engine.record_trade(0.5, premium_check=premium)
    state_a = engine.get_state()
    engine.record_trade(-1.0)
    engine.record_trade(-1.0)
    engine.record_trade(-1.0)
    return {
        "tier": engine.tier.value,
        "risk_pct": engine.risk_pct,
        "risk_amount": engine.risk_amount,
        "is_halted": engine.is_halted,
        "halt_reason": engine.halt_reason,
        "state_a_tier": state_a.tier.value,
        "state_a_pct": state_a.risk_pct,
        "state": engine.get_state(),
    }


def test_risk_tier_parity():
    import importlib
    legacy_mod = importlib.import_module("app.domain.services.risk_tier_engine")
    from quant.execution.risk_tier import (
        RiskTierEngine as QuantRiskTier,
        TierAPremiumCheck as QuantPremium,
    )
    assert_parity(
        lambda: _run_risk_tier(legacy_mod.RiskTierEngine, legacy_mod.TierAPremiumCheck),
        lambda: _run_risk_tier(QuantRiskTier, QuantPremium),
    )


# ---------------------------------------------------------------------------
# TradeCosts
# ---------------------------------------------------------------------------


def _run_trade_costs(fn) -> dict:
    import dataclasses
    return dataclasses.asdict(fn(notional=600_000, slippage_bps=15.0, is_sell=True))


def test_trade_costs_parity():
    import importlib
    legacy = importlib.import_module("app.domain.services.trade_costs").compute_trade_costs
    from quant.execution.trade_costs import compute_trade_costs as quant_compute
    assert_parity(
        lambda: _run_trade_costs(legacy),
        lambda: _run_trade_costs(quant_compute),
    )


# ---------------------------------------------------------------------------
# ExitEngine.check_position
# ---------------------------------------------------------------------------


def _exit_position() -> Position:
    return Position(
        id="P1",
        symbol="NIFTY",
        side=Side.LONG,
        entry_price=Decimal("100.0"),
        stop_loss=Decimal("95.0"),
        take_profit=Decimal("115.0"),
        initial_stop=Decimal("95.0"),
    )


def _run_check_position(engine_cls) -> dict:
    engine = engine_cls()
    pos = _exit_position()
    sig = engine.check_position(pos, 95.0)
    return {
        "sig": (sig.position_id, sig.reason, sig.exit_price) if sig else None,
        "cushion": pos.cushion_state.value,
    }


def _run_check_position_hold(engine_cls) -> dict:
    engine = engine_cls()
    pos = _exit_position()
    pos.entry_time = "2026-01-01T00:00:00Z"
    sigs = [engine.check_position(pos, 102.0) for _ in range(6)]
    return {
        "sig": (sigs[-1].position_id, sigs[-1].reason, sigs[-1].exit_price) if sigs[-1] else None,
        "tick_count": pos.tick_count,
        "mfe": float(pos.mfe),
    }


def test_exit_engine_stop_loss_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.exit_engine").ExitEngine
    from quant.execution.exit_engine import ExitEngine as QuantExitEngine
    assert_parity(
        lambda: _run_check_position(legacy),
        lambda: _run_check_position(QuantExitEngine),
    )


def test_exit_engine_hold_parity():
    import importlib
    legacy = importlib.import_module("app.domain.fabio_ai.services.exit_engine").ExitEngine
    from quant.execution.exit_engine import ExitEngine as QuantExitEngine
    assert_parity(
        lambda: _run_check_position_hold(legacy),
        lambda: _run_check_position_hold(QuantExitEngine),
    )
