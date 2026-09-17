"""WS-REALISM guards: min-stop distance + max-size clamp in SignalBuilder."""

import pytest

from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.signal_builder import (
    MAX_POSITION_QUANTITY,
    MIN_STOP_DISTANCE_PCT,
    SignalBuilder,
    clamp_quantity,
    is_min_stop_met,
    is_stop_too_thin,
)
from quant.decision.stops import min_stop_distance


def _ctx(close, val, step, nearest):
    bar = Bar(time="t", open=close, high=close, low=close, close=close, volume=100.0)
    return DecisionContext(
        state=None, bar=bar, symbol="SYM", time_str="t",
        agent_direction="LONG", agent_probability=0.7,
        poc=close, vah=val + 2 * step, val=val, tick_size=0.05,
    )


def _pass_results():
    return [GateResult(i, True) for i in range(1, 8)]


def test_defaults_are_exported_constants():
    assert MIN_STOP_DISTANCE_PCT == 0.1
    assert MAX_POSITION_QUANTITY == 1000
    sb = SignalBuilder()
    assert sb.min_stop_distance_pct == MIN_STOP_DISTANCE_PCT
    assert sb.max_position_quantity == MAX_POSITION_QUANTITY


def test_thin_stop_setup_is_rejected():
    # The anchor walks to a deeper level when the nearest is noise, so on a
    # normal-priced instrument a thin nearest stop no longer blocks the trade.
    # On a high-priced instrument even the fallback (5 ticks) sits inside the
    # 0.1% noise band, so the builder must refuse rather than emit a noise stop.
    sb = SignalBuilder()
    ctx = _ctx(close=56000.0, val=55999.9, step=0.1, nearest=55999.8)
    assert sb.build(ctx, _pass_results()) is None


def test_thin_nearest_anchor_reanchors_to_a_valid_level():
    # entry 104.92, nearest VAL 104.919 is noise-thin, but the bar provides a
    # deeper structural level, so the builder emits with a valid stop.
    sb = SignalBuilder()
    ctx = _ctx(close=104.92, val=104.919, step=0.01, nearest=104.9)
    sig = sb.build(ctx, _pass_results())
    assert sig is not None
    assert abs(sig.entry - sig.sl) >= min_stop_distance(sig.entry, ctx.tick_size)


def test_thin_stop_pure_function():
    assert is_stop_too_thin(104.92, 104.90) is True
    assert is_stop_too_thin(100.0, 99.9) is True
    assert is_stop_too_thin(100.0, 99.89) is False


def test_healthy_setup_still_builds():
    # SL 1.9% away (100 -> 98.10) -> builds normally.
    sb = SignalBuilder()
    ctx = _ctx(close=100.0, val=98.0, step=1.0, nearest=98.0)
    s = sb.build(ctx, _pass_results())
    assert s is not None and s.type == "LONG"
    assert s.sl == pytest.approx(98.10)


def test_override_min_stop_allows_thin_stop():
    # Explicit override (min_stop_distance_pct=0) permits the thin stop.
    sb = SignalBuilder(min_stop_distance_pct=0.0)
    ctx = _ctx(close=104.92, val=104.919, step=0.01, nearest=104.9)
    assert sb.build(ctx, _pass_results()) is not None


def test_quantity_is_clamped_to_max():
    # equity 100k @ 1% risk, |entry-sl| = 0.02 -> 50k units -> clamped to 1000.
    # SignalBuilder.size was removed (duplicate sizing authority); the clamp
    # ceiling is applied by the engine via clamp_quantity after
    # SessionRisk.position_size.
    assert clamp_quantity(50_000.0) == MAX_POSITION_QUANTITY


def test_healthy_quantity_unclamped():
    # The surviving sizing authority (SessionRisk.position_size): qty is
    # equity * risk_pct / |entry-sl| for a healthy (non-thin) stop, with the
    # risk_pct sourced from the risk engine (not a second formula in
    # SignalBuilder).
    from quant.execution.risk import SessionRisk

    # Pin a mid-week day: DAY_OF_WEEK_MULTIPLIER halves risk on Mon/Fri, so an unpinned day makes this assertion calendar-dependent.
    risk = SessionRisk(starting_equity=100_000.0, base_risk_pct=0.01, day_of_week=1)
    qty = risk.position_size(entry=100.0, sl=97.0)
    risk_amount = 100_000.0 * risk._risk_per_trade_pct()
    assert qty == pytest.approx(risk_amount / 3.0)
    assert 0 < qty <= MAX_POSITION_QUANTITY


def test_max_quantity_override():
    # The engine's ceiling override on the shared clamp.
    assert clamp_quantity(50_000.0, max_quantity=500) == 500


def test_is_min_stop_met_defaults_match_constant():
    # Positive form of is_stop_too_thin with the same 0.1% default.
    assert is_min_stop_met(100.0, 99.89) is True
    assert is_min_stop_met(100.0, 97.0) is True
    assert is_min_stop_met(104.92, 104.90) is False
    assert is_min_stop_met(100.0, 99.9) is False


def test_is_min_stop_met_negates_is_stop_too_thin():
    assert is_min_stop_met(100.0, 99.9) is not is_stop_too_thin(100.0, 99.9)
    assert is_min_stop_met(100.0, 99.89) is not is_stop_too_thin(100.0, 99.89)


def test_is_min_stop_met_override():
    assert is_min_stop_met(104.92, 104.90, min_stop_distance_pct=0.0) is True


def test_clamp_quantity_defaults_match_constant():
    assert clamp_quantity(MAX_POSITION_QUANTITY + 1) == MAX_POSITION_QUANTITY
    assert clamp_quantity(MAX_POSITION_QUANTITY) == MAX_POSITION_QUANTITY
    assert clamp_quantity(1.0) == 1.0
    assert clamp_quantity(MAX_POSITION_QUANTITY + 1, max_quantity=0) == MAX_POSITION_QUANTITY + 1
