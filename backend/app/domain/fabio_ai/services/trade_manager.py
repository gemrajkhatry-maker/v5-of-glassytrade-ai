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

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Optional

from app.domain.trading.models.enums import MarketStateCodec
from app.shared.timezones import IST

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class TradeManagerConfig:
    """All thresholds are expressed as fractions (e.g. 0.005 = 0.5%)."""

    stop_loss_pct: float = 0.005  # 0.5% hard stop
    take_profit_pct: float = 0.015  # 1.5% take profit
    trail_activation_pct: float = 0.50  # activate trail after 50% of TP (legacy)
    trail_step_pct: float = (
        0.20  # Fabio Gap #14: trail 20% behind peak (tighter for options with theta)
    )
    max_hold_seconds: float = 1800  # 30 min time stop for scalps (Fabio: < 30 min)
    cooldown_seconds: float = 30  # no re-entry for 30s after exit
    partial_tp_pct: float = 0.50  # take partial at 50% of TP distance
    partial_size_pct: float = 0.50  # close 50% of position on partial
    scratch_threshold_pct: float = 0.0005  # 0.05% movement threshold for scratch
    # Runner logic (Fabio: close 75% at target, trail 25% as runner)
    runner_close_pct: float = 0.75  # close 75% at primary target
    runner_trail_pct: float = 0.25  # trail remaining 25%
    # CVD-based breakeven: move SL to entry when CVD confirms direction
    cvd_breakeven: bool = True
    cvd_breakeven_min_slope: float = 0.5  # minimum CVD slope magnitude to trigger
    # Trail activation at 1R instead of 50% TP distance
    trail_activation_r: float = 1.0
    # Instrument tick size for SL/TP rounding
    tick_size: float = 0.05


# ---------------------------------------------------------------------------
# Position Tracker (lightweight, per-symbol)
# ---------------------------------------------------------------------------


@dataclass
class ManagedPosition:
    """Internal state for a position being managed by the TradeManager."""

    position_id: str
    symbol: str  # The trading symbol (e.g. NIFTY24DEC20000CE)
    side: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    market_state: str = "BALANCED"  # "BALANCED" or "IMBALANCED"

    entry_time: float = 0.0  # callers must set; 0 = use time.time() fallback
    initial_stop: float = 0.0  # original stop for R-multiple calculation
    partial_taken: bool = False  # True after partial profit booking
    runner_active: bool = False  # True when runner portion is being trailed
    mae: float = 0.0  # Maximum Adverse Excursion
    mfe: float = 0.0  # Maximum Favorable Excursion
    tick_count: int = 0  # ticks since entry (grace period guard)

    # Breakeven tracking
    breakeven_set: bool = False  # True once SL moved to entry (1R or CVD)
    entry_cvd_direction: str = ""  # "LONG" or "SHORT" — set by CVD confirmation

    # Session-aware time stop fields
    session_phase: str = ""  # "MORNING" or "AFTERNOON"
    is_expiry: bool = False  # True on options expiry day

    # Reconciliation protection
    registered_at: float = (
        0.0  # time.time() when registered — protects from race condition
    )
    applied_time_stop: float = 0.0  # computed session time stop (never shrinks)

    # Scale-in state (Fabio Rule 4: 40/30/30)
    scale_step: int = 1  # 1=initial(40%), 2=confirmation(+30%), 3=breakout(+30%)
    scale_confirm_price: float = 0.0  # price level that triggers step 2
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


@dataclass(frozen=True)
class PositionConsistency:
    """Comparison between portfolio-open positions and lifecycle-managed positions."""

    open_position_ids: tuple[str, ...]
    managed_position_ids: tuple[str, ...]
    unmanaged_open_ids: tuple[str, ...]
    stale_managed_ids: tuple[str, ...]

    @property
    def is_consistent(self) -> bool:
        return not self.unmanaged_open_ids and not self.stale_managed_ids


# ---------------------------------------------------------------------------
# Session-aware time stop table
# ---------------------------------------------------------------------------

# (session_phase, market_state) -> time stop in seconds
TIME_STOP_TABLE: dict[tuple[str, str], float] = {
    ("MORNING", "BALANCED"): 1200,  # 20 min
    ("MORNING", "IMBALANCED"): 2700,  # 45 min
    ("AFTERNOON", "BALANCED"): 900,  # 15 min
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

    def __init__(
        self, config: TradeManagerConfig | None = None, persist_fn=None
    ) -> None:
        self.config = config or TradeManagerConfig()
        self._lock = threading.RLock()
        self._positions: dict[str, ManagedPosition] = {}
        self._last_exit_time: dict[str, float] = {}  # Per-symbol exit time
        self._persist_fn = (
            persist_fn  # Optional callback: (key, value) → persists crash-safe state
        )
        # Track daily losses globally AND per-symbol
        self._global_daily_losses: int = 0
        self._symbol_daily_losses: dict[str, int] = {}
        # Track consecutive losses for ATR-based circuit breaker
        self._symbol_consecutive_losses: dict[str, int] = {}
        self._symbol_last_stop_price: dict[str, float] = {}
        self._load_daily_losses()
        self._daily_loss_reset_time: float = self._next_ist_midnight()
        self._session_realized_pnl: float = 0.0  # Tracks PnL for the current session

        # Ensure clean startup — clear any stale positions
        self._positions.clear()

    # ------------------------------------------------------------------
    # Daily loss tracking
    # ------------------------------------------------------------------

    @staticmethod
    def _next_ist_midnight() -> float:
        """Return epoch timestamp of the next IST (UTC+5:30) midnight.

        NSE/MCX daily loss limits must reset with the Indian trading day,
        not UTC midnight (which would reset at 05:30 AM IST mid-session).
        """
        now = datetime.now(IST)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(
            days=1
        )
        return tomorrow.timestamp()

    def _load_daily_losses(self) -> None:
        """Load persisted daily loss counts (crash-safe recovery)."""
        if not self._persist_fn:
            return
        try:
            raw = self._persist_fn("daily_losses_v2", None)  # get mode
            if raw:
                data = json.loads(raw)
                # Only restore if same IST date
                today = datetime.now(IST).strftime("%Y-%m-%d")
                if data.get("date") == today:
                    self._global_daily_losses = data.get("global_count", 0)
                    self._symbol_daily_losses = data.get("symbol_counts", {})
                    logger.info(
                        "Restored daily losses from DB: global=%d, symbols=%s",
                        self._global_daily_losses,
                        self._symbol_daily_losses,
                    )
        except Exception:
            logger.debug("Failed to load daily losses from DB", exc_info=True)

    def _save_daily_losses(self) -> None:
        """Persist daily loss counts to survive crashes."""
        if not self._persist_fn:
            return
        try:
            today = datetime.now(IST).strftime("%Y-%m-%d")
            payload = {
                "date": today,
                "global_count": self._global_daily_losses,
                "symbol_counts": self._symbol_daily_losses,
            }
            self._persist_fn("daily_losses_v2", json.dumps(payload))
        except Exception:
            logger.debug("Failed to persist daily losses", exc_info=True)

    def _maybe_reset_daily(self) -> None:
        """Reset daily loss counters if we have passed midnight IST."""
        if time.time() >= self._daily_loss_reset_time:
            self._global_daily_losses = 0
            self._symbol_daily_losses = {}
            self._symbol_consecutive_losses = {}
            self._symbol_last_stop_price = {}
            self._daily_loss_reset_time = self._next_ist_midnight()
            self._save_daily_losses()

    def record_loss(self, symbol: str, stop_price: float = 0.0) -> None:
        """Record a stop-loss exit for daily loss tracking and circuit breakers."""
        with self._lock:
            self._maybe_reset_daily()
            self._global_daily_losses += 1
            self._symbol_daily_losses[symbol] = (
                self._symbol_daily_losses.get(symbol, 0) + 1
            )

            # Increment consecutive losses and record the price level
            self._symbol_consecutive_losses[symbol] = (
                self._symbol_consecutive_losses.get(symbol, 0) + 1
            )
            if stop_price > 0:
                self._symbol_last_stop_price[symbol] = stop_price

            # Use global limit for individual symbols, but can be configured per-symbol later
            logger.info(
                "TradeManager: daily losses - global=%d/%d, %s=%d/%d",
                self._global_daily_losses,
                self.MAX_DAILY_LOSSES * 3,  # Global limit allows more overall
                symbol,
                self._symbol_daily_losses[symbol],
                self.MAX_DAILY_LOSSES,
            )
            self._save_daily_losses()

    def is_daily_limit_reached(self, symbol: str) -> bool:
        """True if the daily loss limit has been reached globally or for the specific symbol."""
        with self._lock:
            self._maybe_reset_daily()

            # Hard block if global multi-symbol limit is reached (e.g. market is untradable)
            if self._global_daily_losses >= (self.MAX_DAILY_LOSSES * 3):
                return True

            # Hard block if symbol limit is reached
            symbol_losses = self._symbol_daily_losses.get(symbol, 0)
            return symbol_losses >= self.MAX_DAILY_LOSSES

    def should_block_entry(
        self, symbol: str, current_price: float = 0.0, current_atr: float = 0.0
    ) -> bool:
        """True if new entries should be blocked for this symbol (daily limit or consecutive stop-outs)."""
        if self.is_daily_limit_reached(symbol):
            return True

        # Circuit Breaker: Prevent re-entry near the exact same zone if we just took 2+ consecutive losses
        with self._lock:
            cons_losses = self._symbol_consecutive_losses.get(symbol, 0)
            if cons_losses >= 2 and current_price > 0 and current_atr > 0:
                last_price = self._symbol_last_stop_price.get(symbol, 0.0)
                if last_price > 0:
                    distance = abs(current_price - last_price)
                    # Block entry if price hasn't moved at least 1.5 ATR away from the bloodbath zone
                    if distance < (1.5 * current_atr):
                        logger.warning(
                            f"TradeManager: Circuit Breaker ACTIVE for {symbol}. "
                            f"Distance from last stop ({distance:.1f}) < required buffer ({1.5 * current_atr:.1f})."
                        )
                        return True

        return False

    def reset_consecutive_losses(self, symbol: str) -> None:
        """Reset consecutive losses (e.g., after a profitable trade)."""
        with self._lock:
            if symbol in self._symbol_consecutive_losses:
                self._symbol_consecutive_losses[symbol] = 0

    # ------------------------------------------------------------------
    # Intraday Compounding (Cushion System)
    # ------------------------------------------------------------------

    def add_realized_pnl(self, realized_pnl: float) -> None:
        """Add to the session's realized PnL."""
        with self._lock:
            self._session_realized_pnl += realized_pnl
            logger.info(
                f"TradeManager: realized PnL added: {realized_pnl:.2f}. Session total: {self._session_realized_pnl:.2f}"
            )

    def compute_dynamic_risk(self, base_capital: float) -> tuple[float, str]:
        """Compute the dynamic risk percentage based on the current session PnL (Cushion System).

        Returns:
            Tuple of (risk_pct, risk_tier_name)
        """
        with self._lock:
            pnl = self._session_realized_pnl

        # Base conservative risk (0.25%) when starting or in drawdown
        if pnl <= 0:
            return 0.0025, "Conservative"

        # Cushion built: scale risk up to 0.40% max, adding 20% of session profit
        cushion_risk_amount = (base_capital * 0.0035) + (pnl * 0.20)
        risk_pct = cushion_risk_amount / base_capital

        # Cap risk at 0.50% absolutely, or 30% of session profit if smaller
        max_allowed_from_profit = (base_capital * 0.0025) + (pnl * 0.30)
        max_allowed_pct = min(0.0050, max_allowed_from_profit / base_capital)

        final_risk_pct = min(risk_pct, max_allowed_pct)

        # Tier names for LLM Context
        if final_risk_pct >= 0.0040:
            return final_risk_pct, "Momentum (Aggressive)"
        else:
            return final_risk_pct, "Cushion Built (Scaling)"

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
                phase_stop = (
                    7200.0 if MarketStateCodec.is_imbalanced(market_state) else 1800.0
                )
        else:
            # No session info: use static fallback
            phase_stop = (
                7200.0 if MarketStateCodec.is_imbalanced(market_state) else 1800.0
            )

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
    def is_valid_rr(
        entry: float, sl: float, tp: float, min_rr: float | None = None
    ) -> bool:
        """Check that risk:reward ratio is at least 1:min_rr.

        Returns True if the trade offers sufficient reward relative to risk.
        Default threshold from plan FR-07-08: 1.5
        """
        from app.domain.constants import MIN_RR_RATIO

        threshold = min_rr if min_rr is not None else MIN_RR_RATIO
        if entry <= 0:
            return False
        risk = abs(entry - sl)
        reward = abs(tp - entry)
        if risk <= 0 or reward <= 0:
            return False
        return (reward / risk) >= threshold

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_position(
        self,
        position_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        market_state: str = "BALANCED",
        allow_trail: bool = False,  # retained for backward compat; no-op
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
        # Ensure compatible types for calculation
        entry_dec = (
            float(entry_price) if hasattr(entry_price, "__float__") else entry_price
        )
        stop_dec = float(stop_loss) if hasattr(stop_loss, "__float__") else stop_loss
        tp_dec = (
            float(take_profit) if hasattr(take_profit, "__float__") else take_profit
        )

        risk = abs(entry_dec - stop_dec)
        tp_dist = abs(tp_dec - entry_dec)

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
            symbol=symbol,
            side=side,
            entry_price=float(entry_dec),
            stop_loss=float(stop_dec),
            take_profit=float(tp_dec),
            market_state=market_state,
            initial_stop=float(stop_dec),
            entry_time=entry_time if entry_time is not None else time.time(),
            scale_step=1 if enable_scale_in else 3,  # 3 = fully deployed
            scale_confirm_price=confirm_price,
            scale_breakout_price=breakout_price,
            session_phase=session_phase,
            is_expiry=is_expiry,
            registered_at=time.time(),
        )
        with self._lock:
            self._positions[position_id] = mp
            pos_count = len(self._positions)

        logger.info(
            f"TradeManager: registered {side} {position_id} "
            f"entry={float(entry_price):.2f} SL={float(stop_loss):.2f} TP={float(take_profit):.2f} "
            f"total_positions={pos_count}"
            f"{' [scale-in enabled]' if enable_scale_in else ''}"
        )

    def unregister_position(
        self, position_id: str, current_time: float | None = None
    ) -> None:
        """Stop managing a position (call after exit is executed)."""
        with self._lock:
            if position_id in self._positions:
                symbol = self._positions[position_id].symbol
                del self._positions[position_id]
                self._last_exit_time[symbol] = (
                    current_time if current_time is not None else time.time()
                )
                logger.info(f"TradeManager: unregistered {position_id} ({symbol})")

    def update_market_state(self, position_id: str, market_state: str) -> None:
        """Update market state for open position (enables dynamic time stops).

        If market transitions BALANCED->IMBALANCED mid-trade, the time stop
        will be extended. The reverse is protected by the never-shrink guard in
        check_position().
        """
        mp = self._positions.get(position_id)
        if mp and mp.market_state != market_state:
            mp.market_state = market_state

    # ------------------------------------------------------------------
    # Tick-level check
    # ------------------------------------------------------------------

    def check_position(
        self,
        position_id: str,
        current_price: float,
        current_time: float | None = None,
        time_to_close: float = 0.0,
        cvd_slope: float = 0.0,
        stop_price: float | None = None,  # tick.low for LONG, tick.high for SHORT
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
            sl_check = stop_price if stop_price is not None else current_price
            if mp.is_long and sl_check <= mp.stop_loss:
                logger.info(
                    f"TradeManager: STOP LOSS hit for {position_id} at {current_price:.2f}"
                )
                self.record_loss(mp.symbol, current_price)
                return ExitSignal(position_id, ExitReason.STOP_LOSS, current_price)

            if not mp.is_long and (stop_price if stop_price is not None else current_price) >= mp.stop_loss:
                logger.info(
                    f"TradeManager: STOP LOSS hit for {position_id} at {current_price:.2f}"
                )
                self.record_loss(mp.symbol, current_price)
                return ExitSignal(position_id, ExitReason.STOP_LOSS, current_price)

            # ----- MAE/MFE tracking -----
            unrealised = (
                (current_price - mp.entry_price)
                if mp.is_long
                else (mp.entry_price - current_price)
            )
            if unrealised > mp.mfe:
                mp.mfe = unrealised
            if unrealised < -mp.mae:
                mp.mae = -unrealised  # mae stored as positive value

            # ----- PROFIT EXITS & TRAILING -----
            # Break-Even, P1/P2/P3 rules, and trail logic are handled natively
            # upstream by the PartitionExitManager. TradeManager checks hard stops.

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
                if MarketStateCodec.is_imbalanced(mp.market_state):
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

            # Fabio rule: never scale-in to a losing position
            risk = abs(mp.entry_price - mp.initial_stop)
            if risk > 0:
                if mp.is_long and current_price < mp.entry_price:
                    return 0.0  # Below entry, don't add to losers
                if not mp.is_long and current_price > mp.entry_price:
                    return 0.0  # Above entry, don't add to losers

            if mp.scale_step == 1:
                # Step 2: confirmation — price moved favorably past confirm level
                triggered = (
                    mp.is_long and current_price >= mp.scale_confirm_price > 0
                ) or (
                    not mp.is_long
                    and current_price <= mp.scale_confirm_price
                    and mp.scale_confirm_price > 0
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
                    mp.is_long and current_price >= mp.scale_breakout_price > 0
                ) or (
                    not mp.is_long
                    and current_price <= mp.scale_breakout_price
                    and mp.scale_breakout_price > 0
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
        self,
        position_id: str,
        cvd_divergence: str,
        current_price: float,
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
                    logger.info(
                        f"TradeManager: CVD kill signal — moved SL to break-even for {position_id}"
                    )
                else:
                    # Already partial — scratch out
                    logger.info(
                        f"TradeManager: CVD kill signal — scratching {position_id}"
                    )
                    return ExitSignal(position_id, ExitReason.SCRATCH, current_price)

            # SHORT + BULLISH divergence = sellers losing steam → tighten
            if not mp.is_long and cvd_divergence == "BULLISH_DIV":
                if not mp.partial_taken:
                    mp.stop_loss = mp.entry_price
                    logger.info(
                        f"TradeManager: CVD kill signal — moved SL to break-even for {position_id}"
                    )
                else:
                    logger.info(
                        f"TradeManager: CVD kill signal — scratching {position_id}"
                    )
                    return ExitSignal(position_id, ExitReason.SCRATCH, current_price)

            return None

    # apply_cvd_breakeven is defined below (line ~1001) — the authoritative version.
    # (Removed duplicate that was previously here at line ~730.)

    # ------------------------------------------------------------------
    # Overseer helpers
    # ------------------------------------------------------------------

    def get_position_state(
        self,
        position_id: str,
        current_price: float,
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
            # Convert Decimal to float for calculations
            entry = (
                float(mp.entry_price)
                if hasattr(mp.entry_price, "__float__")
                else mp.entry_price
            )
            sl = (
                float(mp.stop_loss)
                if hasattr(mp.stop_loss, "__float__")
                else mp.stop_loss
            )
            tp = (
                float(mp.take_profit)
                if hasattr(mp.take_profit, "__float__")
                else mp.take_profit
            )

            unrealised = (
                (current_price - entry) if mp.is_long else (entry - current_price)
            )
            unrealised_pct = unrealised / entry if entry else 0.0

            # Distance to SL / TP as percentage of entry price
            distance_to_sl = (
                abs(current_price - mp.stop_loss) / mp.entry_price
                if mp.entry_price
                else 0.0
            )
            distance_to_tp = (
                abs(mp.take_profit - current_price) / mp.entry_price
                if mp.entry_price
                else 0.0
            )

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
                "runner_active": mp.runner_active,
                "market_state": mp.market_state,
                "mae": round(mp.mae, 4),
                "mfe": round(mp.mfe, 4),
                "r_multiple": round(
                    unrealised / abs(mp.entry_price - mp.initial_stop), 2
                )
                if abs(mp.entry_price - mp.initial_stop) > 0
                else 0.0,
            }

    def get_position_metrics(
        self, position_id: str
    ) -> Optional[dict[str, float | int | bool]]:
        """Return stable lifecycle metrics for a managed position.

        This is the public query API used by handlers instead of reaching into
        the private `_positions` dict directly.
        """
        with self._lock:
            mp = self._positions.get(position_id)
            if mp is None:
                return None
            return {
                "tick_count": mp.tick_count,
                "runner_active": mp.runner_active,
                "partial_taken": mp.partial_taken,
                "mae": mp.mae,
                "mfe": mp.mfe,
            }

    def get_managed_position_ids(
        self,
        *,
        symbol: str | None = None,
        open_ids: set[str] | None = None,
    ) -> tuple[str, ...]:
        """Return managed position IDs matching the given filters."""
        with self._lock:
            ids: list[str] = []
            for mp in self._positions.values():
                if symbol is not None and mp.symbol != symbol:
                    continue
                if open_ids is not None and mp.position_id not in open_ids:
                    continue
                ids.append(mp.position_id)
            return tuple(ids)

    def get_position_consistency(
        self,
        open_ids: set[str],
        *,
        symbol: str | None = None,
    ) -> PositionConsistency:
        """Compare portfolio-open position IDs with managed lifecycle state."""
        with self._lock:
            managed_ids = {
                mp.position_id
                for mp in self._positions.values()
                if symbol is None or mp.symbol == symbol
            }
            if symbol is None:
                filtered_open_ids = set(open_ids)
            else:
                known_other_symbol_ids = {
                    mp.position_id
                    for mp in self._positions.values()
                    if mp.symbol != symbol
                }
                filtered_open_ids = {
                    position_id
                    for position_id in open_ids
                    if position_id not in known_other_symbol_ids
                }
            return PositionConsistency(
                open_position_ids=tuple(sorted(filtered_open_ids)),
                managed_position_ids=tuple(sorted(managed_ids)),
                unmanaged_open_ids=tuple(sorted(filtered_open_ids - managed_ids)),
                stale_managed_ids=tuple(sorted(managed_ids - filtered_open_ids)),
            )

    def sync_with_open_position_ids(
        self,
        open_ids: set[str],
        *,
        symbol: str | None = None,
        current_time: float | None = None,
    ) -> tuple[str, ...]:
        """Remove managed positions that no longer exist in the portfolio view.

        This is the canonical reconciliation hook between the portfolio's open
        positions and the lifecycle manager's managed-position registry.

        Protects recently registered positions (< 5s) from being removed by
        race conditions between signal execution and tick processing threads.
        """
        consistency = self.get_position_consistency(open_ids, symbol=symbol)
        stale_ids = list(consistency.stale_managed_ids)

        # Protect recently registered positions from race condition removal
        now = current_time or time.time()
        with self._lock:
            protected = {
                pid
                for pid in stale_ids
                if pid in self._positions
                and (now - self._positions[pid].registered_at) < 5.0
            }
            stale_ids = [pid for pid in stale_ids if pid not in protected]
            if protected:
                logger.info(
                    "TradeManager: protecting %d recently registered positions from reconciliation",
                    len(protected),
                )

        for position_id in stale_ids:
            self.unregister_position(position_id, current_time=current_time)
        return tuple(stale_ids)

    def adjust_stop_loss(self, position_id: str, new_sl: float) -> bool:
        """Tighten the stop-loss for a managed position.

        For LONG positions, new_sl must be > current stop_loss (tighten up).
        For SHORT positions, new_sl must be < current stop_loss (tighten down).
        Returns True if adjusted, False if rejected or position not found.

        SL is rounded to tick_size boundary before applying.
        """
        from app.domain.services.tick_utils import round_to_tick

        # Round new SL to tick boundary
        ts = self.config.tick_size
        if ts > 0:
            new_sl = round_to_tick(new_sl, ts)

        with self._lock:
            mp = self._positions.get(position_id)
            if mp is None:
                logger.warning(
                    f"TradeManager: adjust_stop_loss — position {position_id} not found"
                )
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
        - SL is rounded to tick_size boundary.
        """
        from app.domain.services.tick_utils import round_to_tick

        ts = self.config.tick_size

        with self._lock:
            mp = self._positions.get(position_id)
            if mp is None:
                return

            entry = mp.entry_price
            initial_risk = abs(entry - mp.initial_stop)
            if initial_risk <= 0:
                return

            unrealised = (
                (current_price - entry) if mp.is_long else (entry - current_price)
            )
            unrealised_r = unrealised / initial_risk

            if unrealised_r < 1.5:
                return  # Not enough profit to trail

            bands = sorted(
                [vwap, vwap_upper_1, vwap_lower_1, vwap_upper_2, vwap_lower_2]
            )

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

                # Never lower SL (ratchet only) — round to tick boundary
                if trail_sl > mp.stop_loss:
                    mp.stop_loss = round_to_tick(trail_sl, ts) if ts > 0 else trail_sl
                    logger.info(
                        "TradeManager: VWAP trail for %s — SL moved to %.2f (%.1fR)",
                        position_id,
                        mp.stop_loss,
                        unrealised_r,
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

                # Never loosen SL (ratchet only) — round to tick boundary
                if trail_sl < mp.stop_loss:
                    mp.stop_loss = round_to_tick(trail_sl, ts) if ts > 0 else trail_sl
                    logger.info(
                        "TradeManager: VWAP trail for %s — SL moved to %.2f (%.1fR)",
                        position_id,
                        mp.stop_loss,
                        unrealised_r,
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
                position_id,
                spread,
                spread_pct * 100,
                premium,
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

            # Check CVD direction alignment with minimum slope threshold
            if mp.is_long and cvd_slope >= self.config.cvd_breakeven_min_slope:
                mp.stop_loss = mp.entry_price
                mp.breakeven_set = True
                logger.info(
                    "TradeManager: CVD breakeven for %s — CVD slope %.2f confirms LONG",
                    position_id,
                    cvd_slope,
                )
                return True
            elif not mp.is_long and cvd_slope <= -self.config.cvd_breakeven_min_slope:
                mp.stop_loss = mp.entry_price
                mp.breakeven_set = True
                logger.info(
                    "TradeManager: CVD breakeven for %s — CVD slope %.2f confirms SHORT",
                    position_id,
                    cvd_slope,
                )
                return True

            return False

    # ------------------------------------------------------------------
    # Cooldown query
    # ------------------------------------------------------------------

    def check_imbalance_tighten(
        self,
        position_id: str,
        imbalances: list,
        current_price: float,
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
                im
                for im in imbalances
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
                        position_id,
                        pos.stop_loss,
                    )
                    return True
            else:
                distance = pos.stop_loss - current_price
                if distance > 0:
                    pos.stop_loss = pos.stop_loss - distance * 0.3
                    logger.info(
                        "TradeManager: imbalance tighten for %s — SL moved to %.2f",
                        position_id,
                        pos.stop_loss,
                    )
                    return True
            return False

    def in_cooldown(self, symbol: str, current_time: float | None = None) -> bool:
        """True if a recent exit was taken on this symbol and we should not re-enter yet."""
        with self._lock:
            last_exit = self._last_exit_time.get(symbol, 0.0)
            if last_exit == 0.0:
                return False
            now = current_time if current_time is not None else time.time()
            return (now - last_exit) < self.config.cooldown_seconds

    def has_managed_positions(self, symbol: str) -> bool:
        """True if this specific symbol currently has an actively managed position.

        O(n) scan over all positions — acceptable since MAX_CONCURRENT_POSITIONS=5.
        For larger scale, maintain a per-symbol reference count.
        """
        with self._lock:
            return any(mp.symbol == symbol for mp in self._positions.values())
