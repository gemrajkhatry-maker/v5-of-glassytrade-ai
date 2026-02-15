"""Deterministic Trade Manager — manages open positions to conclusion.

This is pure domain logic with NO LLM dependency.  It runs every tick
and checks stop-loss, take-profit, trailing-stop and time-stop rules.

Design rationale
----------------
The LLM was trained on *entry* decisions only (AAA Setup, Momentum,
Failed Auction).  Asking it to HOLD/EXIT produces random outputs.
Trade management must therefore be **rule-based and deterministic**.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class TradeManagerConfig:
    """All thresholds are expressed as fractions (e.g. 0.005 = 0.5%)."""

    stop_loss_pct: float = 0.005        # 0.5% hard stop
    take_profit_pct: float = 0.015      # 1.5% take profit
    trail_activation_pct: float = 0.50  # activate trail after 50% of TP
    trail_step_pct: float = 0.30        # trail 30% behind peak unrealised PnL
    max_hold_seconds: float = 3600      # 60 min time stop
    cooldown_seconds: float = 30        # no re-entry for 30s after exit


# ---------------------------------------------------------------------------
# Position Tracker (lightweight, per-symbol)
# ---------------------------------------------------------------------------

@dataclass
class ManagedPosition:
    """Internal state for a position being managed by the TradeManager."""

    position_id: str
    side: str              # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    allow_trail: bool = False  # Only trail if market is Imbalanced

    entry_time: float = field(default_factory=time.time)
    peak_price: float = 0.0          # best price since entry
    trailing_active: bool = False
    trailing_stop: float = 0.0

    @property
    def is_long(self) -> bool:
        return self.side == "LONG"


# ---------------------------------------------------------------------------
# Exit reasons (used for analytics / UI)
# ---------------------------------------------------------------------------

class ExitReason:
    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    TRAILING_STOP = "TRAILING_STOP"
    TIME_STOP = "TIME_STOP"


# ---------------------------------------------------------------------------
# Trade Manager Service
# ---------------------------------------------------------------------------

@dataclass
class ExitSignal:
    """Returned by check_position when an exit is triggered."""
    position_id: str
    reason: str
    exit_price: float


class TradeManager:
    """Deterministic tick-level trade management.

    Usage::

        mgr = TradeManager()
        mgr.register_position(pos_id, "LONG", entry, sl, tp)

        # on every tick:
        exit_sig = mgr.check_position(pos_id, current_price)
        if exit_sig:
            execute_exit(exit_sig)

        # after exit completes:
        mgr.unregister_position(pos_id)
    """

    def __init__(self, config: TradeManagerConfig | None = None) -> None:
        self.config = config or TradeManagerConfig()
        self._positions: dict[str, ManagedPosition] = {}
        self._last_exit_time: float = 0.0

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_position(
        self,
        position_id: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        allow_trail: bool = False,
    ) -> None:
        """Start managing a newly opened position."""
        mp = ManagedPosition(
            position_id=position_id,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            allow_trail=allow_trail,
            peak_price=entry_price,
        )
        self._positions[position_id] = mp
        logger.info(
            f"TradeManager: registered {side} {position_id} "
            f"entry={entry_price:.2f} SL={stop_loss:.2f} TP={take_profit:.2f}"
        )

    def unregister_position(self, position_id: str) -> None:
        """Stop managing a position (call after exit is executed)."""
        if position_id in self._positions:
            del self._positions[position_id]
            self._last_exit_time = time.time()
            logger.info(f"TradeManager: unregistered {position_id}")

    # ------------------------------------------------------------------
    # Tick-level check
    # ------------------------------------------------------------------

    def check_position(
        self, position_id: str, current_price: float
    ) -> Optional[ExitSignal]:
        """Check all exit rules for a managed position.

        Returns an ExitSignal if any rule triggers, else None.
        """
        mp = self._positions.get(position_id)
        if mp is None:
            return None

        now = time.time()

        # ----- 1. STOP LOSS -----
        if mp.is_long and current_price <= mp.stop_loss:
            logger.info(f"TradeManager: STOP LOSS hit for {position_id} at {current_price:.2f}")
            return ExitSignal(position_id, ExitReason.STOP_LOSS, current_price)

        if not mp.is_long and current_price >= mp.stop_loss:
            logger.info(f"TradeManager: STOP LOSS hit for {position_id} at {current_price:.2f}")
            return ExitSignal(position_id, ExitReason.STOP_LOSS, current_price)

        # ----- 2. TAKE PROFIT -----
        if mp.is_long and current_price >= mp.take_profit:
            logger.info(f"TradeManager: TAKE PROFIT hit for {position_id} at {current_price:.2f}")
            return ExitSignal(position_id, ExitReason.TAKE_PROFIT, current_price)

        if not mp.is_long and current_price <= mp.take_profit:
            logger.info(f"TradeManager: TAKE PROFIT hit for {position_id} at {current_price:.2f}")
            return ExitSignal(position_id, ExitReason.TAKE_PROFIT, current_price)

        # ----- 3. TRAILING STOP -----
        # Update peak
        if mp.is_long:
            mp.peak_price = max(mp.peak_price, current_price)
        else:
            # For shorts, "peak" is the lowest price reached
            if mp.peak_price == mp.entry_price:
                mp.peak_price = current_price
            mp.peak_price = min(mp.peak_price, current_price)

        # Activation check
        if mp.allow_trail and not mp.trailing_active:
            tp_distance = abs(mp.take_profit - mp.entry_price)
            unrealised = (
                (current_price - mp.entry_price) if mp.is_long
                else (mp.entry_price - current_price)
            )
            if unrealised >= tp_distance * self.config.trail_activation_pct:
                mp.trailing_active = True
                trail_offset = unrealised * self.config.trail_step_pct
                if mp.is_long:
                    mp.trailing_stop = current_price - trail_offset
                else:
                    mp.trailing_stop = current_price + trail_offset
                logger.info(
                    f"TradeManager: trailing stop ACTIVATED for {position_id} "
                    f"at trail={mp.trailing_stop:.2f}"
                )

        # Move trail (ratchet only)
        if mp.trailing_active:
            if mp.is_long:
                unrealised = current_price - mp.entry_price
                trail_offset = unrealised * self.config.trail_step_pct
                new_trail = current_price - trail_offset
                if new_trail > mp.trailing_stop:
                    mp.trailing_stop = new_trail
                # Check hit
                if current_price <= mp.trailing_stop:
                    logger.info(
                        f"TradeManager: TRAILING STOP hit for {position_id} "
                        f"at {current_price:.2f}"
                    )
                    return ExitSignal(
                        position_id, ExitReason.TRAILING_STOP, current_price
                    )
            else:
                unrealised = mp.entry_price - current_price
                trail_offset = unrealised * self.config.trail_step_pct
                new_trail = current_price + trail_offset
                if new_trail < mp.trailing_stop:
                    mp.trailing_stop = new_trail
                if current_price >= mp.trailing_stop:
                    logger.info(
                        f"TradeManager: TRAILING STOP hit for {position_id} "
                        f"at {current_price:.2f}"
                    )
                    return ExitSignal(
                        position_id, ExitReason.TRAILING_STOP, current_price
                    )

        # ----- 4. TIME STOP -----
        if (now - mp.entry_time) >= self.config.max_hold_seconds:
            logger.info(
                f"TradeManager: TIME STOP for {position_id} after "
                f"{now - mp.entry_time:.0f}s"
            )
            return ExitSignal(position_id, ExitReason.TIME_STOP, current_price)

        return None

    # ------------------------------------------------------------------
    # Cooldown query
    # ------------------------------------------------------------------

    def in_cooldown(self) -> bool:
        """True if a recent exit was taken and we should not re-enter yet."""
        if self._last_exit_time == 0:
            return False
        return (time.time() - self._last_exit_time) < self.config.cooldown_seconds

    @property
    def has_managed_positions(self) -> bool:
        return len(self._positions) > 0
