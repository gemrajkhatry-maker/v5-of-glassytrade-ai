"""Stateless ExitEngine — deterministic exit logic operating on Position objects.

This replaces the stateful TradeManager.  Instead of maintaining its own
``_positions`` dict, ExitEngine receives a ``Position`` object on every call
and mutates it directly (stop-loss advances, cushion-state transitions, etc.).

Session-level risk state (daily losses, circuit breakers, cooldown) is still
kept inside ExitEngine because it is NOT position-level state — it spans the
whole trading session.

Design rationale
----------------
The LLM was trained on *entry* decisions only.  Trade management must be
**rule-based and deterministic**.  Separating the exit engine from the position
registry makes both easier to test and removes the dual-state problem.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from typing import Optional

from app.domain.trading.models.enums import CushionState, MarketStateCodec  # noqa: F401 – re-exported
from app.domain.trading.models.entities import Position
from app.domain.trading.models.enums import Side
from app.shared.timezones import IST

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ExitDecision — immutable exit recommendation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExitDecision:
    """Immutable exit recommendation from the ExitEngine."""

    position_id: str
    reason: str          # ExitReason constant
    exit_price: float
    partial_pct: float = 0.0  # 0 = full close, >0 = partial close percentage


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


# ManagedPosition removed in Task 1C — Position entity is now the single representation


# ---------------------------------------------------------------------------
# Exit reasons
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
# ExitSignal — legacy compat (same shape as ExitDecision but mutable)
# ---------------------------------------------------------------------------


@dataclass
class ExitSignal:
    """Returned by check_position when an exit is triggered."""

    position_id: str
    reason: str
    exit_price: float


# PositionConsistency removed in Task 1C — dual-state reconciliation no longer needed


# ---------------------------------------------------------------------------
# Session-aware time stop table
# ---------------------------------------------------------------------------

TIME_STOP_TABLE: dict[tuple[str, str], float] = {
    ("MORNING", "BALANCED"): 1200,
    ("MORNING", "IMBALANCED"): 2700,
    ("AFTERNOON", "BALANCED"): 900,
    ("AFTERNOON", "IMBALANCED"): 1800,
}

EXPIRY_TIME_STOP: float = 600


# ---------------------------------------------------------------------------
# ExitEngine (stateless core) + TradeManager (full stateful facade)
# ---------------------------------------------------------------------------


class ExitEngine:
    """Stateless exit engine — takes Position objects, returns ExitDecision.

    Session-level risk state (daily losses, circuit breakers, cooldown) is
    still managed here because it spans the whole session, not a single
    position.

    All position-level state is stored directly on Position entities.
    Callers pass Position objects to check_position() and other methods.
    """

    MAX_DAILY_LOSSES = 3

    def __init__(
        self, config: TradeManagerConfig | None = None, persist_fn=None
    ) -> None:
        self._config = config or TradeManagerConfig()
        # Public alias used by tests and callers
        self.config = self._config
        self._lock = threading.RLock()
        self._persist_fn = persist_fn
        # Session-level risk state (NOT position-level)
        self._global_daily_losses: int = 0
        self._symbol_daily_losses: dict[str, int] = {}
        self._symbol_consecutive_losses: dict[str, int] = {}
        self._symbol_last_stop_price: dict[str, float] = {}
        self._load_daily_losses()
        self._daily_loss_reset_time: float = self._next_ist_midnight()
        self._session_realized_pnl: float = 0.0
        # Cooldown tracking per symbol (session-level)
        self._last_exit_time: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Daily loss tracking
    # ------------------------------------------------------------------

    @staticmethod
    def _next_ist_midnight() -> float:
        now = datetime.now(IST)
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        return tomorrow.timestamp()

    def _load_daily_losses(self) -> None:
        if not self._persist_fn:
            return
        try:
            raw = self._persist_fn("daily_losses_v2", None)
            if raw:
                data = json.loads(raw)
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
        if time.time() >= self._daily_loss_reset_time:
            self._global_daily_losses = 0
            self._symbol_daily_losses = {}
            self._symbol_consecutive_losses = {}
            self._symbol_last_stop_price = {}
            self._daily_loss_reset_time = self._next_ist_midnight()
            self._save_daily_losses()

    def record_loss(self, symbol: str, stop_price: float = 0.0) -> None:
        with self._lock:
            self._maybe_reset_daily()
            self._global_daily_losses += 1
            self._symbol_daily_losses[symbol] = self._symbol_daily_losses.get(symbol, 0) + 1
            self._symbol_consecutive_losses[symbol] = (
                self._symbol_consecutive_losses.get(symbol, 0) + 1
            )
            if stop_price > 0:
                self._symbol_last_stop_price[symbol] = stop_price
            logger.info(
                "ExitEngine: daily losses - global=%d/%d, %s=%d/%d",
                self._global_daily_losses,
                self.MAX_DAILY_LOSSES * 3,
                symbol,
                self._symbol_daily_losses[symbol],
                self.MAX_DAILY_LOSSES,
            )
            self._save_daily_losses()

    def is_daily_limit_reached(self, symbol: str) -> bool:
        with self._lock:
            self._maybe_reset_daily()
            if self._global_daily_losses >= (self.MAX_DAILY_LOSSES * 3):
                return True
            return self._symbol_daily_losses.get(symbol, 0) >= self.MAX_DAILY_LOSSES

    def should_block_entry(
        self, symbol: str, current_price: float = 0.0, current_atr: float = 0.0
    ) -> bool:
        if self.is_daily_limit_reached(symbol):
            return True
        with self._lock:
            cons_losses = self._symbol_consecutive_losses.get(symbol, 0)
            if cons_losses >= 2 and current_price > 0 and current_atr > 0:
                last_price = self._symbol_last_stop_price.get(symbol, 0.0)
                if last_price > 0:
                    distance = abs(current_price - last_price)
                    if distance < (1.5 * current_atr):
                        logger.warning(
                            f"ExitEngine: Circuit Breaker ACTIVE for {symbol}. "
                            f"Distance from last stop ({distance:.1f}) < required buffer ({1.5 * current_atr:.1f})."
                        )
                        return True
        return False

    def reset_consecutive_losses(self, symbol: str) -> None:
        with self._lock:
            if symbol in self._symbol_consecutive_losses:
                self._symbol_consecutive_losses[symbol] = 0

    # ------------------------------------------------------------------
    # Session PnL / Cushion System
    # ------------------------------------------------------------------

    def add_realized_pnl(self, realized_pnl: float) -> None:
        with self._lock:
            self._session_realized_pnl += realized_pnl
            logger.info(
                f"ExitEngine: realized PnL added: {realized_pnl:.2f}. Session total: {self._session_realized_pnl:.2f}"
            )

    def compute_dynamic_risk(
        self,
        base_capital: float,
        session_realized_pnl: float | None = None,
    ) -> tuple[float, str]:
        """Compute dynamic risk percentage based on cushion system.

        ``session_realized_pnl`` overrides the internal tracker when provided,
        making the method usable as a pure function without instance state.
        """
        if session_realized_pnl is not None:
            pnl = session_realized_pnl
        else:
            with self._lock:
                pnl = self._session_realized_pnl

        if pnl <= 0:
            return 0.0025, "Conservative"

        cushion_risk_amount = (base_capital * 0.0035) + (pnl * 0.20)
        risk_pct = cushion_risk_amount / base_capital
        max_allowed_from_profit = (base_capital * 0.0025) + (pnl * 0.30)
        max_allowed_pct = min(0.0050, max_allowed_from_profit / base_capital)
        final_risk_pct = min(risk_pct, max_allowed_pct)

        if final_risk_pct >= 0.0040:
            return final_risk_pct, "Momentum (Aggressive)"
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
        if is_expiry:
            phase_stop = EXPIRY_TIME_STOP
        elif session_phase:
            key = (session_phase.upper(), market_state.upper())
            phase_stop = TIME_STOP_TABLE.get(key, 0.0)
            if phase_stop == 0.0:
                phase_stop = 7200.0 if MarketStateCodec.is_imbalanced(market_state) else 1800.0
        else:
            phase_stop = 7200.0 if MarketStateCodec.is_imbalanced(market_state) else 1800.0

        if time_to_close > 0:
            near_close_stop = time_to_close - 300.0
            if near_close_stop > 0:
                phase_stop = min(phase_stop, near_close_stop)
            else:
                phase_stop = 1.0

        return phase_stop

    # ------------------------------------------------------------------
    # RR Filter
    # ------------------------------------------------------------------

    @staticmethod
    def is_valid_rr(
        entry: float, sl: float, tp: float, min_rr: float | None = None
    ) -> bool:
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
    # Stateless core: check_position(Position, price) → ExitDecision | None
    # ------------------------------------------------------------------

    def check_position(
        self,
        position: Position,
        current_price: float,
        current_time: float | None = None,
        time_to_close: float = 0.0,
        cvd_slope: float = 0.0,
        stop_price: float | None = None,
    ) -> Optional[ExitSignal]:
        """Check all exit rules for a Position entity.

        This is the stateless API — the Position object is mutated directly
        for lifecycle state (stop-loss advances, cushion-state transitions, etc.).

        Returns an ``ExitSignal`` (or ``None``).
        """
        return self._check_position_entity(
            position,
            current_price,
            current_time=current_time,
            time_to_close=time_to_close,
            cvd_slope=cvd_slope,
            stop_price=stop_price,
        )

    def _check_position_entity(
        self,
        position: Position,
        current_price: float,
        current_time: float | None = None,
        time_to_close: float = 0.0,
        cvd_slope: float = 0.0,
        stop_price: float | None = None,
    ) -> Optional[ExitSignal]:
        """Stateless exit logic operating on a Position entity."""
        with self._lock:
            now = current_time if current_time is not None else time.time()
            position.tick_count += 1

            is_long = position.side == Side.LONG or position.side.value == "LONG"
            entry_price = float(position.entry_price)
            sl = float(position.stop_loss)
            initial_stop = float(position.initial_stop)

            # ----- 1. STOP LOSS -----
            sl_check = stop_price if stop_price is not None else current_price
            if is_long and sl_check <= sl:
                logger.info(
                    "ExitEngine: STOP LOSS hit for %s at %.2f", position.id, current_price
                )
                self.record_loss(position.symbol, current_price)
                position.advance_cushion_state(CushionState.CLOSED)
                return ExitSignal(position.id, ExitReason.STOP_LOSS, current_price)

            if not is_long and sl_check >= sl:
                logger.info(
                    "ExitEngine: STOP LOSS hit for %s at %.2f", position.id, current_price
                )
                self.record_loss(position.symbol, current_price)
                position.advance_cushion_state(CushionState.CLOSED)
                return ExitSignal(position.id, ExitReason.STOP_LOSS, current_price)

            # ----- MAE/MFE tracking -----
            unrealised = (
                (current_price - entry_price) if is_long else (entry_price - current_price)
            )
            mfe = float(position.mfe)
            mae = float(position.mae)
            if unrealised > mfe:
                position.mfe = Decimal(str(unrealised))
            if unrealised < -mae:
                position.mae = Decimal(str(-unrealised))

            # ----- ATR TRAILING STOP -----
            if position.partial_taken:
                from app.domain.constants import ATR_TRAIL_ACTIVATION_R, ATR_TRAIL_STEP_PCT

                if initial_stop > 0:
                    initial_risk = abs(entry_price - initial_stop)
                    peak_profit = float(position.peak_profit)
                    if unrealised > peak_profit:
                        position.peak_profit = Decimal(str(unrealised))
                        peak_profit = unrealised

                    if initial_risk > 0:
                        activation_threshold = ATR_TRAIL_ACTIVATION_R * initial_risk
                        if peak_profit >= activation_threshold:
                            if not position.atr_trail_active:
                                position.atr_trail_active = True
                                position.advance_cushion_state(CushionState.TRAILING)
                                logger.info(
                                    "ExitEngine: ATR trail ARMED for %s — peak_profit=%.2f >= %.2f (1R)",
                                    position.id,
                                    peak_profit,
                                    activation_threshold,
                                )

                            retain_pct = 1.0 - ATR_TRAIL_STEP_PCT
                            if is_long:
                                atr_trail_sl = entry_price + peak_profit * retain_pct
                                if atr_trail_sl > float(position.stop_loss):
                                    old_sl = float(position.stop_loss)
                                    position.stop_loss = Decimal(str(atr_trail_sl))
                                    logger.info(
                                        "ExitEngine: ATR trail advanced for %s (LONG) — SL %.2f -> %.2f",
                                        position.symbol,
                                        old_sl,
                                        atr_trail_sl,
                                    )
                            else:
                                atr_trail_sl = entry_price - peak_profit * retain_pct
                                if atr_trail_sl < float(position.stop_loss):
                                    old_sl = float(position.stop_loss)
                                    position.stop_loss = Decimal(str(atr_trail_sl))
                                    logger.info(
                                        "ExitEngine: ATR trail advanced for %s (SHORT) — SL %.2f -> %.2f",
                                        position.symbol,
                                        old_sl,
                                        atr_trail_sl,
                                    )

            # ----- TIME STOP / SCRATCH -----
            if position.tick_count < 5:
                return None

            # Resolve entry_time: Position stores it as ISO string
            entry_time_epoch: float
            if position.entry_time:
                try:
                    from datetime import datetime as _dt, timezone as _tz
                    dt = _dt.fromisoformat(position.entry_time)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=_tz.utc)
                    entry_time_epoch = dt.timestamp()
                except (ValueError, TypeError):
                    entry_time_epoch = now  # fallback: no time stop
            else:
                entry_time_epoch = now

            # Derive market_state from position metadata
            market_state = "BALANCED"
            if position.metadata:
                ms = position.metadata.get("market_state_model", "")
                if ms and ("trend" in str(ms).lower() or "imbalance" in str(ms).lower()):
                    market_state = "IMBALANCED"

            if position.session_phase or position.is_expiry:
                new_stop = self.get_session_time_stop(
                    market_state=market_state,
                    session_phase=position.session_phase,
                    is_expiry=position.is_expiry,
                    time_to_close=time_to_close,
                )
                position.applied_time_stop = max(position.applied_time_stop, new_stop)
                max_hold = position.applied_time_stop
            else:
                max_hold = self._config.max_hold_seconds
                if MarketStateCodec.is_imbalanced(market_state):
                    max_hold = 7200

            if (now - entry_time_epoch) >= max_hold:
                price_move_pct = abs(current_price - entry_price) / entry_price if entry_price else 0.0
                if price_move_pct < self._config.scratch_threshold_pct:
                    logger.info(
                        "ExitEngine: SCRATCH for %s after %.0fs (move=%.5f)",
                        position.id,
                        now - entry_time_epoch,
                        price_move_pct,
                    )
                    position.advance_cushion_state(CushionState.CLOSED)
                    return ExitSignal(position.id, ExitReason.SCRATCH, current_price)
                else:
                    logger.info(
                        "ExitEngine: TIME STOP for %s after %.0fs",
                        position.id,
                        now - entry_time_epoch,
                    )
                    position.advance_cushion_state(CushionState.CLOSED)
                    return ExitSignal(position.id, ExitReason.TIME_STOP, current_price)

            return None

    def get_position_metrics(
        self,
        position: Position,
    ) -> dict:
        """Return lifecycle metrics from a Position entity."""
        return {
            "tick_count": position.tick_count,
            "runner_active": position.runner_active,
            "partial_taken": position.partial_taken,
            "mae": float(position.mae),
            "mfe": float(position.mfe),
            "cushion_state": position.cushion_state.value,
        }

    # ------------------------------------------------------------------
    # Scale-in (Position-based API)
    # ------------------------------------------------------------------
    
    def check_scale_in(self, position: Position, current_price: float) -> float:
        """Stateless scale-in check operating on a Position entity."""
        with self._lock:
            if position.scale_step >= 3:
                return 0.0
    
            is_long = position.side == Side.LONG or position.side.value == "LONG"
            entry_price = float(position.entry_price)
            initial_stop = float(position.initial_stop)
            risk = abs(entry_price - initial_stop)
    
            if risk > 0:
                if is_long and current_price < entry_price:
                    return 0.0
                if not is_long and current_price > entry_price:
                    return 0.0
    
            confirm_price = float(position.scale_confirm_price)
            breakout_price = float(position.scale_breakout_price)
    
            if position.scale_step == 1:
                triggered = (
                    (is_long and current_price >= confirm_price > 0)
                    or (not is_long and current_price <= confirm_price and confirm_price > 0)
                )
                if triggered:
                    position.scale_step = 2
                    logger.info(
                        "ExitEngine: SCALE-IN step 2 (confirmation) for %s at %.2f — adding 30%%",
                        position.id, current_price,
                    )
                    return 0.3
    
            if position.scale_step == 2:
                triggered = (
                    (is_long and current_price >= breakout_price > 0)
                    or (not is_long and current_price <= breakout_price and breakout_price > 0)
                )
                if triggered:
                    position.scale_step = 3
                    logger.info(
                        "ExitEngine: SCALE-IN step 3 (breakout) for %s at %.2f — adding final 30%%",
                        position.id, current_price,
                    )
                    return 0.3
    
            return 0.0

    # ------------------------------------------------------------------
    # CVD helpers (Position-based API)
    # ------------------------------------------------------------------

    def apply_cvd_kill_signal(
        self,
        position: Position,
        cvd_divergence: str,
        current_price: float,
    ) -> Optional[ExitSignal]:
        """Apply CVD kill signal to a Position entity."""
        is_long = position.side == Side.LONG or position.side.value == "LONG"

        if is_long and cvd_divergence == "BEARISH_DIV":
            if not position.partial_taken:
                position.stop_loss = position.entry_price
                logger.info("ExitEngine: CVD kill signal — moved SL to break-even for %s", position.id)
            else:
                logger.info("ExitEngine: CVD kill signal — scratching %s", position.id)
                position.advance_cushion_state(CushionState.CLOSED)
                return ExitSignal(position.id, ExitReason.SCRATCH, current_price)

        if not is_long and cvd_divergence == "BULLISH_DIV":
            if not position.partial_taken:
                position.stop_loss = position.entry_price
                logger.info("ExitEngine: CVD kill signal — moved SL to break-even for %s", position.id)
            else:
                logger.info("ExitEngine: CVD kill signal — scratching %s", position.id)
                position.advance_cushion_state(CushionState.CLOSED)
                return ExitSignal(position.id, ExitReason.SCRATCH, current_price)

        return None

    def apply_cvd_breakeven(self, position: Position, cvd_slope: float) -> bool:
        """Apply CVD breakeven to a Position entity."""
        if not self._config.cvd_breakeven:
            return False

        if position.breakeven_set:
            return False

        is_long = position.side == Side.LONG or position.side.value == "LONG"
        entry_price = float(position.entry_price)

        if is_long and cvd_slope >= self._config.cvd_breakeven_min_slope:
            position.stop_loss = Decimal(str(entry_price))
            position.breakeven_set = True
            position.advance_cushion_state(CushionState.CUSHIONED)
            logger.info(
                "ExitEngine: CVD breakeven for %s — CVD slope %.2f confirms LONG",
                position.id, cvd_slope,
            )
            return True
        elif not is_long and cvd_slope <= -self._config.cvd_breakeven_min_slope:
            position.stop_loss = Decimal(str(entry_price))
            position.breakeven_set = True
            position.advance_cushion_state(CushionState.CUSHIONED)
            logger.info(
                "ExitEngine: CVD breakeven for %s — CVD slope %.2f confirms SHORT",
                position.id, cvd_slope,
            )
            return True

        return False

    # ------------------------------------------------------------------
    # VWAP trail
    # ------------------------------------------------------------------
    # VWAP trail (Position-based API)
    # ------------------------------------------------------------------

    def apply_vwap_trail(
        self,
        position: Position,
        current_price: float,
        vwap: float,
        vwap_upper_1: float,
        vwap_lower_1: float,
        vwap_upper_2: float,
        vwap_lower_2: float,
    ) -> None:
        """Apply VWAP-based trailing stop to a Position entity.

        At 1.5R profit, SL moves to nearest VWAP band above entry (for LONG)
        or below entry (for SHORT). At 2 sigma overextension, SL tightened
        to 50% of current distance.
        """
        from app.domain.services.tick_utils import round_to_tick

        ts = self._config.tick_size

        is_long = position.side == Side.LONG or position.side.value == "LONG"
        entry = float(position.entry_price)
        initial_risk = abs(entry - float(position.initial_stop))
        if initial_risk <= 0:
            return

        unrealised = (current_price - entry) if is_long else (entry - current_price)
        unrealised_r = unrealised / initial_risk

        if unrealised_r < 1.5:
            return

        bands = sorted([vwap, vwap_upper_1, vwap_lower_1, vwap_upper_2, vwap_lower_2])
        current_sl = float(position.stop_loss)

        if is_long:
            valid_bands = [b for b in bands if b < current_price and b > entry]
            trail_sl = max(valid_bands) if valid_bands else entry + initial_risk * 1.5
            min_trail = entry + initial_risk * 1.5
            trail_sl = max(trail_sl, min_trail)
            if current_price >= vwap_upper_2:
                current_distance = current_price - current_sl
                tightened = current_price - (current_distance * 0.5)
                trail_sl = max(trail_sl, tightened)
            if trail_sl > current_sl:
                if ts > 0:
                    trail_sl = round_to_tick(trail_sl, ts)
                position.stop_loss = Decimal(str(trail_sl))
                logger.info(
                    "ExitEngine: VWAP trail for %s — SL moved to %.2f (%.1fR)",
                    position.id, trail_sl, unrealised_r,
                )
        else:
            valid_bands = [b for b in bands if b > current_price and b < entry]
            trail_sl = min(valid_bands) if valid_bands else entry - initial_risk * 1.5
            max_trail = entry - initial_risk * 1.5
            trail_sl = min(trail_sl, max_trail)
            if current_price <= vwap_lower_2:
                current_distance = current_sl - current_price
                tightened = current_price + (current_distance * 0.5)
                trail_sl = min(trail_sl, tightened)
            if trail_sl < current_sl:
                if ts > 0:
                    trail_sl = round_to_tick(trail_sl, ts)
                position.stop_loss = Decimal(str(trail_sl))
                logger.info(
                    "ExitEngine: VWAP trail for %s — SL moved to %.2f (%.1fR)",
                    position.id, trail_sl, unrealised_r,
                )

    # ------------------------------------------------------------------
    # Spread blowout (Position-based API)
    # ------------------------------------------------------------------

    def check_spread_blowout(
        self,
        position: Position,
        best_bid: float,
        best_ask: float,
        premium: float,
        max_spread_pct: float = 0.03,
    ) -> Optional[ExitSignal]:
        """Check for spread blowout and return exit signal if triggered.

        Spread >= max_spread_pct of premium triggers exit.
        """
        if best_bid <= 0 or best_ask <= 0 or premium <= 0:
            return None

        spread = best_ask - best_bid
        spread_pct = spread / premium

        if spread_pct >= max_spread_pct:
            logger.info(
                "ExitEngine: SPREAD BLOWOUT for %s — spread=%.2f (%.1f%% of premium %.2f)",
                position.id, spread, spread_pct * 100, premium,
            )
            exit_price = (best_bid + best_ask) / 2
            position.advance_cushion_state(CushionState.CLOSED)
            return ExitSignal(position.id, ExitReason.SPREAD_BLOWOUT, exit_price)

        return None

    # ------------------------------------------------------------------
    # Adjust SL (Position-based API)
    # ------------------------------------------------------------------

    def adjust_stop_loss(self, position: Position, new_sl: float) -> bool:
        """Adjust stop-loss on a Position entity.

        LONG: new_sl must be > current stop_loss (tighten up)
        SHORT: new_sl must be < current stop_loss (tighten down)
        Returns True if adjusted, False if rejected.
        """
        from app.domain.services.tick_utils import round_to_tick

        ts = self._config.tick_size
        if ts > 0:
            new_sl = round_to_tick(new_sl, ts)

        is_long = position.side == Side.LONG or position.side.value == "LONG"
        entry = float(position.entry_price)
        current_sl = float(position.stop_loss)

        if position.breakeven_set:
            if is_long and new_sl < entry:
                logger.info(
                    "ExitEngine: adjust_stop_loss REJECTED for %s — breakeven set, new SL %.2f < entry %.2f",
                    position.id, new_sl, entry,
                )
                return False
            if not is_long and new_sl > entry:
                logger.info(
                    "ExitEngine: adjust_stop_loss REJECTED for %s — breakeven set, new SL %.2f > entry %.2f",
                    position.id, new_sl, entry,
                )
                return False

        if is_long:
            if new_sl <= current_sl:
                logger.info(
                    "ExitEngine: adjust_stop_loss REJECTED for %s — new SL %.2f <= current %.2f (LONG can only tighten up)",
                    position.id, new_sl, current_sl,
                )
                return False
        else:
            if new_sl >= current_sl:
                logger.info(
                    "ExitEngine: adjust_stop_loss REJECTED for %s — new SL %.2f >= current %.2f (SHORT can only tighten down)",
                    position.id, new_sl, current_sl,
                )
                return False

        position.stop_loss = Decimal(str(new_sl))
        logger.info(
            "ExitEngine: stop-loss adjusted for %s — %.2f -> %.2f",
            position.id, current_sl, new_sl,
        )
        return True

    # ------------------------------------------------------------------
    # Imbalance tighten (Position-based API)
    # ------------------------------------------------------------------

    def check_imbalance_tighten(
        self,
        position: Position,
        imbalances: list,
        current_price: float,
    ) -> bool:
        """Check for opposing imbalances and tighten stop-loss if found.

        If an imbalance opposes the position direction, SL is tightened
        by 30% of the distance to current price.
        """
        if not imbalances:
            return False

        is_long = position.side == Side.LONG or position.side.value == "LONG"
        side_str = "LONG" if is_long else "SHORT"

        opposing = [
            im
            for im in imbalances
            if (side_str == "LONG" and im.direction == "SELL")
            or (side_str == "SHORT" and im.direction == "BUY")
        ]
        if not opposing:
            return False

        current_sl = float(position.stop_loss)

        if is_long:
            distance = current_price - current_sl
            if distance > 0:
                new_sl = current_sl + distance * 0.3
                position.stop_loss = Decimal(str(new_sl))
                logger.info(
                    "ExitEngine: imbalance tighten for %s — SL moved to %.2f",
                    position.id, new_sl,
                )
                return True
        else:
            distance = current_sl - current_price
            if distance > 0:
                new_sl = current_sl - distance * 0.3
                position.stop_loss = Decimal(str(new_sl))
                logger.info(
                    "ExitEngine: imbalance tighten for %s — SL moved to %.2f",
                    position.id, new_sl,
                )
                return True
        return False

    # ------------------------------------------------------------------
    # Cooldown tracking (session-level)
    # ------------------------------------------------------------------

    def in_cooldown(self, symbol: str, current_time: float | None = None) -> bool:
        with self._lock:
            last_exit = self._last_exit_time.get(symbol, 0.0)
            if last_exit == 0.0:
                return False
            now = current_time if current_time is not None else time.time()
            return (now - last_exit) < self._config.cooldown_seconds

    def record_exit_time(self, symbol: str, current_time: float | None = None) -> None:
        """Record the time of an exit for cooldown tracking."""
        with self._lock:
            self._last_exit_time[symbol] = current_time if current_time is not None else time.time()


# ---------------------------------------------------------------------------
# Backward compatibility alias
# ---------------------------------------------------------------------------

# Remove after all callers migrate to ExitEngine directly.
TradeManager = ExitEngine
