"""Position Sizer — calculates position size based on risk parameters.

Formula:
  position_size = (risk_per_trade × capital) / (entry - SL)
  lots = floor(position_size / lot_size)
  actual_risk = lots × lot_size × |entry - SL|
"""

from __future__ import annotations


def calculate_position_size(
    capital: float,
    risk_per_trade_pct: float,
    entry_price: float,
    stop_loss: float,
    lot_size: int,
) -> tuple[int, float]:
    """Calculate position size in lots.

    Returns:
        (lots, actual_risk_amount)
    """
    if entry_price <= 0 or stop_loss <= 0 or lot_size <= 0:
        return 0, 0.0

    risk_per_lot = abs(entry_price - stop_loss) * lot_size
    if risk_per_lot <= 0:
        return 0, 0.0

    risk_amount = capital * (risk_per_trade_pct / 100)
    lots = int(risk_amount / risk_per_lot)

    # Cap at reasonable maximum
    lots = min(lots, 100)

    actual_risk = lots * risk_per_lot
    return max(0, lots), actual_risk
