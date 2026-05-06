"""Entry gate facade + sizing wrapper for 12-gate pipeline."""

from __future__ import annotations

from app.domain.exit.service.position_sizer import PositionSizer


def calculate_position_size(
    equity: float,
    entry_price: float,
    stop_loss: float,
    point_value: float = 10.0,
    price_velocity: float = 0.0,
    risk_pct: float = 0.005,
) -> tuple[int, float, bool]:
    size = PositionSizer.calculate(
        equity, entry_price, stop_loss, point_value, risk_pct=risk_pct
    )
    if not size.valid or size.lots <= 0:
        return 0, 0.0, False
    if price_velocity > 0:
        adjusted, _ = PositionSizer.apply_velocity_scaling(size.lots, price_velocity)
        if adjusted != size.lots:
            adjusted_risk = size.risk_amount * (adjusted / max(size.lots, 1))
            return adjusted, adjusted_risk, True
    return size.lots, size.risk_amount, True


def run_entry_gates(data: list, amt_result, tick: dict, **kwargs) -> tuple[bool, str, str, int, int]:
    """Compatibility wrapper around the default gate pipeline."""
    from app.domain.amt.service.gate_pipeline import run_gate_pipeline

    return run_gate_pipeline(data, amt_result, tick, **kwargs)

