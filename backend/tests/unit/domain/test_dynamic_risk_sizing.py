"""Dynamic risk feeding position sizing (audit P1-11).

Position sizing must reduce effective risk after session losses. The dynamic
cushion from LossTracker.compute_dynamic_risk is wired into
gate_runner.calculate_position_size via an optional ``session_realized_pnl``.
"""

import pytest

from app.domain.fabio_ai.services.entry_gates.gate_runner import calculate_position_size


def _size(session_realized_pnl=None, price_velocity: float = 0.0):
    return calculate_position_size(
        equity=100_000.0,
        entry_price=100.0,
        stop_loss=99.0,
        point_value=10.0,
        price_velocity=price_velocity,
        session_realized_pnl=session_realized_pnl,
    )


def test_baseline_fixed_pct_when_pnl_unavailable():
    """No session PnL -> fall back to fixed 0.5% risk pct (0.5% of 100k = 500)."""
    lots, risk, valid = _size(session_realized_pnl=None)
    assert valid
    assert lots == 50
    assert risk == pytest.approx(500.0)


def test_sizing_smaller_after_losses():
    """Three losses (negative session PnL) -> conservative 0.25% risk, half the lots."""
    lots_base, risk_base, _ = _size(session_realized_pnl=None)
    lots_lost, risk_lost, valid = _size(session_realized_pnl=-3000.0)
    assert valid
    assert lots_lost < lots_base
    assert risk_lost < risk_base
    assert lots_lost == 25
    assert risk_lost == pytest.approx(250.0)


def test_sizing_never_exceeds_baseline_in_profit():
    """Profit grows cushion but risk caps at 0.5% ceiling -> never above baseline."""
    lots_base, _, _ = _size(session_realized_pnl=None)
    lots_profit, risk_profit, valid = _size(session_realized_pnl=5000.0)
    assert valid
    assert lots_profit <= lots_base
    assert risk_profit <= 500.0


def test_velocity_scaling_still_applied():
    """Bug #10 velocity scaling stays intact after dynamic risk wiring."""
    lots_base, risk_base, _ = _size(session_realized_pnl=-3000.0)
    lots_fast, risk_fast, valid = _size(session_realized_pnl=-3000.0, price_velocity=0.2)
    assert valid
    assert lots_fast < lots_base
    assert lots_fast == 17  # int(25 * 0.7) = 17
    assert risk_fast == pytest.approx(250.0 * 17 / 25)
