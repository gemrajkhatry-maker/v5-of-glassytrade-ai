"""
Trade constructor — entry/SL/TP construction from structural levels.

Entry at level, SL beyond aggressive print + buffer, target at POC.
"""

from dataclasses import dataclass
from typing import Optional

from src.config.engine_config import CFG


@dataclass
class EntrySignal:
    """Entry signal with all trade parameters."""

    direction: str  # "LONG", "SHORT", "FLAT"
    entry_price: float
    stop_loss: float
    target: float
    risk_reward: float
    cushion_ticks: int
    cushion_quality: str  # "EXCELLENT", "ACCEPTABLE", "INVALID"
    invalidation: float


class TradeConstructor:
    """
    Construct trade parameters from structural levels.

    Uses static methods for pure function behavior.
    """

    @staticmethod
    def build(
        direction: str,
        entry_level: float,
        aggressive_print: float,
        poc: float,
        atr: float,
        tick_size: float,
    ) -> EntrySignal:
        """
        Build entry signal from structural levels.

        Args:
            direction: "LONG" or "SHORT"
            entry_level: Entry price (LVN, VAH, VAL)
            aggressive_print: Aggressive print price for SL
            poc: Point of Control for target
            atr: Current ATR for buffer calculation
            tick_size: Instrument tick size

        Returns:
            EntrySignal with all parameters.
        """
        # Calculate buffer (2 ticks beyond aggressive print)
        buffer = tick_size * 2

        # Calculate stop loss
        if direction == "LONG":
            stop_loss = aggressive_print - buffer
            target = poc if poc > entry_level else entry_level + atr * 2
        else:  # SHORT
            stop_loss = aggressive_print + buffer
            target = poc if poc < entry_level else entry_level - atr * 2

        # Calculate risk and reward
        risk = abs(entry_level - stop_loss)
        reward = abs(target - entry_level)

        # Calculate R:R
        risk_reward = reward / risk if risk > 0 else 0.0

        # Calculate cushion
        cushion_ticks = int(risk / tick_size) if tick_size > 0 else 0

        # Determine cushion quality
        if cushion_ticks <= CFG.cushion_excellent_ticks:
            cushion_quality = "EXCELLENT"
        elif cushion_ticks <= CFG.cushion_acceptable_ticks:
            cushion_quality = "ACCEPTABLE"
        elif cushion_ticks <= CFG.max_cushion_ticks:
            cushion_quality = "ACCEPTABLE"
        else:
            cushion_quality = "INVALID"

        # Calculate invalidation level
        if direction == "LONG":
            invalidation = stop_loss
        else:
            invalidation = stop_loss

        return EntrySignal(
            direction=direction,
            entry_price=entry_level,
            stop_loss=stop_loss,
            target=target,
            risk_reward=risk_reward,
            cushion_ticks=cushion_ticks,
            cushion_quality=cushion_quality,
            invalidation=invalidation,
        )

    @staticmethod
    def validate_cushion(entry: float, sl: float, tick_size: float) -> str:
        """
        Validate cushion quality.

        Returns: "EXCELLENT", "ACCEPTABLE", or "INVALID"
        """
        if tick_size <= 0:
            return "INVALID"

        cushion_ticks = int(abs(entry - sl) / tick_size)

        if cushion_ticks <= CFG.cushion_excellent_ticks:
            return "EXCELLENT"
        elif cushion_ticks <= CFG.max_cushion_ticks:
            return "ACCEPTABLE"
        else:
            return "INVALID"

    @staticmethod
    def validate_rr(entry: float, sl: float, tp: float) -> bool:
        """
        Validate risk-reward ratio.

        Returns True if R:R >= 1.5
        """
        risk = abs(entry - sl)
        reward = abs(tp - entry)

        if risk <= 0:
            return False

        rr = reward / risk
        return rr >= CFG.min_rr_ratio
