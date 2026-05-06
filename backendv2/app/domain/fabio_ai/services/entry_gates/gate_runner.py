"""Facade for entry gate execution and sizing."""

from __future__ import annotations

from app.domain.amt.service.gate_pipeline import run_gate_pipeline
from app.domain.amt.service.entry_gates import calculate_position_size


def run_entry_gate_pipeline(
    data,
    amt_result,
    tick,
    **kwargs,
) -> tuple[bool, str, str, int, int]:
    """Backwards-compatible wrapper used by older imports."""
    return run_gate_pipeline(data, amt_result, tick, **kwargs)


def calculate_position_size_wrapper(
    equity: float,
    entry_price: float,
    stop_loss: float,
    point_value: float = 10.0,
    price_velocity: float = 0.0,
) -> tuple[int, float, bool]:
    """Position-size compatibility wrapper."""
    return calculate_position_size(
        equity=equity,
        entry_price=entry_price,
        stop_loss=stop_loss,
        point_value=point_value,
        price_velocity=price_velocity,
    )


def run_gate_pipeline(
    data,
    amt_result,
    tick,
    **kwargs,
) -> tuple[bool, str, str, int, int]:
    """Alias kept for parity with v1 module layout."""
    return run_entry_gate_pipeline(data, amt_result, tick, **kwargs)


def calculate_position_size(
    equity: float,
    entry_price: float,
    stop_loss: float,
    point_value: float = 10.0,
    price_velocity: float = 0.0,
) -> tuple[int, float, bool]:
    """Alias kept for parity with v1 module layout."""
    return calculate_position_size_wrapper(
        equity=equity,
        entry_price=entry_price,
        stop_loss=stop_loss,
        point_value=point_value,
        price_velocity=price_velocity,
    )

