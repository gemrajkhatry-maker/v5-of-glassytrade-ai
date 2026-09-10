"""Alerts router for WebSocket notifications."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.core.alerts import subscribe_alerts, unsubscribe_alerts, send_alert

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.websocket("/ws")
async def alerts_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time alerts."""
    await websocket.accept()
    
    # Register callback
    async def on_alert(alert: dict):
        try:
            await websocket.send_json(alert)
        except Exception:  # silent-except - dead websocket subscriber must not break alert fan-out
            pass
    
    subscribe_alerts(on_alert)
    
    try:
        # Keep connection alive
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        unsubscribe_alerts(on_alert)


@router.post("/test")
async def test_alert(message: str = "Test alert"):
    """Send a test alert."""
    return send_alert("system", "info", message, data={"test": True})