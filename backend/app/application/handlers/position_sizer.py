"""Position Sizer — Calculates position sizes based on risk and confidence.

Responsibilities:
- Position size calculation
- Risk-based sizing
- Confidence-based adjustments
- Kelly criterion integration
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult

logger = logging.getLogger(__name__)


class PositionSizer:
    """Calculates position sizes based on risk and confidence.
    
    This module encapsulates all position sizing logic, providing a single
    source of truth for position sizing across the codebase.
    """

    def calculate_size(
        self,
        entry_price: float,
        stop_loss: float,
        equity: float,
        confidence: str = "Medium",
        max_risk_pct: float = 0.02,
        point_value: float = 10.0,
    ) -> tuple[float, float]:
        """Calculate position size based on risk and confidence.
        
        Args:
            entry_price: Entry price for the trade
            stop_loss: Stop loss price
            equity: Account equity
            confidence: Confidence level (High/Medium/Low)
            max_risk_pct: Maximum risk per trade as percentage of equity
            point_value: Point value for the instrument
        
        Returns:
            Tuple of (size, risk_amount)
        """
        from app.domain.constants import MAX_RISK_PER_TRADE
        
        # Use provided max_risk_pct or default from constants
        risk_pct = max_risk_pct if max_risk_pct > 0 else MAX_RISK_PER_TRADE
        
        # Calculate risk amount
        risk_amount = equity * risk_pct
        
        # Calculate risk per unit
        risk_per_unit = abs(entry_price - stop_loss)
        
        if risk_per_unit <= 0:
            logger.warning("Invalid risk per unit: %.2f", risk_per_unit)
            return 0.0, 0.0
        
        # Calculate base size
        base_size = risk_amount / risk_per_unit
        
        # Apply confidence adjustment
        confidence_multiplier = self._get_confidence_multiplier(confidence)
        
        # Calculate final size
        final_size = base_size * confidence_multiplier
        
        # Apply point value if provided
        if point_value > 0:
            final_size = final_size / point_value
        
        logger.info(
            "Position sizing: entry=%.2f, SL=%.2f, equity=%.2f, confidence=%s, "
            "risk_pct=%.4f, base_size=%.2f, final_size=%.2f",
            entry_price, stop_loss, equity, confidence,
            risk_pct, base_size, final_size,
        )
        
        return final_size, risk_amount

    def _get_confidence_multiplier(self, confidence: str) -> float:
        """Get position size multiplier based on confidence level.
        
        Args:
            confidence: Confidence level (High/Medium/Low)
        
        Returns:
            Multiplier for position sizing
        """
        multipliers = {
            "High": 1.0,
            "Medium": 0.75,
            "Low": 0.5,
        }
        return multipliers.get(confidence, 0.5)

    def calculate_kelly_size(
        self,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        equity: float,
        max_kelly_pct: float = 0.25,
    ) -> float:
        """Calculate position size using Kelly criterion.
        
        Args:
            win_rate: Historical win rate (0.0 to 1.0)
            avg_win: Average winning trade amount
            avg_loss: Average losing trade amount (positive number)
            equity: Account equity
            max_kelly_pct: Maximum Kelly percentage to use
        
        Returns:
            Position size based on Kelly criterion
        """
        if win_rate <= 0 or win_rate >= 1:
            logger.warning("Invalid win rate: %.2f", win_rate)
            return 0.0
        
        if avg_loss <= 0:
            logger.warning("Invalid average loss: %.2f", avg_loss)
            return 0.0
        
        # Calculate Kelly percentage
        # Kelly % = (W * R - (1 - W)) / R
        # where W = win rate, R = avg_win / avg_loss
        r = avg_win / avg_loss if avg_loss > 0 else 0
        kelly_pct = (win_rate * r - (1 - win_rate)) / r if r > 0 else 0
        
        # Cap at maximum Kelly percentage
        kelly_pct = min(kelly_pct, max_kelly_pct)
        
        # Calculate position size
        position_size = equity * kelly_pct
        
        logger.info(
            "Kelly sizing: win_rate=%.2f, avg_win=%.2f, avg_loss=%.2f, "
            "R=%.2f, kelly_pct=%.4f, size=%.2f",
            win_rate, avg_win, avg_loss, r, kelly_pct, position_size,
        )
        
        return position_size

    def adjust_for_volatility(
        self,
        base_size: float,
        atr: float,
        current_volatility: float,
        target_volatility: float = 0.02,
    ) -> float:
        """Adjust position size based on volatility.
        
        Args:
            base_size: Base position size
            atr: Average True Range
            current_volatility: Current volatility measure
            target_volatility: Target volatility level
        
        Returns:
            Adjusted position size
        """
        if current_volatility <= 0 or target_volatility <= 0:
            return base_size
        
        # Calculate volatility ratio
        volatility_ratio = target_volatility / current_volatility
        
        # Adjust size inversely to volatility
        adjusted_size = base_size * volatility_ratio
        
        # Cap adjustment to reasonable bounds
        adjusted_size = max(adjusted_size, base_size * 0.25)  # Min 25% of base
        adjusted_size = min(adjusted_size, base_size * 2.0)   # Max 200% of base
        
        logger.info(
            "Volatility adjustment: base=%.2f, atr=%.2f, current_vol=%.4f, "
            "target_vol=%.4f, ratio=%.2f, adjusted=%.2f",
            base_size, atr, current_volatility, target_volatility,
            volatility_ratio, adjusted_size,
        )
        
        return adjusted_size

    def validate_size(
        self,
        size: float,
        entry_price: float,
        stop_loss: float,
        equity: float,
        max_position_pct: float = 0.10,
    ) -> tuple[bool, str]:
        """Validate position size against constraints.
        
        Args:
            size: Position size to validate
            entry_price: Entry price
            stop_loss: Stop loss price
            equity: Account equity
            max_position_pct: Maximum position size as percentage of equity
        
        Returns:
            Tuple of (valid: bool, reason: str)
        """
        if size <= 0:
            return False, "Position size must be positive"
        
        # Calculate position value
        position_value = size * entry_price
        
        # Check maximum position size
        max_position_value = equity * max_position_pct
        if position_value > max_position_value:
            return False, f"Position value ({position_value:.2f}) exceeds maximum ({max_position_value:.2f})"
        
        # Calculate risk
        risk_per_unit = abs(entry_price - stop_loss)
        total_risk = size * risk_per_unit
        
        # Check maximum risk
        max_risk = equity * 0.02  # 2% max risk
        if total_risk > max_risk:
            return False, f"Total risk ({total_risk:.2f}) exceeds maximum ({max_risk:.2f})"
        
        return True, "Position size is valid"