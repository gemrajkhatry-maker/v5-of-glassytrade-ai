"""Alerting system with WebSocket notifications."""

import json
from datetime import datetime, timezone
from typing import Literal
from app.core.correlation import get_correlation_id
from app.core.logging import log_info

# Type aliases for alerts
AlertSeverity = Literal["info", "warning", "error", "critical"]
AlertType = Literal["circuit_breaker", "drawdown", "loss_streak", "signal_quality", "system"]


# Global alert subscribers (WebSocket connections)
_alert_subscribers: list[callable] = []


def subscribe_alerts(callback: callable) -> None:
    """Register a WebSocket callback for alerts."""
    _alert_subscribers.append(callback)


def unsubscribe_alerts(callback: callable) -> None:
    """Remove a WebSocket callback."""
    if callback in _alert_subscribers:
        _alert_subscribers.remove(callback)


def send_alert(
    alert_type: AlertType,
    severity: AlertSeverity,
    message: str,
    symbol: str | None = None,
    data: dict | None = None,
) -> dict:
    """Send an alert to all subscribers."""
    alert = {
        "id": get_correlation_id(),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "type": alert_type,
        "severity": severity,
        "message": message,
        "symbol": symbol,
        "data": data or {},
    }
    
    # Log the alert
    log_info("alerts", message, symbol=symbol, severity=severity, alert_type=alert_type)
    
    # Send to WebSocket subscribers
    for callback in _alert_subscribers:
        try:
            callback(alert)
        except Exception:
            pass  # Don't let subscriber errors break the system
    
    return alert


# Alert helpers
def alert_circuit_breaker(state: str, symbol: str, failure_count: int):
    severity = "critical" if state == "open" else "warning"
    return send_alert(
        "circuit_breaker",
        severity,
        f"Circuit breaker {state} for {symbol} ({failure_count} failures)",
        symbol,
        {"state": state, "failure_count": failure_count},
    )


def alert_drawdown(symbol: str, pct: float, threshold: float = 0.02):
    severity = "critical" if pct > 0.03 else "warning"
    return send_alert(
        "drawdown",
        severity,
        f"Drawdown {pct:.1%} exceeds {threshold:.0%} threshold",
        symbol,
        {"drawdown_pct": pct, "threshold": threshold},
    )


def alert_loss_streak(symbol: str, streak: int, threshold: int = 3):
    return send_alert(
        "loss_streak",
        "critical" if streak >= threshold else "warning",
        f"Loss streak: {streak} consecutive losses",
        symbol,
        {"streak": streak, "threshold": threshold},
    )