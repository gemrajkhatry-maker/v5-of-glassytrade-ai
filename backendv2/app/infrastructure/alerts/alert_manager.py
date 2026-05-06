"""Alert system for trading notifications."""
from dataclasses import dataclass, field
from typing import List, Callable, Optional
from enum import Enum
from datetime import datetime
import asyncio

from app.core.event_store import Event, EventStore
from app.core.feature_flags import FeatureFlags, Feature


class AlertType(Enum):
    SIGNAL = "SIGNAL"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_CLOSED = "POSITION_CLOSED"
    RISK_WARNING = "RISK_WARNING"
    PNL_ALERT = "PNL_ALERT"


@dataclass
class Alert:
    """Trading alert."""
    type: AlertType
    message: str
    symbol: Optional[str] = None
    data: dict = field(default_factory=dict)
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    
    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "message": self.message,
            "symbol": self.symbol,
            "data": self.data,
            "timestamp": self.timestamp
        }


class AlertManager:
    """Manages alert subscriptions and broadcasting."""
    
    def __init__(self, features: FeatureFlags):
        self._features = features
        self._subscribers: List[Callable[[Alert], None]] = []
        self._event_store = EventStore()
    
    def subscribe(self, callback: Callable[[Alert], None]) -> Callable[[], None]:
        """Subscribe to alerts. Returns unsubscribe function."""
        self._subscribers.append(callback)
        
        def unsubscribe():
            self._subscribers.remove(callback)
        
        return unsubscribe
    
    def broadcast(self, alert: Alert) -> None:
        """Broadcast alert to all subscribers."""
        if not self._features.is_enabled(Feature.AI_ANALYSIS):
            return
        
        # Store event
        event = Event(
            event_type=f"ALERT_{alert.type.value}",
            timestamp=alert.timestamp,
            data=alert.to_dict()
        )
        self._event_store.append(event)
        
        # Notify subscribers
        for callback in self._subscribers:
            try:
                callback(alert)
            except Exception:
                pass
    
    def signal_alert(self, symbol: str, direction: str, entry: float, sl: float, tp: float):
        """Create signal alert."""
        alert = Alert(
            type=AlertType.SIGNAL,
            message=f"New {direction} signal for {symbol}",
            symbol=symbol,
            data={
                "direction": direction,
                "entry": entry,
                "sl": sl,
                "tp": tp
            }
        )
        self.broadcast(alert)
    
    def position_alert(self, position_id: str, symbol: str, status: str, pnl: Optional[float] = None):
        """Create position alert."""
        alert_type = AlertType.POSITION_OPENED if status == "OPEN" else AlertType.POSITION_CLOSED
        alert = Alert(
            type=alert_type,
            message=f"Position {position_id} for {symbol} is now {status}",
            symbol=symbol,
            data={"position_id": position_id, "pnl": pnl}
        )
        self.broadcast(alert)
    
    def risk_alert(self, symbol: str, message: str, level: str = "WARNING"):
        """Create risk alert."""
        alert = Alert(
            type=AlertType.RISK_WARNING,
            message=message,
            symbol=symbol,
            data={"level": level}
        )
        self.broadcast(alert)