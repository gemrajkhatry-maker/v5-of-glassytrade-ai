"""Alert Manager — Pre-alert system for Drive 1 returns per Fabio AMT spec.

Fires when price returns within N ticks of a key level.
Clears per-level alerts when drive 3+ detected (level exhausted).
Pushes alerts via WebSocket to frontend.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class PriceAlert:
    """An active price alert."""
    alert_id: str
    symbol: str
    price: float
    direction: str  # "LONG" | "SHORT"
    level_type: str  # "VAH", "VAL", "LVN", "POC", "NPOC"
    zone_upper: float
    zone_lower: float
    fired: bool = False
    created_at: str = ""
    fired_at: str | None = None


@dataclass
class AlertEvent:
    """A fired alert event."""
    type: str = "PRICE_ALERT"
    alert_id: str = ""
    symbol: str = ""
    level_type: str = ""
    level_price: float = 0.0
    current_price: float = 0.0
    direction: str = ""
    message: str = ""


class AlertManager:
    """Manages price alerts for Drive 1 returns.

    Usage:
        manager = AlertManager(ws_publisher=ws_send_fn, proximity_ticks=3)
        alert_id = manager.set_price_alert("CRUDEOIL", 6100.0, "LONG", "VAH", tick_size=0.1)
        fired = manager.check_alerts("CRUDEOIL", current_price=6100.2)
        manager.clear_alerts_for_level("CRUDEOIL", 6100.0)
    """

    def __init__(
        self,
        ws_publisher: Callable | None = None,
        proximity_ticks: int = 3,
    ):
        self._ws = ws_publisher
        self._proximity_ticks = proximity_ticks
        self._active_alerts: dict[str, PriceAlert] = {}
        self._fired_events: list[AlertEvent] = []

    def set_price_alert(
        self,
        symbol: str,
        price: float,
        direction: str,
        level_type: str,
        tick_size: float,
    ) -> str:
        """Set alert to fire when price returns within N ticks of level.

        Args:
            symbol: Trading symbol.
            price: The level price to watch.
            direction: "LONG" or "SHORT" — intended trade direction.
            level_type: Type of level (VAH, VAL, LVN, POC, NPOC).
            tick_size: Instrument tick size for zone calculation.

        Returns:
            Alert ID string.
        """
        alert_id = f"{symbol}_{price:.1f}_{level_type}"
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

        logger.info(
            "Alert set: %s %s at %.1f (zone=%.1f-%.1f)",
            symbol, level_type, price,
            price - zone, price + zone,
        )
        return alert_id

    def check_alerts(self, symbol: str, current_price: float) -> list[AlertEvent]:
        """Check if any alerts should fire.

        Args:
            symbol: Trading symbol.
            current_price: Current market price.

        Returns:
            List of fired AlertEvent objects.
        """
        fired = []
        for aid, alert in self._active_alerts.items():
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
                    message=f"Price approaching {alert.level_type} at {alert.price:.1f} (current: {current_price:.1f})",
                )
                fired.append(event)
                self._fired_events.append(event)
                logger.info("ALERT FIRED: %s", event.message)

                # Push via WebSocket if publisher available
                if self._ws:
                    try:
                        self._ws({
                            "type": "PRICE_ALERT",
                            "alertId": aid,
                            "symbol": symbol,
                            "levelType": alert.level_type,
                            "levelPrice": alert.price,
                            "currentPrice": current_price,
                            "direction": alert.direction,
                            "message": event.message,
                        })
                    except Exception:
                        logger.debug("WS alert push failed", exc_info=True)

        return fired

    def clear_alerts_for_level(self, symbol: str, price: float) -> int:
        """Clear all alerts for a specific level (e.g., when drive 3+ detected).

        Args:
            symbol: Trading symbol.
            price: The level price to clear alerts for.

        Returns:
            Number of alerts cleared.
        """
        to_remove = [
            aid for aid, alert in self._active_alerts.items()
            if alert.symbol == symbol and abs(alert.price - price) < 0.5
        ]
        for aid in to_remove:
            del self._active_alerts[aid]

        if to_remove:
            logger.info("Cleared %d alerts for %s level %.1f (D3+ exhaustion)", len(to_remove), symbol, price)
        return len(to_remove)

    def clear_all_alerts(self, symbol: str | None = None) -> int:
        """Clear all alerts, optionally filtered by symbol.

        Args:
            symbol: If provided, only clear alerts for this symbol.

        Returns:
            Number of alerts cleared.
        """
        if symbol:
            to_remove = [aid for aid, alert in self._active_alerts.items() if alert.symbol == symbol]
        else:
            to_remove = list(self._active_alerts.keys())

        for aid in to_remove:
            del self._active_alerts[aid]
        return len(to_remove)

    def get_active_alerts(self, symbol: str | None = None) -> list[dict]:
        """Get all active (unfired) alerts.

        Args:
            symbol: If provided, filter by symbol.

        Returns:
            List of alert dicts.
        """
        alerts = []
        for alert in self._active_alerts.values():
            if alert.fired:
                continue
            if symbol and alert.symbol != symbol:
                continue
            alerts.append({
                "alertId": alert.alert_id,
                "symbol": alert.symbol,
                "price": alert.price,
                "direction": alert.direction,
                "levelType": alert.level_type,
                "zoneUpper": alert.zone_upper,
                "zoneLower": alert.zone_lower,
                "createdAt": alert.created_at,
            })
        return alerts

    def get_fired_events(self, limit: int = 50) -> list[dict]:
        """Get recent fired alert events.

        Args:
            limit: Max number of events to return.

        Returns:
            List of event dicts.
        """
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
