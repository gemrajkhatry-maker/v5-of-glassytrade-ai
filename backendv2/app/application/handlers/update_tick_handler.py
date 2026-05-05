"""UpdateTick command handler."""
from typing import Optional
from app.application.commands.trading_commands import UpdateTick
from app.domain.shared.event.domain_events import TickReceived, AMTAnalyzed
from app.infrastructure.messaging.event_bus import EventBus


class IAMTService:
    """Interface for AMT analysis service."""
    def analyze(self, symbol: str, price: float) -> dict:
        """Analyze market data for a symbol."""
        ...


class UpdateTickHandler:
    """
    Handles UpdateTick commands.
    
    Processing flow:
    1. Validate tick data
    2. Publish TickReceived event
    3. Trigger AMT analysis
    4. Publish AMTAnalyzed event
    """
    
    def __init__(
        self,
        event_bus: EventBus,
        amt_service: Optional[IAMTService] = None
    ):
        self._event_bus = event_bus
        self._amt_service = amt_service
    
    def handle(self, cmd: UpdateTick) -> None:
        """
        Process a tick update command.
        
        Args:
            cmd: The UpdateTick command containing tick data
        """
        # 1. Publish tick received event
        tick_event = TickReceived(
            symbol=cmd.symbol,
            price=cmd.price,
            volume=cmd.volume,
            timestamp_ms=cmd.timestamp
        )
        self._event_bus.publish(tick_event)
        
        # 2. Trigger AMT analysis if service available
        if self._amt_service:
            result = self._amt_service.analyze(symbol=cmd.symbol, price=cmd.price)
            
            # 3. Publish AMT analyzed event
            amt_event = AMTAnalyzed(
                symbol=cmd.symbol,
                phase1_result=result.get("phase1", {}),
                phase2_result=result.get("phase2", {}),
                phase3_result=result.get("phase3", {}),
                phase4_result=result.get("phase4", {}),
                absorptions_count=result.get("absorptions_count", 0),
                vwap=result.get("vwap", 0.0)
            )
            self._event_bus.publish(amt_event)