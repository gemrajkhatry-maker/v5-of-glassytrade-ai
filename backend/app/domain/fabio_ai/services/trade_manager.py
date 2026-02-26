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
    max_hold_seconds: float = 1800      # 30 min time stop for scalps (Fabio: < 30 min)
    cooldown_seconds: float = 30        # no re-entry for 30s after exit
    partial_tp_pct: float = 0.50        # take partial at 50% of TP distance
    partial_size_pct: float = 0.50      # close 50% of position on partial
    scratch_threshold_pct: float = 0.0005  # 0.05% movement threshold for scratch
    # Runner logic (Fabio: close 75% at target, trail 25% as runner)
    runner_close_pct: float = 0.75      # close 75% at primary target
    runner_trail_pct: float = 0.25      # trail remaining 25%
    # Breakeven at 1R: move SL to entry when unrealised profit reaches 1R
    breakeven_at_1r: bool = True
    # CVD-based breakeven: move SL to entry when CVD confirms direction
    cvd_breakeven: bool = True
    # Trail activation at 1R instead of 50% TP distance
    trail_activation_r: float = 1.0


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
    tick_count: int = 0              # ticks since entry (grace period guard)

    # Breakeven tracking
    breakeven_set: bool = False      # True once SL moved to entry (1R or CVD)
    entry_cvd_direction: str = ""    # "LONG" or "SHORT" — set by CVD confirmation

    # Session-aware time stop fields
    session_phase: str = ""          # "MORNING" or "AFTERNOON"
    is_expiry: bool = False          # True on options expiry day
    applied_time_stop: float = 0.0   # computed session time stop (never shrinks)

    # Scale-in state (Fabio Rule 4: 40/30/30)
    scale_step: int = 1              # 1=initial(40%), 2=confirmation(+30%), 3=breakout(+30%)
    scale_confirm_price: float = 0.0 # price level that triggers step 2
    scale_breakout_price: float = 0.0  # price level that triggers step 3

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
    SPREAD_BLOWOUT = "SPREAD_BLOWOUT"


# ---------------------------------------------------------------------------
# Trade Manager Service
# ---------------------------------------------------------------------------

@dataclass
class ExitSignal:
    """Returned by check_position when an exit is triggered."""
    position_id: str
    reason: str
    exit_price: float


# ---------------------------------------------------------------------------
# Session-aware time stop table
# ---------------------------------------------------------------------------

# (session_phase, market_state) -> time stop in seconds
TIME_STOP_TABLE: dict[tuple[str, str], float] = {
    ("MORNING", "BALANCED"): 1200,      # 20 min
    ("MORNING", "IMBALANCED"): 2700,    # 45 min
    ("AFTERNOON", "BALANCED"): 900,     # 15 min
    ("AFTERNOON", "IMBALANCED"): 1800,  # 30 min
}

# Expiry day flat time stop (regardless of session/state)
EXPIRY_TIME_STOP: float = 600  # 10 min


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
        with self._lock:
            self._maybe_reset_daily()
            self._daily_losses += 1
            logger.info(f"TradeManager: daily losses = {self._daily_losses}/{self.MAX_DAILY_LOSSES}")

    def is_daily_limit_reached(self) -> bool:
        """True if the daily loss limit has been reached."""
        with self._lock:
            self._maybe_reset_daily()
            return self._daily_losses >= self.MAX_DAILY_LOSSES

    def should_block_entry(self) -> bool:
        """True if new entries should be blocked (daily limit reached)."""
        return self.is_daily_limit_reached()

    # ------------------------------------------------------------------
    # Session-aware time stop
    # ------------------------------------------------------------------

    @staticmethod
    def get_session_time_stop(
        market_state: str,
        session_phase: str,
        is_expiry: bool,
        time_to_close: float,
    ) -> float:
        """Compute session-aware time stop in seconds.

        Args:
            market_state: "BALANCED" or "IMBALANCED"
            session_phase: "MORNING" or "AFTERNOON" (empty = fallback)
            is_expiry: True on options expiry day
            time_to_close: seconds until market close (0 = unknown)

        Returns:
            Time stop in seconds. Caller must use max(applied, new) to
            ensure stops never shrink.
        """
        # Expiry day: flat 600s regardless of session/state
        if is_expiry:
            phase_stop = EXPIRY_TIME_STOP
        elif session_phase:
            # Look up from table; fallback to config defaults if not found
            key = (session_phase.upper(), market_state.upper())
            phase_stop = TIME_STOP_TABLE.get(key, 0.0)
            if phase_stop == 0.0:
                # Fallback: 1800 balanced, 7200 imbalanced
                phase_stop = 7200.0 if market_state.upper() == "IMBALANCED" else 1800.0
        else:
            # No session info: use static fallback
            phase_stop = 7200.0 if market_state.upper() == "IMBALANCED" else 1800.0

        # Near close: cap at time_to_close - 300s (5 min buffer before close)
        if time_to_close > 0:
            near_close_stop = time_to_close - 300.0
            if near_close_stop > 0:
                phase_stop = min(phase_stop, near_close_stop)
            else:
                # Less than 5 min to close: exit immediately (1s)
                phase_stop = 1.0

        return phase_stop

    # ------------------------------------------------------------------
    # RR Filter
    # ------------------------------------------------------------------

    @staticmethod
    def is_valid_rr(entry: float, sl: float, tp: float, min_rr: float = 1.95) -> bool:
        """Check that risk:reward ratio is at least 1:min_rr.

        Returns True if the trade offers sufficient reward relative to risk.
        Threshold slightly below 2.0 to avoid floating-point edge rejections.
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
        enable_scale_in: bool = False,
        session_phase: str = "",
        is_expiry: bool = False,
    ) -> None:
        """Start managing a newly opened position.

        If ``enable_scale_in`` is True, scale-in trigger levels are set:
          - Step 2 (confirmation): price moves 30% of SL distance in favor
          - Step 3 (breakout): price moves 60% toward TP
        """
        risk = abs(entry_price - stop_loss)
        tp_dist = abs(take_profit - entry_price)

        # Scale-in levels
        if enable_scale_in and side == "LONG":
            confirm_price = entry_price + risk * 0.3
            breakout_price = entry_price + tp_dist * 0.6
        elif enable_scale_in and side == "SHORT":
            confirm_price = entry_price - risk * 0.3
            breakout_price = entry_price - tp_dist * 0.6
        else:
            confirm_price = 0.0
            breakout_price = 0.0

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
            scale_step=1 if enable_scale_in else 3,  # 3 = fully deployed
            scale_confirm_price=confirm_price,
            scale_breakout_price=breakout_price,
            session_phase=session_phase,
            is_expiry=is_expiry,
        )
        with self._lock:
            self._positions[position_id] = mp
        logger.info(
            f"TradeManager: registered {side} {position_id} "
            f"entry={entry_price:.2f} SL={stop_loss:.2f} TP={take_profit:.2f}"
            f"{' [scale-in enabled]' if enable_scale_in else ''}"
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
        time_to_close: float = 0.0,
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
            mp.tick_count += 1

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

            # ----- 1b. BREAKEVEN AT 1R -----
            # Move SL to entry when unrealised profit reaches 1R (risk distance)
            if self.config.breakeven_at_1r and not mp.breakeven_set:
                risk = abs(mp.entry_price - mp.initial_stop)
                if risk > 0 and unrealised >= risk:
                    mp.stop_loss = mp.entry_price
                    mp.breakeven_set = True
                    logger.info(
                        f"TradeManager: BREAKEVEN at 1R for {position_id} — "
                        f"SL moved to entry {mp.entry_price:.2f}"
                    )

            # ----- 1c. BREAKEVEN FLOOR -----
            # Once breakeven is set, SL can never go below entry
            if mp.breakeven_set:
                if mp.is_long and mp.stop_loss < mp.entry_price:
                    mp.stop_loss = mp.entry_price
                elif not mp.is_long and mp.stop_loss > mp.entry_price:
                    mp.stop_loss = mp.entry_price

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

            # Activation check — activate at 1R (risk distance) instead of 50% TP
            if mp.allow_trail and not mp.trailing_active:
                risk = abs(mp.entry_price - mp.initial_stop)
                activation_threshold = risk * self.config.trail_activation_r
                unrealised = (
                    (current_price - mp.entry_price) if mp.is_long
                    else (mp.entry_price - current_price)
                )
                if activation_threshold > 0 and unrealised >= activation_threshold:
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
            # Grace period: skip time stop for first 5 ticks (position settling)
            if mp.tick_count < 5:
                return None

            # Session-aware time stop: use table if session info is available
            if mp.session_phase or mp.is_expiry:
                new_stop = self.get_session_time_stop(
                    market_state=mp.market_state,
                    session_phase=mp.session_phase,
                    is_expiry=mp.is_expiry,
                    time_to_close=time_to_close,
                )
                # Never shrink: only extend the time stop
                mp.applied_time_stop = max(mp.applied_time_stop, new_stop)
                max_hold = mp.applied_time_stop
            else:
                # Fallback: static time stops (no session info)
                max_hold = self.config.max_hold_seconds
                if mp.market_state == "IMBALANCED":
                    max_hold = 7200  # 2 hr for trending/momentum markets

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

    def check_scale_in(self, position_id: str, current_price: float) -> float:
        """Check if a scale-in trigger is hit. Returns the fraction to add (0.3) or 0.0."""
        with self._lock:
            mp = self._positions.get(position_id)
            if mp is None or mp.scale_step >= 3:
                return 0.0

            if mp.scale_step == 1:
                # Step 2: confirmation — price moved favorably past confirm level
                triggered = (
                    (mp.is_long and current_price >= mp.scale_confirm_price > 0) or
                    (not mp.is_long and current_price <= mp.scale_confirm_price and mp.scale_confirm_price > 0)
                )
                if triggered:
                    mp.scale_step = 2
                    logger.info(
                        f"TradeManager: SCALE-IN step 2 (confirmation) for {position_id} "
                        f"at {current_price:.2f} — adding 30%%"
                    )
                    return 0.3

            if mp.scale_step == 2:
                # Step 3: breakout — price reached breakout level
                triggered = (
                    (mp.is_long and current_price >= mp.scale_breakout_price > 0) or
                    (not mp.is_long and current_price <= mp.scale_breakout_price and mp.scale_breakout_price > 0)
                )
                if triggered:
                    mp.scale_step = 3
                    logger.info(
                        f"TradeManager: SCALE-IN step 3 (breakout) for {position_id} "
                        f"at {current_price:.2f} — adding final 30%%"
                    )
                    return 0.3

            return 0.0

    def apply_cvd_kill_signal(
        self, position_id: str, cvd_divergence: str, current_price: float,
    ) -> Optional[ExitSignal]:
        """Check if CVD divergence contra the position should trigger early exit.

        Fabio's rule: if CVD diverges against your position, tighten to break-even
        or scratch immediately.
        """
        with self._lock:
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

    def apply_cvd_breakeven(self, position_id: str, cvd_slope: float) -> bool:
        """Move SL to breakeven if CVD slope confirms the trade direction.

        Positive slope confirms LONG, negative slope confirms SHORT.
        Returns True if breakeven was applied, False otherwise.
        """
        if not self.config.cvd_breakeven:
            return False

        with self._lock:
            mp = self._positions.get(position_id)
            if mp is None or mp.breakeven_set:
                return False

            # CVD slope must confirm trade direction
            confirms = (
                (mp.is_long and cvd_slope > 0) or
                (not mp.is_long and cvd_slope < 0)
            )
            if not confirms:
                return False

            mp.stop_loss = mp.entry_price
            mp.breakeven_set = True
            mp.entry_cvd_direction = mp.side
            logger.info(
                f"TradeManager: CVD BREAKEVEN for {position_id} — "
                f"slope={cvd_slope:.3f}, SL moved to entry {mp.entry_price:.2f}"
            )
            return True

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

            # Breakeven floor: once set, SL cannot go below entry
            if mp.breakeven_set:
                if mp.is_long and new_sl < mp.entry_price:
                    logger.info(
                        f"TradeManager: adjust_stop_loss REJECTED for {position_id} — "
                        f"breakeven set, new SL {new_sl:.2f} < entry {mp.entry_price:.2f}"
                    )
                    return False
                if not mp.is_long and new_sl > mp.entry_price:
                    logger.info(
                        f"TradeManager: adjust_stop_loss REJECTED for {position_id} — "
                        f"breakeven set, new SL {new_sl:.2f} > entry {mp.entry_price:.2f}"
                    )
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
    # VWAP Band Trailing
    # ------------------------------------------------------------------

    def apply_vwap_trail(
        self,
        position_id: str,
        current_price: float,
        vwap: float,
        vwap_upper_1: float,
        vwap_lower_1: float,
        vwap_upper_2: float,
        vwap_lower_2: float,
    ) -> None:
        """Trail stop-loss to nearest VWAP band at 1.5R profit, tighten at 2 sigma.

        Rules:
        - Only activates when unrealised profit >= 1.5R.
        - For LONG: SL moves to highest VWAP band below price and above entry.
        - 1.5R floor: trail distance never exceeds 1.5R from entry.
        - 2 sigma tighten: if price at/beyond 2-sigma band, SL tightened to 50%
          of current price-to-SL distance.
        - SL only ratchets (never loosens).
        """
        with self._lock:
            mp = self._positions.get(position_id)
            if mp is None:
                return

            entry = mp.entry_price
            initial_risk = abs(entry - mp.initial_stop)
            if initial_risk <= 0:
                return

            unrealised = (current_price - entry) if mp.is_long else (entry - current_price)
            unrealised_r = unrealised / initial_risk

            if unrealised_r < 1.5:
                return  # Not enough profit to trail

            bands = sorted([vwap, vwap_upper_1, vwap_lower_1, vwap_upper_2, vwap_lower_2])

            if mp.is_long:
                # Find highest band below current price and above entry
                valid_bands = [b for b in bands if b < current_price and b > entry]
                if valid_bands:
                    trail_sl = max(valid_bands)
                else:
                    trail_sl = entry + initial_risk * 1.5

                # Cap: trail must be at least 1.5R above entry
                min_trail = entry + initial_risk * 1.5
                trail_sl = max(trail_sl, min_trail)

                # 2 sigma tighten: if price at/above vwap_upper_2
                if current_price >= vwap_upper_2:
                    current_distance = current_price - mp.stop_loss
                    tightened = current_price - (current_distance * 0.5)
                    trail_sl = max(trail_sl, tightened)

                # Never lower SL (ratchet only)
                if trail_sl > mp.stop_loss:
                    mp.stop_loss = trail_sl
                    logger.info(
                        "TradeManager: VWAP trail for %s — SL moved to %.2f (%.1fR)",
                        position_id, trail_sl, unrealised_r,
                    )

            elif not mp.is_long:
                # For SHORT: find lowest band above current price and below entry
                valid_bands = [b for b in bands if b > current_price and b < entry]
                if valid_bands:
                    trail_sl = min(valid_bands)
                else:
                    trail_sl = entry - initial_risk * 1.5

                # Cap
                max_trail = entry - initial_risk * 1.5
                trail_sl = min(trail_sl, max_trail)

                # 2 sigma tighten
                if current_price <= vwap_lower_2:
                    current_distance = mp.stop_loss - current_price
                    tightened = current_price + (current_distance * 0.5)
                    trail_sl = min(trail_sl, tightened)

                # Never loosen SL (ratchet only)
                if trail_sl < mp.stop_loss:
                    mp.stop_loss = trail_sl
                    logger.info(
                        "TradeManager: VWAP trail for %s — SL moved to %.2f (%.1fR)",
                        position_id, trail_sl, unrealised_r,
                    )

    # ------------------------------------------------------------------
    # Spread blowout detection
    # ------------------------------------------------------------------

    def check_spread_blowout(
        self,
        position_id: str,
        best_bid: float,
        best_ask: float,
        premium: float,
        max_spread_pct: float = 0.03,
    ) -> Optional[ExitSignal]:
        """Check if bid-ask spread has blown out beyond threshold.

        If spread >= max_spread_pct of premium, return an immediate exit signal.
        Gracefully returns None if order book data is missing (bid/ask <= 0)
        or premium <= 0.
        """
        with self._lock:
            mp = self._positions.get(position_id)
            if mp is None:
                return None

        # Skip if no valid order book data
        if best_bid <= 0 or best_ask <= 0 or premium <= 0:
            return None

        spread = best_ask - best_bid
        spread_pct = spread / premium

        if spread_pct >= max_spread_pct:
            logger.info(
                "TradeManager: SPREAD BLOWOUT for %s — spread=%.2f (%.1f%% of premium %.2f)",
                position_id, spread, spread_pct * 100, premium,
            )
            # Use midpoint as exit price (best realistic fill in illiquid conditions)
            exit_price = (best_bid + best_ask) / 2
            return ExitSignal(position_id, ExitReason.SPREAD_BLOWOUT, exit_price)

        return None

    # ------------------------------------------------------------------
    # CVD-based breakeven
    # ------------------------------------------------------------------

    def apply_cvd_breakeven(self, position_id: str, cvd_slope: float) -> bool:
        """Move SL to breakeven if CVD confirms the trade direction.

        LONG + positive CVD slope = buyers confirming -> breakeven.
        SHORT + negative CVD slope = sellers confirming -> breakeven.
        Returns True if SL was moved, False otherwise.
        """
        with self._lock:
            mp = self._positions.get(position_id)
            if mp is None:
                return False

            if not self.config.cvd_breakeven:
                return False

            if mp.breakeven_set:
                return False  # already at breakeven

            # Check CVD direction alignment
            if mp.is_long and cvd_slope > 0:
                mp.stop_loss = mp.entry_price
                mp.breakeven_set = True
                logger.info(
                    "TradeManager: CVD breakeven for %s — CVD slope %.2f confirms LONG",
                    position_id, cvd_slope,
                )
                return True
            elif not mp.is_long and cvd_slope < 0:
                mp.stop_loss = mp.entry_price
                mp.breakeven_set = True
                logger.info(
                    "TradeManager: CVD breakeven for %s — CVD slope %.2f confirms SHORT",
                    position_id, cvd_slope,
                )
                return True

            return False

    # ------------------------------------------------------------------
    # Cooldown query
    # ------------------------------------------------------------------

    def check_imbalance_tighten(
        self, position_id: str, imbalances: list, current_price: float,
    ) -> bool:
        """Tighten SL if stacked imbalances oppose position. Returns True if tightened.

        Opposing imbalances (SELL for LONG, BUY for SHORT) trigger a 30%
        tighten of the current price-to-SL distance.
        """
        with self._lock:
            pos = self._positions.get(position_id)
            if pos is None or not imbalances:
                return False

            opposing = [
                im for im in imbalances
                if (pos.side == "LONG" and im.direction == "SELL")
                or (pos.side == "SHORT" and im.direction == "BUY")
            ]
            if not opposing:
                return False

            # Tighten SL by 30% of current distance
            if pos.is_long:
                distance = current_price - pos.stop_loss
                if distance > 0:
                    pos.stop_loss = pos.stop_loss + distance * 0.3
                    logger.info(
                        "TradeManager: imbalance tighten for %s — SL moved to %.2f",
                        position_id, pos.stop_loss,
                    )
                    return True
            else:
                distance = pos.stop_loss - current_price
                if distance > 0:
                    pos.stop_loss = pos.stop_loss - distance * 0.3
                    logger.info(
                        "TradeManager: imbalance tighten for %s — SL moved to %.2f",
                        position_id, pos.stop_loss,
                    )
                    return True
            return False

    def in_cooldown(self, current_time: float | None = None) -> bool:
        """True if a recent exit was taken and we should not re-enter yet."""
        with self._lock:
            if self._last_exit_time == 0:
                return False
            now = current_time if current_time is not None else time.time()
            return (now - self._last_exit_time) < self.config.cooldown_seconds

    @property
    def has_managed_positions(self) -> bool:
        with self._lock:
            return len(self._positions) > 0
