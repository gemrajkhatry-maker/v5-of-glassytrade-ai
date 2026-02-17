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
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
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
    max_hold_seconds: float = 120       # 2 min time stop (scratch)
    cooldown_seconds: float = 30        # no re-entry for 30s after exit
    partial_tp_pct: float = 0.50        # take partial at 50% of TP distance
    partial_size_pct: float = 0.50      # close 50% of position on partial
    scratch_threshold_pct: float = 0.0005  # 0.05% movement threshold for scratch
    # Runner logic (Fabio: close 75% at target, trail 25% as runner)
    runner_close_pct: float = 0.75      # close 75% at primary target
    runner_trail_pct: float = 0.25      # trail remaining 25%


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
    market_state: str = "BALANCED"  # "BALANCED" or "IMBALANCED"

    entry_time: float = 0.0  # callers must set; 0 = use time.time() fallback
    initial_stop: float = 0.0        # original stop for R-multiple calculation
    peak_price: float = 0.0          # best price since entry
    trailing_active: bool = False
    trailing_stop: float = 0.0
    partial_taken: bool = False       # True after partial profit booking
    runner_active: bool = False       # True when runner portion is being trailed
    mae: float = 0.0                 # Maximum Adverse Excursion
    mfe: float = 0.0                 # Maximum Favorable Excursion

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
    PARTIAL_TAKE_PROFIT = "PARTIAL_TAKE_PROFIT"
    SCRATCH = "SCRATCH"
    BREAK_EVEN = "BREAK_EVEN"
    OVERSEER_EXIT = "OVERSEER_EXIT"
    OVERSEER_PARTIAL = "OVERSEER_PARTIAL"


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

    MAX_DAILY_LOSSES = 3

    def __init__(self, config: TradeManagerConfig | None = None) -> None:
        self.config = config or TradeManagerConfig()
        self._lock = threading.Lock()
        self._positions: dict[str, ManagedPosition] = {}
        self._last_exit_time: float = 0.0
        self._daily_losses: int = 0
        self._daily_loss_reset_time: float = self._next_utc_midnight()

    # ------------------------------------------------------------------
    # Daily loss tracking
    # ------------------------------------------------------------------

    @staticmethod
    def _next_utc_midnight() -> float:
        """Return epoch timestamp of the next UTC midnight."""
        now = datetime.now(timezone.utc)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if tomorrow <= now:
            from datetime import timedelta
            tomorrow += timedelta(days=1)
        return tomorrow.timestamp()

    def _maybe_reset_daily(self) -> None:
        """Reset daily loss counter if we have passed midnight UTC."""
        if time.time() >= self._daily_loss_reset_time:
            self._daily_losses = 0
            self._daily_loss_reset_time = self._next_utc_midnight()

    def record_loss(self) -> None:
        """Record a stop-loss exit for daily loss tracking."""
        self._maybe_reset_daily()
        self._daily_losses += 1
        logger.info(f"TradeManager: daily losses = {self._daily_losses}/{self.MAX_DAILY_LOSSES}")

    def is_daily_limit_reached(self) -> bool:
        """True if the daily loss limit has been reached."""
        self._maybe_reset_daily()
        return self._daily_losses >= self.MAX_DAILY_LOSSES

    def should_block_entry(self) -> bool:
        """True if new entries should be blocked (daily limit reached)."""
        return self.is_daily_limit_reached()

    # ------------------------------------------------------------------
    # RR Filter
    # ------------------------------------------------------------------

    @staticmethod
    def is_valid_rr(entry: float, sl: float, tp: float, min_rr: float = 2.0) -> bool:
        """Check that risk:reward ratio is at least 1:min_rr.

        Returns True if the trade offers sufficient reward relative to risk.
        """
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        if risk <= 0:
            return False
        return (reward / risk) >= min_rr

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
        market_state: str = "BALANCED",
        entry_time: float | None = None,
    ) -> None:
        """Start managing a newly opened position."""
        mp = ManagedPosition(
            position_id=position_id,
            side=side,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            allow_trail=allow_trail,
            market_state=market_state,
            peak_price=entry_price,
            initial_stop=stop_loss,
            entry_time=entry_time if entry_time is not None else time.time(),
        )
        with self._lock:
            self._positions[position_id] = mp
        logger.info(
            f"TradeManager: registered {side} {position_id} "
            f"entry={entry_price:.2f} SL={stop_loss:.2f} TP={take_profit:.2f}"
        )

    def unregister_position(self, position_id: str, current_time: float | None = None) -> None:
        """Stop managing a position (call after exit is executed)."""
        with self._lock:
            if position_id in self._positions:
                del self._positions[position_id]
                self._last_exit_time = current_time if current_time is not None else time.time()
                logger.info(f"TradeManager: unregistered {position_id}")

    # ------------------------------------------------------------------
    # Tick-level check
    # ------------------------------------------------------------------

    def check_position(
        self, position_id: str, current_price: float,
        current_time: float | None = None,
    ) -> Optional[ExitSignal]:
        """Check all exit rules for a managed position.

        Returns an ExitSignal if any rule triggers, else None.
        Priority order: SL > TP > Partial TP > Trailing > Time/Scratch.
        """
        with self._lock:
            mp = self._positions.get(position_id)
        if mp is None:
            return None

        now = current_time if current_time is not None else time.time()

        # ----- 1. STOP LOSS -----
        if mp.is_long and current_price <= mp.stop_loss:
            logger.info(f"TradeManager: STOP LOSS hit for {position_id} at {current_price:.2f}")
            return ExitSignal(position_id, ExitReason.STOP_LOSS, current_price)

        if not mp.is_long and current_price >= mp.stop_loss:
            logger.info(f"TradeManager: STOP LOSS hit for {position_id} at {current_price:.2f}")
            return ExitSignal(position_id, ExitReason.STOP_LOSS, current_price)

        # ----- MAE/MFE tracking -----
        unrealised = (current_price - mp.entry_price) if mp.is_long else (mp.entry_price - current_price)
        if unrealised > mp.mfe:
            mp.mfe = unrealised
        if unrealised < -mp.mae:
            mp.mae = -unrealised  # mae stored as positive value

        # ----- 2. TAKE PROFIT -----
        tp_hit = (
            (mp.is_long and current_price >= mp.take_profit) or
            (not mp.is_long and current_price <= mp.take_profit)
        )
        if tp_hit and not mp.runner_active:
            if mp.allow_trail:
                # Runner logic: close 75% at target, trail 25%
                mp.runner_active = True
                mp.stop_loss = mp.entry_price  # move to break-even
                # Set trailing stop for runner
                trail_offset = abs(current_price - mp.entry_price) * self.config.trail_step_pct
                if mp.is_long:
                    mp.trailing_stop = current_price - trail_offset
                else:
                    mp.trailing_stop = current_price + trail_offset
                mp.trailing_active = True
                logger.info(
                    f"TradeManager: RUNNER activated for {position_id} — "
                    f"closing {self.config.runner_close_pct:.0%}, trailing {self.config.runner_trail_pct:.0%}"
                )
                return ExitSignal(position_id, ExitReason.PARTIAL_TAKE_PROFIT, current_price)
            else:
                # Mean reversion: close 100% at POC
                logger.info(f"TradeManager: TAKE PROFIT hit for {position_id} at {current_price:.2f}")
                return ExitSignal(position_id, ExitReason.TAKE_PROFIT, current_price)

        # ----- 3. PARTIAL TAKE PROFIT (at 50% of TP distance) -----
        if not mp.partial_taken:
            tp_distance = abs(mp.take_profit - mp.entry_price)
            partial_target = tp_distance * self.config.partial_tp_pct
            unrealised = (
                (current_price - mp.entry_price) if mp.is_long
                else (mp.entry_price - current_price)
            )
            if unrealised >= partial_target and partial_target > 0:
                mp.partial_taken = True
                # Move stop loss to break-even after partial
                mp.stop_loss = mp.entry_price
                logger.info(
                    f"TradeManager: PARTIAL TP for {position_id} at {current_price:.2f}, "
                    f"SL moved to break-even ({mp.entry_price:.2f})"
                )
                return ExitSignal(position_id, ExitReason.PARTIAL_TAKE_PROFIT, current_price)

        # ----- 4. TRAILING STOP -----
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

        # ----- 5. TIME STOP / SCRATCH -----
        # Imbalanced markets get more time (trends need time to develop)
        max_hold = self.config.max_hold_seconds
        if mp.market_state == "IMBALANCED":
            max_hold = 300  # 5 min for trending markets

        if (now - mp.entry_time) >= max_hold:
            price_move_pct = abs(current_price - mp.entry_price) / mp.entry_price
            if price_move_pct < self.config.scratch_threshold_pct:
                logger.info(
                    f"TradeManager: SCRATCH for {position_id} after "
                    f"{now - mp.entry_time:.0f}s (move={price_move_pct:.5f})"
                )
                return ExitSignal(position_id, ExitReason.SCRATCH, current_price)
            else:
                logger.info(
                    f"TradeManager: TIME STOP for {position_id} after "
                    f"{now - mp.entry_time:.0f}s"
                )
                return ExitSignal(position_id, ExitReason.TIME_STOP, current_price)

        return None

    def apply_cvd_kill_signal(
        self, position_id: str, cvd_divergence: str, current_price: float,
    ) -> Optional[ExitSignal]:
        """Check if CVD divergence contra the position should trigger early exit.

        Fabio's rule: if CVD diverges against your position, tighten to break-even
        or scratch immediately.
        """
        mp = self._positions.get(position_id)
        if mp is None:
            return None

        # LONG + BEARISH divergence = buyers losing steam → tighten
        if mp.is_long and cvd_divergence == "BEARISH_DIV":
            if not mp.partial_taken:
                # Move stop to break-even
                mp.stop_loss = mp.entry_price
                logger.info(f"TradeManager: CVD kill signal — moved SL to break-even for {position_id}")
            else:
                # Already partial — scratch out
                logger.info(f"TradeManager: CVD kill signal — scratching {position_id}")
                return ExitSignal(position_id, ExitReason.SCRATCH, current_price)

        # SHORT + BULLISH divergence = sellers losing steam → tighten
        if not mp.is_long and cvd_divergence == "BULLISH_DIV":
            if not mp.partial_taken:
                mp.stop_loss = mp.entry_price
                logger.info(f"TradeManager: CVD kill signal — moved SL to break-even for {position_id}")
            else:
                logger.info(f"TradeManager: CVD kill signal — scratching {position_id}")
                return ExitSignal(position_id, ExitReason.SCRATCH, current_price)

        return None

    # ------------------------------------------------------------------
    # Overseer helpers
    # ------------------------------------------------------------------

    def get_position_state(
        self, position_id: str, current_price: float,
        current_time: float | None = None,
    ) -> Optional[dict]:
        """Return a snapshot dict of the position state for the Overseer.

        Returns None if the position is not found.
        """
        with self._lock:
            mp = self._positions.get(position_id)
        if mp is None:
            return None

        now = current_time if current_time is not None else time.time()
        unrealised = (
            (current_price - mp.entry_price) if mp.is_long
            else (mp.entry_price - current_price)
        )
        unrealised_pct = unrealised / mp.entry_price if mp.entry_price else 0.0

        # Distance to SL / TP as percentage of entry price
        distance_to_sl = abs(current_price - mp.stop_loss) / mp.entry_price if mp.entry_price else 0.0
        distance_to_tp = abs(mp.take_profit - current_price) / mp.entry_price if mp.entry_price else 0.0

        return {
            "position_id": position_id,
            "side": mp.side,
            "entry_price": mp.entry_price,
            "current_price": current_price,
            "unrealized_pnl_pct": round(unrealised_pct, 6),
            "time_in_trade_secs": round(now - mp.entry_time, 1),
            "stop_loss": mp.stop_loss,
            "take_profit": mp.take_profit,
            "distance_to_sl_pct": round(distance_to_sl, 6),
            "distance_to_tp_pct": round(distance_to_tp, 6),
            "partial_taken": mp.partial_taken,
            "trailing_active": mp.trailing_active,
            "runner_active": mp.runner_active,
            "market_state": mp.market_state,
            "mae": round(mp.mae, 4),
            "mfe": round(mp.mfe, 4),
            "r_multiple": round(unrealised / abs(mp.entry_price - mp.initial_stop), 2)
                if abs(mp.entry_price - mp.initial_stop) > 0 else 0.0,
        }

    def adjust_stop_loss(self, position_id: str, new_sl: float) -> bool:
        """Tighten the stop-loss for a managed position.

        For LONG positions, new_sl must be > current stop_loss (tighten up).
        For SHORT positions, new_sl must be < current stop_loss (tighten down).
        Returns True if adjusted, False if rejected or position not found.
        """
        with self._lock:
            mp = self._positions.get(position_id)
        if mp is None:
            logger.warning(f"TradeManager: adjust_stop_loss — position {position_id} not found")
            return False

        if mp.is_long:
            if new_sl <= mp.stop_loss:
                logger.info(
                    f"TradeManager: adjust_stop_loss REJECTED for {position_id} — "
                    f"new SL {new_sl:.2f} <= current {mp.stop_loss:.2f} (LONG can only tighten up)"
                )
                return False
        else:
            if new_sl >= mp.stop_loss:
                logger.info(
                    f"TradeManager: adjust_stop_loss REJECTED for {position_id} — "
                    f"new SL {new_sl:.2f} >= current {mp.stop_loss:.2f} (SHORT can only tighten down)"
                )
                return False

        old_sl = mp.stop_loss
        mp.stop_loss = new_sl
        logger.info(
            f"TradeManager: stop-loss adjusted for {position_id} — "
            f"{old_sl:.2f} -> {new_sl:.2f}"
        )
        return True

    # ------------------------------------------------------------------
    # Cooldown query
    # ------------------------------------------------------------------

    def in_cooldown(self, current_time: float | None = None) -> bool:
        """True if a recent exit was taken and we should not re-enter yet."""
        if self._last_exit_time == 0:
            return False
        now = current_time if current_time is not None else time.time()
        return (now - self._last_exit_time) < self.config.cooldown_seconds

    @property
    def has_managed_positions(self) -> bool:
        return len(self._positions) > 0
