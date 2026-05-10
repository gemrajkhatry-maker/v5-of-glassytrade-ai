"""Pure exit rule functions. No state, no side effects.

These functions operate on Position objects and return exit decisions.
They are pure functions suitable for unit testing.
"""

from __future__ import annotations

from app.domain.exit.model.exit_models import ExitReason


# Session-aware time stop table
TIME_STOP_TABLE: dict[tuple[str, str], float] = {
    ("MORNING", "BALANCED"): 1200,
    ("MORNING", "IMBALANCED"): 2700,
    ("AFTERNOON", "BALANCED"): 900,
    ("AFTERNOON", "IMBALANCED"): 1800,
}

EXPIRY_TIME_STOP: float = 600
HARD_MAX_HOLD_SECONDS: float = 7200


def classify_exit(
    direction: str,
    entry_price: float,
    exit_price: float,
    sl: float,
    tp: float,
    is_manual: bool = False,
) -> str:
    """Classify the reason for an exit."""
    if is_manual:
        return ExitReason.MANUAL

    if direction == "LONG":
        if exit_price <= sl:
            return ExitReason.STOP_LOSS
        if exit_price >= tp:
            return ExitReason.TAKE_PROFIT
    else:
        if exit_price >= sl:
            return ExitReason.STOP_LOSS
        if exit_price <= tp:
            return ExitReason.TAKE_PROFIT

    return ExitReason.MANUAL


def check_time_stop(
    hold_time_seconds: float,
    session_phase: str = "MORNING",
    market_state: str = "BALANCED",
    is_expiry: bool = False,
) -> bool:
    """Check if time stop has been reached."""
    if is_expiry:
        return hold_time_seconds >= EXPIRY_TIME_STOP

    key = (session_phase, market_state)
    limit = TIME_STOP_TABLE.get(key, 1800)
    return hold_time_seconds >= limit


def is_valid_rr(entry: float, sl: float, tp: float, direction: str, min_rr: float = 1.5) -> bool:
    """Check if the risk-reward ratio is valid."""
    risk = abs(entry - sl)
    if risk == 0:
        return False
    if direction == "LONG":
        reward = tp - entry
    else:
        reward = entry - tp
    rr = reward / risk
    return rr >= min_rr


def check_spread_blowout(spread_pct: float, threshold: float = 0.03) -> bool:
    """Check if bid-ask spread has blown out."""
    return spread_pct > threshold
