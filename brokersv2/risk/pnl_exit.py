"""P&L Exit Manager - Profit targets, stop losses, and trailing stops."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ExitType(Enum):
    """Types of exit events."""
    PROFIT_TARGET = "profit_target"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    POSITION_STOP_LOSS = "position_stop_loss"
    POSITION_PROFIT_TARGET = "position_profit_target"
    TRAILING_STOP = "trailing_stop"


@dataclass(frozen=True)
class ExitEvent:
    """Exit event with details."""
    timestamp: datetime
    exit_type: ExitType
    pnl: float
    symbol: Optional[str] = None


@dataclass
class PnLExitRule:
    """Rule definition for exit conditions."""
    rule_type: ExitType
    threshold: float
    enabled: bool = True


@dataclass
class PnLExitConfig:
    """P&L Exit configuration."""
    daily_profit_target: float = 5000.0
    daily_loss_limit: float = 3000.0
    position_stop_loss: float = 1000.0


@dataclass
class PositionInfo:
    """Position information."""
    symbol: str
    quantity: int
    entry_price: float
    current_price: float
    use_trailing_stop: bool = False
    trailing_stop: Optional[float] = None
    highest_price: Optional[float] = None


class PnLExitManager:
    """
    Manages P&L-based exits for positions and daily trading.
    
    Features:
    - Daily profit/loss limits
    - Position-specific stop losses
    - Trailing stop management
    - Exit event generation
    """
    
    def __init__(self, config: Optional[PnLExitConfig] = None):
        """
        Initialize P&L exit manager.
        
        Args:
            config: PnLExitConfig instance (uses defaults if None)
        """
        self._config = config or PnLExitConfig()
        self._daily_pnl: float = 0.0
        self._positions: Dict[str, PositionInfo] = {}
    
    @property
    def daily_pnl(self) -> float:
        """Current daily P&L."""
        return self._daily_pnl
    
    @property
    def positions(self) -> Dict[str, PositionInfo]:
        """Open positions."""
        return self._positions.copy()
    
    def update_daily_pnl(self, pnl: float) -> None:
        """Update daily P&L."""
        self._daily_pnl = pnl
    
    def open_position(
        self,
        symbol: str,
        quantity: int,
        price: float,
        use_trailing_stop: bool = False,
    ) -> None:
        """
        Open a new position.
        
        Args:
            symbol: Instrument symbol
            quantity: Position quantity
            price: Entry price
            use_trailing_stop: Whether to use trailing stop
        """
        initial_stop = price - self._config.position_stop_loss / quantity if quantity > 0 else price
        
        self._positions[symbol] = PositionInfo(
            symbol=symbol,
            quantity=quantity,
            entry_price=price,
            current_price=price,
            use_trailing_stop=use_trailing_stop,
            trailing_stop=initial_stop if use_trailing_stop else None,
            highest_price=price if use_trailing_stop else None,
        )
    
    def close_position(self, symbol: str, exit_price: float) -> None:
        """
        Close a position.
        
        Args:
            symbol: Instrument symbol
            exit_price: Exit price
        """
        if symbol in self._positions:
            pos = self._positions[symbol]
            pnl = pos.quantity * (exit_price - pos.entry_price)
            self._daily_pnl += pnl
            del self._positions[symbol]
            logger.info(f"Closed {symbol} at {exit_price}, PnL: {pnl}")
    
    def update_position_price(self, symbol: str, current_price: float) -> None:
        """
        Update position current price.
        
        Args:
            symbol: Instrument symbol
            current_price: Current market price
        """
        if symbol not in self._positions:
            return
        
        pos = self._positions[symbol]
        pos.current_price = current_price
        
        # Update trailing stop if enabled
        if pos.use_trailing_stop:
            if pos.highest_price is None or current_price > pos.highest_price:
                pos.highest_price = current_price
                # Move trailing stop up (never down)
                if pos.trailing_stop is not None:
                    new_stop = current_price - self._config.position_stop_loss / pos.quantity
                    if new_stop > pos.trailing_stop:
                        pos.trailing_stop = new_stop
    
    def check_exits(self) -> List[ExitEvent]:
        """
        Check all exit conditions and return list of exit events.
        
        Returns:
            List of ExitEvent objects for triggered exits
        """
        exits: List[ExitEvent] = []
        now = datetime.now(timezone.utc)
        
        # Check daily profit target
        if self._daily_pnl >= self._config.daily_profit_target:
            exits.append(ExitEvent(
                timestamp=now,
                exit_type=ExitType.PROFIT_TARGET,
                pnl=self._daily_pnl,
            ))
        
        # Check daily loss limit
        if self._daily_pnl <= -self._config.daily_loss_limit:
            exits.append(ExitEvent(
                timestamp=now,
                exit_type=ExitType.DAILY_LOSS_LIMIT,
                pnl=self._daily_pnl,
            ))
        
        # Check position-level exits
        for symbol, pos in self._positions.items():
            position_pnl = pos.quantity * (pos.current_price - pos.entry_price)
            
            # Check position stop loss
            if position_pnl <= -self._config.position_stop_loss:
                exits.append(ExitEvent(
                    timestamp=now,
                    exit_type=ExitType.POSITION_STOP_LOSS,
                    pnl=position_pnl,
                    symbol=symbol,
                ))
            
            # Check trailing stop
            if pos.use_trailing_stop and pos.trailing_stop is not None:
                if pos.current_price <= pos.trailing_stop:
                    exits.append(ExitEvent(
                        timestamp=now,
                        exit_type=ExitType.TRAILING_STOP,
                        pnl=position_pnl,
                        symbol=symbol,
                    ))
        
        return exits
    
    def get_trailing_stop(self, symbol: str) -> Optional[float]:
        """
        Get trailing stop for a position.
        
        Args:
            symbol: Instrument symbol
            
        Returns:
            Trailing stop price or None
        """
        if symbol not in self._positions:
            return None
        
        pos = self._positions[symbol]
        return pos.trailing_stop
    
    def get_position_pnl(self, symbol: str) -> float:
        """
        Get current P&L for a position.
        
        Args:
            symbol: Instrument symbol
            
        Returns:
            Position P&L
        """
        if symbol not in self._positions:
            return 0.0
        
        pos = self._positions[symbol]
        return pos.quantity * (pos.current_price - pos.entry_price)
    
    def reset_daily(self) -> None:
        """Reset daily P&L."""
        self._daily_pnl = 0.0
        logger.info("Daily P&L reset")
