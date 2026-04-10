"""Exit Engine — stateless exit logic for open positions.

Checks:
- Stop Loss hit
- Take Profit hit
- Trailing stop hit
- Time stop (max duration)
- Scratch (session phase force-exit)
"""

from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass(frozen=True)
class ExitDecision:
    should_exit: bool
    reason: str  # "SL_HIT" | "TP_HIT" | "TRAIL_HIT" | "TIME_STOP" | "SESSION_EXIT" | ""
    exit_price: float = 0.0


def check_exit(
    current_price: float,
    stop_loss: float,
    take_profit: float,
    trail_price: float = 0.0,
    is_long: bool = True,
    max_duration_minutes: float = 0.0,
    entry_time: float = 0.0,
    force_exit: bool = False,  # Session phase forces exit
) -> ExitDecision:
    """Determine if position should be exited.

    Priority: SL > TP > Trail > Time > Session
    """
    # Session force-exit (Phase 5)
    if force_exit:
        return ExitDecision(should_exit=True, reason="SESSION_EXIT", exit_price=current_price)

    # Stop Loss check
    if is_long and current_price <= stop_loss:
        return ExitDecision(should_exit=True, reason="SL_HIT", exit_price=stop_loss)
    if not is_long and current_price >= stop_loss:
        return ExitDecision(should_exit=True, reason="SL_HIT", exit_price=stop_loss)

    # Take Profit check
    if is_long and current_price >= take_profit:
        return ExitDecision(should_exit=True, reason="TP_HIT", exit_price=take_profit)
    if not is_long and current_price <= take_profit:
        return ExitDecision(should_exit=True, reason="TP_HIT", exit_price=take_profit)

    # Trailing stop
    if trail_price > 0:
        if is_long and current_price <= trail_price:
            return ExitDecision(should_exit=True, reason="TRAIL_HIT", exit_price=trail_price)
        if not is_long and current_price >= trail_price:
            return ExitDecision(should_exit=True, reason="TRAIL_HIT", exit_price=trail_price)

    # Time stop
    if max_duration_minutes > 0 and entry_time > 0:
        elapsed = (time.time() - entry_time) / 60.0
        if elapsed >= max_duration_minutes:
            return ExitDecision(should_exit=True, reason="TIME_STOP", exit_price=current_price)

    return ExitDecision(should_exit=False, reason="")
