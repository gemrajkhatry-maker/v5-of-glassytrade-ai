"""UpdateTick command handler."""
from typing import Optional
from app.application.commands.trading_commands import UpdateTick
from app.domain.shared.event.domain_events import TickReceived, AMTAnalyzed
from app.domain.shared.port.event_bus import IEventBus as EventBus


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
            
            # 3. Publish AMT analyzed event using new field structure
            amt_event = AMTAnalyzed(
                symbol=cmd.symbol,
                market_state=result.get("market_state", "BALANCED"),
                poc=result.get("poc", 0.0),
                value_area_high=result.get("vah", 0.0),
                value_area_low=result.get("val", 0.0),
                session_vwap=result.get("vwap", 0.0),
                absorptions_count=result.get("absorptions_count", 0),
                aggression=result.get("aggression", 0.0),
                setup=result.get("setup", ""),
                profile_shape=result.get("profile_shape", ""),
            )
            self._event_bus.publish(amt_event)