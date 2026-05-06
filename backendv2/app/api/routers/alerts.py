"""Alert websocket channel and test endpoint."""
from __future__ import annotations

import asyncio
from typing import Callable

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.core.feature_flags import Feature, FeatureFlags
from app.infrastructure.alerts.alert_manager import Alert, AlertManager

router = APIRouter(prefix="/alerts", tags=["alerts"])

# TODO: Inject via DI container instead of global
_feature_flags = FeatureFlags()
_alert_manager = AlertManager(_feature_flags)
_alert_manager._features.enable(Feature.AI_ANALYSIS)


@router.websocket("/ws")
async def alerts_websocket(websocket: WebSocket):
    """WebSocket endpoint for real-time alerts."""
    await websocket.accept()

    loop = asyncio.get_running_loop()
    send_queue: asyncio.Queue[dict] = asyncio.Queue()

    async def _send_loop() -> None:
        while True:
            payload = await send_queue.get()
            try:
                await websocket.send_json(payload)
            except Exception:
                break

    sender_task = asyncio.create_task(_send_loop())

    def _sync_on_alert(alert: Alert) -> None:
        try:
            loop.call_soon_threadsafe(lambda: send_queue.put_nowait(alert.to_dict()))
        except Exception:
            pass

    unsubscribe: Callable[[], None] = _alert_manager.subscribe(_sync_on_alert)

    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe()
        sender_task.cancel()


@router.post("/test")
async def test_alert(message: str = "Test alert"):
    """Send a test alert through the shared alert manager."""
    _alert_manager.signal_alert(
        "BTCUSDT",
        "LONG",
        0.0,
        0.0,
        0.0,
    )
    return {"status": "ok", "message": message}

