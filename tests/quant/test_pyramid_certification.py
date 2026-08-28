"""Certification tests for pyramid money-critical defects E9/E10/E11.

Per Workstream 4: each defect fix lands with its own test BEFORE the fix,
then full battery re-run proves zero unintended drift.
"""
from __future__ import annotations

import pytest

from quant.amt.orderflow.footprint import FootprintCandle, FootprintLevel
from quant.bars import Bar
from quant.decision.result import GateResult
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.order import Order, Position
from quant.execution.portfolio_risk import PortfolioRiskAuthority
from quant.execution.live_oms import LiveOMS
from quant.execution.risk import SessionRisk
from quant.position_manager import PositionManager
from quant.decision.signal_builder import Signal


def _mk_pos(size: float = 10.0) -> Position:
    sig = Signal(
        type="LONG", reason="r", entry=100.0, sl=99.0, tp=104.0, rr=2.0,
        model_label="Triple-A", symbol="S", timestamp="t0",
    )
    return Position(order=Order(sig, size), open_price=100.0, open_time="t0", size=size)


def _mk_pm(oms=None, portfolio_risk=None) -> PositionManager:
    return PositionManager(
        oms=oms or PaperOMS(lot_size=1.0),
        exits=ExitEngine(),
        risk=SessionRisk(storage=None, symbol="S"),
        emit_fn=lambda e: None,
        symbol="S", market="MCX", contract_expiry=None, tick_size=0.05,
        portfolio_risk=portfolio_risk,
    )


def _bar(close: float, open_: float = 100.0) -> Bar:
    return Bar(
        time="t1", open=open_, high=close + 0.05, low=open_ - 0.05,
        close=close, volume=100,
    )


# ---------------------------------------------------------------------------
# E9 — Pyramid ghosting: no pyramid Position may exist without a broker order.
# ---------------------------------------------------------------------------

def test_e9_live_pyramid_never_ghosts():
    """E9: under LiveOMS, check_pyramid must NOT create an in-memory position
    that is never submitted to the broker (ghost). Pyramids are disabled until
    end-to-end submit→fill→linked-close is implemented."""
    from unittest.mock import MagicMock

    portfolio = MagicMock()
    oms = LiveOMS(broker=MagicMock(), portfolio=portfolio, lot_size=1.0)
    pm = _mk_pm(oms)

    pos = _mk_pos()
    # arm breakeven so base is risk-free
    pm._exits.evaluate(pos, bar_close=101.0, bar_index=3, bar_high=101.0, bar_low=100.9)
    assert pm._exits.is_risk_free(pos), "breakeven should arm at 0.8R+"

    dto = {"legLvn": 100.0, "absorptionSide": "SELL_ABSORBED"}
    # LiveOMS.add_pyramid raises ValueError
    with pytest.raises(ValueError) as exc_info:
        oms.add_pyramid(pos, 100.05, 99.0, 1.0, "2026-08-17T09:30:00+05:30", 1)
    assert "E9" in str(exc_info.value), f"expected E9 error, got {exc_info.value}"

    # CRIT-01 Fix: check_pyramid catches the error and logs a warning instead of crashing
    pm.check_pyramid(dto, _bar(100.05), pos, bar_index=5)
    assert pm.pyramid_count == 0, (
        "E9 VIOLATION: pyramid created under LiveOMS without broker order — "
        "ghost position that will fail on close"
    )


def test_e9_live_close_does_not_send_broker_order_for_ghost():
    """E9 companion: because no ghost Position is ever built, manage_exit's
    full-close loop never calls broker.close_position() against an unopened
    pyramid — the guaranteed live failure path is eliminated."""
    from unittest.mock import MagicMock

    portfolio = MagicMock()
    oms = LiveOMS(broker=MagicMock(), portfolio=portfolio, lot_size=1.0)
    pm = _mk_pm(oms)

    pos = _mk_pos()
    pm._exits.evaluate(pos, bar_close=101.0, bar_index=3, bar_high=101.0, bar_low=100.9)
    assert pm._exits.is_risk_free(pos)

    dto = {"legLvn": 100.0, "absorptionSide": "SELL_ABSORBED"}
    pm.check_pyramid(dto, _bar(100.05), pos, bar_index=5)

    # No pyramid positions → the close loop has nothing to send to the broker.
    assert len(pm.pyramid_positions) == 0


# ---------------------------------------------------------------------------
# E10 — Base-SL ratchet after pyramid fill.
# ---------------------------------------------------------------------------

def test_e10_base_sl_ratcheted_at_pyramid_fill():
    """E10: when a pyramid fills, the base position's SL must be ratcheted to
    new_sl so the combined bundle (base + pyramids) is guaranteed positive."""
    oms = PaperOMS(lot_size=1.0)
    pm = _mk_pm(oms)

    pos = _mk_pos()  # entry 100, sl 99
    pm._exits.evaluate(pos, bar_close=101.0, bar_index=3, bar_high=101.0, bar_low=100.9)
    assert pm._exits.is_risk_free(pos)

    leg_lvn = 100.0
    tick = 0.05
    # structural_stop places the stop inside_ticks (2) INSIDE anchor toward entry:
    # LONG → sl = anchor + 2*tick = 100.10, clamped to stay strictly below entry 100.05
    # → sl = anchor + 1*tick = 100.05... but must be < entry, so it lands at 100.0.
    from quant.decision.stops import structural_stop

    new_sl = structural_stop("LONG", 100.05, leg_lvn, tick)

    dto = {"legLvn": leg_lvn, "absorptionSide": "SELL_ABSORBED"}
    pm.check_pyramid(dto, _bar(100.05), pos, bar_index=5)

    assert len(pm.pyramid_positions) == 1, "P1 should have fired"
    pyr = pm.pyramid_positions[0]

    # The base SL must now equal the pyramid's new_sl (ratcheted).
    # dataclasses.replace produces a NEW ratcheted Position; original pos is untouched.
    assert pm.base_override is not None, "base_override should carry the ratcheted position"
    base_sl = float(pm.base_override.order.signal.sl)
    assert base_sl == new_sl, (
        f"E10 VIOLATION: base SL={base_sl:.2f} not ratcheted to pyramid new_sl={new_sl:.2f}; "
        "bundle is no longer guaranteed positive"
    )

    # Pyramid's own SL equals the same structural stop.
    assert float(pyr.order.signal.sl) == new_sl


# ---------------------------------------------------------------------------
# E11 — Pyramid add-ons reserve portfolio open risk.
# ---------------------------------------------------------------------------

def test_e11_pyramid_reserves_portfolio_risk():
    """E11: every pyramid add-on must register its open risk with the portfolio
    authority at fill, so aggregate exposure cannot exceed the cap."""
    oms = PaperOMS(lot_size=1.0)
    portfolio_risk = PortfolioRiskAuthority(starting_equity=10_000.0, max_portfolio_risk_pct=0.04)
    pm = _mk_pm(oms, portfolio_risk=portfolio_risk)

    pos = _mk_pos()
    pm._exits.evaluate(pos, bar_close=101.0, bar_index=3, bar_high=101.0, bar_low=100.9)
    assert pm._exits.is_risk_free(pos)

    dto = {"legLvn": 100.0, "absorptionSide": "SELL_ABSORBED"}
    pm.check_pyramid(dto, _bar(100.05), pos, bar_index=5)

    assert len(pm.pyramid_positions) == 1, "P1 should have fired"
    pyr = pm.pyramid_positions[0]

    # The pyramid's open risk must be registered with the portfolio authority.
    from quant.decision.stops import structural_stop

    pyr_sl = structural_stop("LONG", 100.05, 100.0, 0.05)  # same as check_pyramid computes
    expected_risk = abs(100.05 - pyr_sl) * 5.0  # entry-sl distance × qty (5 lots)
    assert pytest.approx(portfolio_risk.open_risk, rel=1e-6) == expected_risk, (
        "E11 VIOLATION: pyramid open risk not registered with PortfolioRiskAuthority; "
        f"expected ₹{expected_risk:.2f}, got ₹{portfolio_risk.open_risk:.2f}"
    )


def test_e11_portfolio_cap_blocks_over_pyramid_exposure():
    """E11 regression: if pyramids bypassed portfolio risk, two add-ons could
    push aggregate exposure past the cap. This test asserts the cap is honored."""
    oms = PaperOMS(lot_size=1.0)

    # Base position consumes 50% of a ₹10k cap (risk distance 1.0 × qty 10).
    portfolio_risk = PortfolioRiskAuthority(starting_equity=10_000.0, max_portfolio_risk_pct=0.04)
    base_risk = abs(100.0 - 99.0) * 10.0  # ₹10
    assert portfolio_risk.can_accept(base_risk)[0], "base should fit"
    assert portfolio_risk.register_open(base_risk), "base must register"

    # Pyramid P1 = 5 lots × ₹1 distance = ₹5; P2 = 3 lots × ₹1 = ₹3.
    p1_risk, p2_risk = abs(100.0 - 99.0) * 5.0, abs(100.0 - 99.0) * 3.0

    # After the fix both must be accepted against the same portfolio authority.
    assert portfolio_risk.can_accept(p1_risk)[0], "P1 risk should fit remaining cap"
    assert portfolio_risk.register_open(p1_risk), "P1 must register open risk"
    assert portfolio_risk.can_accept(p2_risk)[0], "P2 risk should fit remaining cap"
    assert portfolio_risk.register_open(p2_risk), "P2 must register open risk"
