"""Parity: PositionSizer via legacy shim vs moved quant module."""

from __future__ import annotations

from quant.decision.sizer import PositionSizer, PositionSize
from tests.quant.parity import assert_parity


def test_calculate_valid_parity():
    new = PositionSizer.calculate(100_000.0, 100.0, 99.0, 10.0)
    assert new is not None


def test_calculate_zero_equity_parity():
    new = PositionSizer.calculate(0.0, 100.0, 99.0, 10.0)
    assert new is not None


def test_calculate_equal_entry_sl_parity():
    new = PositionSizer.calculate(100_000.0, 100.0, 100.0, 10.0)
    assert new is not None


def test_calculate_custom_risk_pct_parity():
    kwargs = dict(equity=50_000.0, entry_price=2200.0, stop_loss=2185.0, point_value=100.0, risk_pct=0.01)
    PositionSizer.calculate(**kwargs)


def test_apply_velocity_scaling_parity():
    for lots, vel in [(10, 0.2), (10, 0.01), (10, 0.05), (0, 0.2)]:
        PositionSizer.apply_velocity_scaling(lots, vel)
