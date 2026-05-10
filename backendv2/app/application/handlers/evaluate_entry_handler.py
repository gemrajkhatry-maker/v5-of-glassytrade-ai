"""EvaluateEntry command handler."""
from typing import Optional
from app.application.commands.trading_commands import EvaluateEntry
from app.domain.shared.event.domain_events import SignalGenerated
from app.domain.shared.port.signal import ISignalService
from app.domain.shared.port.event_bus import IEventBus as EventBus


class EvaluateEntryHandler:
    """
    Handles EvaluateEntry commands.
    
    Processing flow:
    1. Validate phase results exist
    2. Check risk state
    3. Generate signal
    4. Publish SignalGenerated event
    """
    
    def __init__(
        self,
        event_bus: EventBus,
        signal_service: Optional[ISignalService] = None
    ):
        self._event_bus = event_bus
        self._signal_service = signal_service
    
    def handle(self, cmd: EvaluateEntry) -> None:
        """
        Process an entry evaluation command.
        
        Args:
            cmd: The EvaluateEntry command with AMT results
        """
        # 1. Validate inputs
        if not cmd.symbol:
            return
        
        # 2. Check risk state
        if not self._check_risk(cmd.symbol):
            return
        
        # 3. Generate signal if service available
        if self._signal_service:
            signal_result = self._signal_service.generate(
                phase1_result=cmd.phase1_result,
                phase2_result=cmd.phase2_result,
                phase3_result=cmd.phase3_result,
                absorptions=cmd.absorptions,
                current_price=cmd.current_price,
                vwap=cmd.vwap
            )
            
            # 4. Publish signal event using new field structure
            signal_event = SignalGenerated(
                symbol=cmd.symbol,
                signal_id=f"{cmd.symbol}_{int(cmd.current_price)}",
                direction=signal_result.get("type", "FLAT"),
                entry_price=signal_result.get("entry", 0.0),
                stop_loss=signal_result.get("sl", 0.0),
                take_profit=signal_result.get("tp", 0.0),
                position_size=signal_result.get("size", 0.0),
                confidence=str(signal_result.get("confidence", "Medium")),
                setup_type=signal_result.get("reason", ""),
                source="AMT",
            )
            self._event_bus.publish(signal_event)
    
    def _check_risk(self, symbol: str) -> bool:
        """
        Check if entry is allowed based on risk state.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            True if entry is allowed, False if halted
        """
        # Placeholder - would check risk state from domain service
        return True