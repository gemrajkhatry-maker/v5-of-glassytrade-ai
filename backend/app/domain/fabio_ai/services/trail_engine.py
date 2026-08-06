"""Trailing stop logic — ATR, VWAP, imbalance, CVD.

This module contains all trailing stop management for positions.
Each method mutates the Position's stop_loss field when conditions are met.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import TYPE_CHECKING

from app.domain.trading.models.enums import CushionState, Side
from app.domain.services.tick_utils import round_to_tick

if TYPE_CHECKING:
    from app.domain.trading.models.entities import Position

from app.domain.fabio_ai.services.exit_signal import ExitSignal

logger = logging.getLogger(__name__)


class TrailEngine:
    """Manages all trailing stop logic for positions.

    This is a stateless class - all state is stored on Position objects.
    """

    def __init__(
        self,
        atr_trail_activation_r: float = 1.0,
        atr_trail_step_pct: float = 0.20,
        tick_size: float = 0.05,
        cvd_breakeven: bool = True,
        cvd_breakeven_min_slope: float = 0.5,
    ):
        """Initialize trail engine with configuration.

        Args:
            atr_trail_activation_r: Activate trail after this many R profit.
            atr_trail_step_pct: Trail this fraction behind peak profit.
            tick_size: Instrument tick size for rounding.
            cvd_breakeven: Enable CVD-based breakeven.
            cvd_breakeven_min_slope: Minimum CVD slope to trigger breakeven.
        """
        self._atr_trail_activation_r = atr_trail_activation_r
        self._atr_trail_step_pct = atr_trail_step_pct
        self._tick_size = tick_size
        self._cvd_breakeven = cvd_breakeven
        self._cvd_breakeven_min_slope = cvd_breakeven_min_slope

    # -----------------------------------------------------------------------
    # ATR Trailing Stop
    # -----------------------------------------------------------------------

    def apply_atr_trail(
        self,
        position: "Position",
        current_price: float,
    ) -> None:
        """ATR-based trailing: arm at 1R, trail 20% behind peak.

        This method should only be called after partial TP is taken
        (position.partial_taken == True).

        The trail activates when peak_profit >= 1R (activation threshold).
        Once active, SL advances to retain (1 - step_pct) of peak profit.

        Args:
            position: Position to update.
            current_price: Current market price.
        """
        if not position.partial_taken:
            return

        is_long = position.side == Side.LONG or position.side.value == "LONG"
        entry_price = float(position.entry_price)
        initial_stop = float(position.initial_stop)

        if initial_stop <= 0:
            return

        initial_risk = abs(entry_price - initial_stop)

        # Update peak profit
        unrealised = (
            (current_price - entry_price) if is_long else (entry_price - current_price)
        )
        peak_profit = float(position.peak_profit)
        if unrealised > peak_profit:
            position.peak_profit = Decimal(str(unrealised))
            peak_profit = unrealised

        if initial_risk <= 0:
            return

        activation_threshold = self._atr_trail_activation_r * initial_risk

        if peak_profit < activation_threshold:
            return

        # Arm the trail
        if not position.atr_trail_active:
            position.atr_trail_active = True
            position.advance_cushion_state(CushionState.TRAILING)
            logger.info(
                "TrailEngine: ATR trail ARMED for %s — peak_profit=%.2f >= %.2f (1R)",
                position.id,
                peak_profit,
                activation_threshold,
            )

        # Calculate trail SL
        retain_pct = 1.0 - self._atr_trail_step_pct
        current_sl = float(position.stop_loss)

        if is_long:
            atr_trail_sl = entry_price + peak_profit * retain_pct
            if atr_trail_sl > current_sl:
                position.stop_loss = Decimal(str(atr_trail_sl))
                logger.info(
                    "TrailEngine: ATR trail advanced for %s (LONG) — SL %.2f -> %.2f",
                    position.symbol,
                    current_sl,
                    atr_trail_sl,
                )
        else:
            atr_trail_sl = entry_price - peak_profit * retain_pct
            if atr_trail_sl < current_sl:
                position.stop_loss = Decimal(str(atr_trail_sl))
                logger.info(
                    "TrailEngine: ATR trail advanced for %s (SHORT) — SL %.2f -> %.2f",
                    position.symbol,
                    current_sl,
                    atr_trail_sl,
                )

    # -----------------------------------------------------------------------
    # VWAP Trailing Stop
    # -----------------------------------------------------------------------

    def apply_vwap_trail(
        self,
        position: "Position",
        current_price: float,
        vwap: float,
        vwap_upper_1: float,
        vwap_lower_1: float,
        vwap_upper_2: float,
        vwap_lower_2: float,
    ) -> None:
        """Trail SL to VWAP bands.

        At 1.5R profit, SL moves to nearest VWAP band above entry (for LONG)
        or below entry (for SHORT). At 2 sigma overextension, SL tightened
        to 50% of current distance.

        Args:
            position: Position to update.
            current_price: Current market price.
            vwap: VWAP base line.
            vwap_upper_1: 1st upper VWAP band.
            vwap_lower_1: 1st lower VWAP band.
            vwap_upper_2: 2nd upper VWAP band (2 sigma).
            vwap_lower_2: 2nd lower VWAP band (2 sigma).
        """
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
            valid_bands = [b for b in bands if entry < b < current_price]
            trail_sl = max(valid_bands) if valid_bands else current_sl

            # Tighten at 2 sigma overextension
            if current_price >= vwap_upper_2:
                current_distance = current_price - current_sl
                tightened = current_price - (current_distance * 0.5)
                trail_sl = max(trail_sl, tightened)

            if trail_sl > current_sl:
                if self._tick_size > 0:
                    trail_sl = round_to_tick(trail_sl, self._tick_size)
                position.stop_loss = Decimal(str(trail_sl))
                logger.info(
                    "TrailEngine: VWAP trail for %s — SL moved to %.2f (%.1fR)",
                    position.id, trail_sl, unrealised_r,
                )
        else:
            valid_bands = [b for b in bands if entry > b > current_price]
            trail_sl = min(valid_bands) if valid_bands else current_sl

            # Tighten at 2 sigma overextension
            if current_price <= vwap_lower_2:
                current_distance = current_sl - current_price
                tightened = current_price + (current_distance * 0.5)
                trail_sl = min(trail_sl, tightened)

            if trail_sl < current_sl:
                if self._tick_size > 0:
                    trail_sl = round_to_tick(trail_sl, self._tick_size)
                position.stop_loss = Decimal(str(trail_sl))
                logger.info(
                    "TrailEngine: VWAP trail for %s — SL moved to %.2f (%.1fR)",
                    position.id, trail_sl, unrealised_r,
                )

    # -----------------------------------------------------------------------
    # Imbalance Tighten
    # -----------------------------------------------------------------------

    def apply_imbalance_tighten(
        self,
        position: "Position",
        imbalances: list,
        current_price: float,
    ) -> bool:
        """Tighten SL on stacked imbalance opposition.

        If an imbalance opposes the position direction, SL is tightened
        by 30% of the distance to current price.

        Args:
            position: Position to update.
            imbalances: List of imbalance objects with 'direction' field.
            current_price: Current market price.

        Returns:
            True if SL was tightened, False otherwise.
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
                    "TrailEngine: imbalance tighten for %s — SL moved to %.2f",
                    position.id, new_sl,
                )
                return True
        else:
            distance = current_sl - current_price
            if distance > 0:
                new_sl = current_sl - distance * 0.3
                position.stop_loss = Decimal(str(new_sl))
                logger.info(
                    "TrailEngine: imbalance tighten for %s — SL moved to %.2f",
                    position.id, new_sl,
                )
                return True

        return False

    # -----------------------------------------------------------------------
    # CVD Breakeven
    # -----------------------------------------------------------------------

    def apply_cvd_breakeven(
        self,
        position: "Position",
        cvd_slope: float,
    ) -> bool:
        """Move SL to breakeven on CVD confirmation.

        When CVD slope confirms the position direction and has sufficient
        magnitude, SL is moved to entry price.

        Args:
            position: Position to update.
            cvd_slope: Current CVD slope value.

        Returns:
            True if breakeven was set, False otherwise.
        """
        if not self._cvd_breakeven:
            return False

        if position.breakeven_set:
            return False

        is_long = position.side == Side.LONG or position.side.value == "LONG"
        entry_price = float(position.entry_price)

        if is_long and cvd_slope >= self._cvd_breakeven_min_slope:
            position.stop_loss = Decimal(str(entry_price))
            position.breakeven_set = True
            position.advance_cushion_state(CushionState.CUSHIONED)
            logger.info(
                "TrailEngine: CVD breakeven for %s — CVD slope %.2f confirms LONG",
                position.id, cvd_slope,
            )
            return True
        elif not is_long and cvd_slope <= -self._cvd_breakeven_min_slope:
            position.stop_loss = Decimal(str(entry_price))
            position.breakeven_set = True
            position.advance_cushion_state(CushionState.CUSHIONED)
            logger.info(
                "TrailEngine: CVD breakeven for %s — CVD slope %.2f confirms SHORT",
                position.id, cvd_slope,
            )
            return True

        return False

    # -----------------------------------------------------------------------
    # CVD Kill Signal
    # -----------------------------------------------------------------------

    def apply_cvd_kill_signal(
        self,
        position: "Position",
        cvd_divergence: str,
        current_price: float,
    ) -> "ExitSignal | None":
        """Exit on CVD divergence.

        For LONG positions: BEARISH_DIV triggers exit or BE.
        For SHORT positions: BULLISH_DIV triggers exit or BE.

        Args:
            position: Position to update.
            cvd_divergence: CVD divergence type (BEARISH_DIV/BULLISH_DIV).
            current_price: Current market price.

        Returns:
            ExitSignal if exit triggered, None if just moved to BE.
        """

        is_long = position.side == Side.LONG or position.side.value == "LONG"

        if is_long and cvd_divergence == "BEARISH_DIV":
            if not position.partial_taken:
                position.stop_loss = position.entry_price
                logger.info(
                    "TrailEngine: CVD kill signal — moved SL to break-even for %s",
                    position.id
                )
            else:
                logger.info("TrailEngine: CVD kill signal — scratching %s", position.id)
                position.advance_cushion_state(CushionState.CLOSED)
                return ExitSignal(position.id, "SCRATCH", current_price)

        if not is_long and cvd_divergence == "BULLISH_DIV":
            if not position.partial_taken:
                position.stop_loss = position.entry_price
                logger.info(
                    "TrailEngine: CVD kill signal — moved SL to break-even for %s",
                    position.id
                )
            else:
                logger.info("TrailEngine: CVD kill signal — scratching %s", position.id)
                position.advance_cushion_state(CushionState.CLOSED)
                return ExitSignal(position.id, "SCRATCH", current_price)

        return None

    # -----------------------------------------------------------------------
    # Manual Stop Loss Adjustment
    # -----------------------------------------------------------------------

    def adjust_stop_loss(
        self,
        position: "Position",
        new_sl: float,
    ) -> bool:
        """Adjust stop-loss on a Position.

        LONG: new_sl must be > current stop_loss (tighten up)
        SHORT: new_sl must be < current stop_loss (tighten down)

        Args:
            position: Position to update.
            new_sl: New stop loss price.

        Returns:
            True if adjusted, False if rejected.
        """
        if self._tick_size > 0:
            new_sl = round_to_tick(new_sl, self._tick_size)

        is_long = position.side == Side.LONG or position.side.value == "LONG"
        entry = float(position.entry_price)
        current_sl = float(position.stop_loss)

        # Breakeven protection
        if position.breakeven_set:
            if is_long and new_sl < entry:
                logger.info(
                    "TrailEngine: adjust_stop_loss REJECTED for %s — "
                    "breakeven set, new SL %.2f < entry %.2f",
                    position.id, new_sl, entry,
                )
                return False
            if not is_long and new_sl > entry:
                logger.info(
                    "TrailEngine: adjust_stop_loss REJECTED for %s — "
                    "breakeven set, new SL %.2f > entry %.2f",
                    position.id, new_sl, entry,
                )
                return False

        # Direction check
        if is_long:
            if new_sl <= current_sl:
                logger.info(
                    "TrailEngine: adjust_stop_loss REJECTED for %s — "
                    "new SL %.2f <= current %.2f (LONG can only tighten up)",
                    position.id, new_sl, current_sl,
                )
                return False
        else:
            if new_sl >= current_sl:
                logger.info(
                    "TrailEngine: adjust_stop_loss REJECTED for %s — "
                    "new SL %.2f >= current %.2f (SHORT can only tighten down)",
                    position.id, new_sl, current_sl,
                )
                return False

        position.stop_loss = Decimal(str(new_sl))
        logger.info(
            "TrailEngine: stop-loss adjusted for %s — %.2f -> %.2f",
            position.id, current_sl, new_sl,
        )
        return True
