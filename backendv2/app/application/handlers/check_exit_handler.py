"""CheckExit command handler."""
from typing import Optional
from app.application.commands.trading_commands import CheckExit
from app.domain.trading.model.entities import Position
from app.domain.trading.model.enums import Side, PositionStatus
from app.domain.shared.event.domain_events import PositionClosed
from app.domain.shared.port.event_bus import IEventBus as EventBus


class IPositionRepository:
    """Interface for position persistence."""
    def get_by_id(self, position_id: str) -> Optional[Position]:
        """Get position by ID."""
        ...


class CheckExitHandler:
    """
    Handles CheckExit commands.
    
    Processing flow:
    1. Fetch position from repository
    2. Check if SL or TP hit
    3. Calculate PNL
    4. Publish PositionClosed event if exit triggered
    """
    
    def __init__(
        self,
        event_bus: EventBus,
        position_repo: Optional[IPositionRepository] = None
    ):
        self._event_bus = event_bus
        self._position_repo = position_repo
    
    def handle(self, cmd: CheckExit) -> None:
        """
        Process an exit check command.
        
        Args:
            cmd: The CheckExit command with position_id and current price
        """
        # 1. Fetch position
        if not self._position_repo:
            return
            
        position = self._position_repo.get_by_id(cmd.position_id)
        if not position or position.status != PositionStatus.OPEN:
            return
        
        # 2. Check exit conditions
        should_exit = False
        exit_reason = ""
        
        if position.is_long:
            if cmd.current_price <= float(position.stop_loss):
                should_exit = True
                exit_reason = "STOP_LOSS"
            elif cmd.current_price >= float(position.take_profit):
                should_exit = True
                exit_reason = "TAKE_PROFIT"
        else:  # SHORT
            if cmd.current_price >= float(position.stop_loss):
                should_exit = True
                exit_reason = "STOP_LOSS"
            elif cmd.current_price <= float(position.take_profit):
                should_exit = True
                exit_reason = "TAKE_PROFIT"
        
        # 3. Publish exit event if triggered
        if should_exit:
            pnl = self._calculate_pnl(position, cmd.current_price)
            
            exit_event = PositionClosed(
                trade_id=position.id,
                symbol=position.symbol,
                close_reason=exit_reason,
                realized_pnl=pnl,
                exit_price=cmd.current_price,
            )
            self._event_bus.publish(exit_event)
    
    def _calculate_pnl(self, position: Position, exit_price: float) -> float:
        """
        Calculate PNL for a closed position.
        
        Args:
            position: The position being closed
            exit_price: The exit price
            
        Returns:
            PNL in quote currency
        """
        if position.is_long:
            return (exit_price - float(position.entry_price)) * float(position.size)
        else:  # SHORT
            return (float(position.entry_price) - exit_price) * float(position.size)