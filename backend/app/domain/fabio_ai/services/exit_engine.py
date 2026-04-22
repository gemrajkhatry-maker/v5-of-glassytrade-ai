"""Stateless ExitEngine — deterministic exit logic operating on Position objects.

This replaces the stateful TradeManager.  Instead of maintaining its own
``_positions`` dict, ExitEngine receives a ``Position`` object on every call
and mutates it directly (stop-loss advances, cushion-state transitions, etc.).

Session-level risk state (daily losses, circuit breakers, cooldown) is
delegated to LossTracker.

Design rationale
----------------
The LLM was trained on *entry* decisions only.  Trade management must be
**rule-based and deterministic**.  Separating the exit engine from the position
registry makes both easier to test and removes the dual-state problem.

Architecture
------------
ExitEngine now delegates to focused services:
- exit_rules.py: Pure exit rule functions (no state)
- trail_engine.py: Trailing stop logic (ATR, VWAP, imbalance, CVD)
- scale_manager.py: Scale-in management (40/30/30)
- loss_tracker.py: Daily loss tracking and circuit breakers
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

from app.domain.ports.storage import IKeyValueStorage
from app.domain.trading.models.enums import CushionState, MarketStateCodec
from app.domain.trading.models.entities import Position
from app.domain.trading.models.enums import Side
from app.domain.fabio_ai.services.exit_rules import (
    check_spread_blowout,
    check_time_stop_with_price,
    get_session_time_stop,
    is_valid_rr,
    update_excursions,
    TIME_STOP_TABLE,
    EXPIRY_TIME_STOP,
)
from app.domain.fabio_ai.services.exit_signal import ExitSignal
from app.domain.fabio_ai.services.trail_engine import TrailEngine
from app.domain.fabio_ai.services.scale_manager import ScaleManager
from app.domain.fabio_ai.services.loss_tracker import LossTracker

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


# ---------------------------------------------------------------------------
# Exit reasons
# ---------------------------------------------------------------------------


class ExitReason:
    """Exit reason constants."""
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
# ExitEngine (orchestrator)
# ---------------------------------------------------------------------------


class ExitEngine:
    """Stateless exit engine — takes Position objects, returns ExitDecision.

    Session-level risk state (daily losses, circuit breakers, cooldown) is
    delegated to LossTracker.

    All position-level state is stored directly on Position entities.
    Callers pass Position objects to check_position() and other methods.

    Dependency Injection:
        Prefer `storage` parameter (IKeyValueStorage) for DIP compliance.
        The `persist_fn` parameter is deprecated but supported for backward compatibility.
    """

    MAX_DAILY_LOSSES = 3

    def __init__(
        self,
        config: TradeManagerConfig | None = None,
        storage: IKeyValueStorage | None = None,
        persist_fn: Callable[[str, str | None], str | None] | None = None,
    ) -> None:
        self._config = config or TradeManagerConfig()
        # Public alias used by tests and callers
        self.config = self._config

        # Initialize delegate services
        self._trail_engine = TrailEngine(
            atr_trail_activation_r=self._config.trail_activation_r,
            atr_trail_step_pct=self._config.trail_step_pct,
            tick_size=self._config.tick_size,
            cvd_breakeven=self._config.cvd_breakeven,
            cvd_breakeven_min_slope=self._config.cvd_breakeven_min_slope,
        )
        self._scale_manager = ScaleManager()
        self._loss_tracker = LossTracker(
            storage=storage,
            persist_fn=persist_fn,
            max_daily_losses=self.MAX_DAILY_LOSSES,
        )
        # Expose loss_tracker's internal state for test compatibility
        # Tests may modify MAX_DAILY_LOSSES at runtime
        self._global_daily_losses = 0
        self._symbol_daily_losses = {}

    # ------------------------------------------------------------------
    # Daily loss tracking (delegates to LossTracker)
    # ------------------------------------------------------------------

    def record_loss(self, symbol: str, stop_price: float = 0.0) -> None:
        """Record a loss for circuit breaker tracking."""
        self._loss_tracker.record_loss(symbol, stop_price)
        # Sync state for test access
        state = self._loss_tracker.get_state()
        self._global_daily_losses = state["global_daily_losses"]
        self._symbol_daily_losses = state["symbol_daily_losses"]

    def is_daily_limit_reached(self, symbol: str) -> bool:
        """Check if daily loss limit is reached."""
        # Use instance MAX_DAILY_LOSSES to allow test override
        return self._loss_tracker.is_daily_limit_reached_with_override(
            symbol, self.MAX_DAILY_LOSSES
        )

    def should_block_entry(
        self, symbol: str, current_price: float = 0.0, current_atr: float = 0.0
    ) -> bool:
        """Check if entry should be blocked due to circuit breakers."""
        # Use instance MAX_DAILY_LOSSES to allow test override
        return self._loss_tracker.should_block_entry_with_override(
            symbol, current_price, current_atr, self.MAX_DAILY_LOSSES
        )

    def reset_consecutive_losses(self, symbol: str) -> None:
        """Reset consecutive loss counter for a symbol."""
        self._loss_tracker.reset_consecutive_losses(symbol)

    # ------------------------------------------------------------------
    # Session PnL / Cushion System (delegates to LossTracker)
    # ------------------------------------------------------------------

    def add_realized_pnl(self, realized_pnl: float) -> None:
        """Add to session realized PnL."""
        self._loss_tracker.add_realized_pnl(realized_pnl)

    def compute_dynamic_risk(
        self,
        base_capital: float,
        session_realized_pnl: float | None = None,
    ) -> tuple[float, str]:
        """Compute dynamic risk percentage based on cushion system."""
        return self._loss_tracker.compute_dynamic_risk(base_capital, session_realized_pnl)

    # ------------------------------------------------------------------
    # Session-aware time stop (static, delegates to exit_rules)
    # ------------------------------------------------------------------

    @staticmethod
    def get_session_time_stop(
        market_state: str,
        session_phase: str,
        is_expiry: bool,
        time_to_close: float,
    ) -> float:
        """Calculate session-aware time stop."""
        return get_session_time_stop(market_state, session_phase, is_expiry, time_to_close)

    # ------------------------------------------------------------------
    # RR Filter (static, delegates to exit_rules)
    # ------------------------------------------------------------------

    @staticmethod
    def is_valid_rr(
        entry: float, sl: float, tp: float, min_rr: float | None = None
    ) -> bool:
        """Validate risk-reward ratio."""
        return is_valid_rr(entry, sl, tp, min_rr)

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
        now = current_time if current_time is not None else time.time()
        position.tick_count += 1

        is_long = position.side == Side.LONG or position.side.value == "LONG"
        sl = float(position.stop_loss)

        # ----- 1. STOP LOSS -----
        sl_check = stop_price if stop_price is not None else current_price
        if (is_long and sl_check <= sl) or (not is_long and sl_check >= sl):
            logger.info(
                "ExitEngine: STOP LOSS hit for %s at %.2f", position.id, current_price
            )
            self.record_loss(position.symbol, current_price)
            position.advance_cushion_state(CushionState.CLOSED)
            return ExitSignal(position.id, ExitReason.STOP_LOSS, current_price)

        # ----- 2. MAE/MFE tracking -----
        update_excursions(position, current_price)

        # ----- 3. ATR TRAILING STOP (delegates to TrailEngine) -----
        self._trail_engine.apply_atr_trail(position, current_price)

        # ----- 4. TIME STOP / SCRATCH -----
        if position.tick_count < 5:
            return None

        return check_time_stop_with_price(
            position=position,
            current_price=current_price,
            current_time=now,
            time_to_close=time_to_close,
            max_hold_seconds=self._config.max_hold_seconds,
            scratch_threshold_pct=self._config.scratch_threshold_pct,
        )

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
    # Scale-in (delegates to ScaleManager)
    # ------------------------------------------------------------------

    def check_scale_in(self, position: Position, current_price: float) -> float:
        """Stateless scale-in check operating on a Position entity."""
        return self._scale_manager.check_scale_in(position, current_price)

    # ------------------------------------------------------------------
    # CVD helpers (delegates to TrailEngine)
    # ------------------------------------------------------------------

    def apply_cvd_kill_signal(
        self,
        position: Position,
        cvd_divergence: str,
        current_price: float,
    ) -> Optional[ExitSignal]:
        """Apply CVD kill signal to a Position entity."""
        return self._trail_engine.apply_cvd_kill_signal(position, cvd_divergence, current_price)

    def apply_cvd_breakeven(self, position: Position, cvd_slope: float) -> bool:
        """Apply CVD breakeven to a Position entity."""
        return self._trail_engine.apply_cvd_breakeven(position, cvd_slope)

    # ------------------------------------------------------------------
    # VWAP trail (delegates to TrailEngine)
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
        """Apply VWAP-based trailing stop to a Position entity."""
        self._trail_engine.apply_vwap_trail(
            position=position,
            current_price=current_price,
            vwap=vwap,
            vwap_upper_1=vwap_upper_1,
            vwap_lower_1=vwap_lower_1,
            vwap_upper_2=vwap_upper_2,
            vwap_lower_2=vwap_lower_2,
        )

    # ------------------------------------------------------------------
    # Spread blowout (delegates to exit_rules)
    # ------------------------------------------------------------------

    def check_spread_blowout(
        self,
        position: Position,
        best_bid: float,
        best_ask: float,
        premium: float,
        max_spread_pct: float = 0.03,
    ) -> Optional[ExitSignal]:
        """Check for spread blowout and return exit signal if triggered."""
        return check_spread_blowout(position, best_bid, best_ask, premium, max_spread_pct)

    # ------------------------------------------------------------------
    # Adjust SL (delegates to TrailEngine)
    # ------------------------------------------------------------------

    def adjust_stop_loss(self, position: Position, new_sl: float) -> bool:
        """Adjust stop-loss on a Position entity."""
        return self._trail_engine.adjust_stop_loss(position, new_sl)

    # ------------------------------------------------------------------
    # Imbalance tighten (delegates to TrailEngine)
    # ------------------------------------------------------------------

    def check_imbalance_tighten(
        self,
        position: Position,
        imbalances: list,
        current_price: float,
    ) -> bool:
        """Check for opposing imbalances and tighten stop-loss if found."""
        return self._trail_engine.apply_imbalance_tighten(position, imbalances, current_price)

    # ------------------------------------------------------------------
    # Cooldown tracking (delegates to LossTracker)
    # ------------------------------------------------------------------

    def in_cooldown(self, symbol: str, current_time: float | None = None) -> bool:
        """Check if symbol is in cooldown period after exit."""
        return self._loss_tracker.in_cooldown(
            symbol, current_time, self._config.cooldown_seconds
        )

    def record_exit_time(self, symbol: str, current_time: float | None = None) -> None:
        """Record the time of an exit for cooldown tracking."""
        self._loss_tracker.record_exit_time(symbol, current_time)


# ---------------------------------------------------------------------------
# Backward compatibility alias
# ---------------------------------------------------------------------------

# Remove after all callers migrate to ExitEngine directly.
TradeManager = ExitEngine
