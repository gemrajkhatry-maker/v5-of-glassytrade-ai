"""Pre-alert manager for price-proximity trade zones."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class PriceAlert:
    alert_id: str
    symbol: str
    price: float
    direction: str
    level_type: str
    zone_upper: float
    zone_lower: float
    fired: bool = False
    created_at: str = ""
    fired_at: str | None = None


@dataclass
class AlertEvent:
    type: str = "PRICE_ALERT"
    alert_id: str = ""
    symbol: str = ""
    level_type: str = ""
    level_price: float = 0.0
    current_price: float = 0.0
    direction: str = ""
    message: str = ""


class AlertManager:
    def __init__(self, ws_publisher: Any | None = None, proximity_ticks: int = 3):
        self._ws = ws_publisher
        self._proximity_ticks = proximity_ticks
        self._active_alerts: dict[str, PriceAlert] = {}
        self._fired_events: list[AlertEvent] = []

    def set_price_alert(self, symbol: str, price: float, direction: str, level_type: str, tick_size: float) -> str:
        alert_id = f"{symbol}_{price:.1f}_{level_type}_{len(self._active_alerts)+1}"
        zone = tick_size * self._proximity_ticks
        self._active_alerts[alert_id] = PriceAlert(
            alert_id=alert_id,
            symbol=symbol,
            price=price,
            direction=direction,
            level_type=level_type,
            zone_upper=price + zone,
            zone_lower=price - zone,
            created_at=datetime.now().isoformat(),
        )
        return alert_id

    def check_alerts(self, symbol: str, current_price: float) -> list[AlertEvent]:
        fired: list[AlertEvent] = []
        for aid, alert in list(self._active_alerts.items()):
            if alert.symbol != symbol or alert.fired:
                continue
            if alert.zone_lower <= current_price <= alert.zone_upper:
                alert.fired = True
                alert.fired_at = datetime.now().isoformat()
                event = AlertEvent(
                    alert_id=aid,
                    symbol=symbol,
                    level_type=alert.level_type,
                    level_price=alert.price,
                    current_price=current_price,
                    direction=alert.direction,
                    message=f"Price approached {alert.level_type} at {alert.price:.2f}.",
                )
                self._fired_events.append(event)
                fired.append(event)
                if self._ws:
                    try:
                        self._ws({
                            "type": event.type,
                            "alertId": event.alert_id,
                            "symbol": symbol,
                            "levelType": event.level_type,
                            "levelPrice": event.level_price,
                            "currentPrice": current_price,
                            "direction": event.direction,
                            "message": event.message,
                        })
                    except Exception:
                        pass
        return fired

    def clear_alerts_for_level(self, symbol: str, price: float) -> int:
        remove = [aid for aid, alert in self._active_alerts.items() if alert.symbol == symbol and abs(alert.price - price) < 0.5]
        for aid in remove:
            del self._active_alerts[aid]
        return len(remove)

    def clear_all_alerts(self, symbol: str | None = None) -> int:
        if symbol is None:
            count = len(self._active_alerts)
            self._active_alerts.clear()
            return count
        remove = [aid for aid, alert in self._active_alerts.items() if alert.symbol == symbol]
        for aid in remove:
            del self._active_alerts[aid]
        return len(remove)

    def get_active_alerts(self, symbol: str | None = None) -> list[dict[str, Any]]:
        out = []
        for alert in self._active_alerts.values():
            if alert.fired:
                continue
            if symbol and alert.symbol != symbol:
                continue
            out.append(
                {
                    "alertId": alert.alert_id,
                    "symbol": alert.symbol,
                    "price": alert.price,
                    "direction": alert.direction,
                    "levelType": alert.level_type,
                    "zoneUpper": alert.zone_upper,
                    "zoneLower": alert.zone_lower,
                    "createdAt": alert.created_at,
                }
            )
        return out

    def get_fired_events(self, limit: int = 50) -> list[dict[str, Any]]:
        return [
            {
                "type": e.type,
                "alertId": e.alert_id,
                "symbol": e.symbol,
                "levelType": e.level_type,
                "levelPrice": e.level_price,
                "currentPrice": e.current_price,
                "direction": e.direction,
                "message": e.message,
            }
            for e in self._fired_events[-limit:]
        ]
