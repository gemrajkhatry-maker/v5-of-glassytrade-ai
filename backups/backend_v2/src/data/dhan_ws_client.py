"""
Dhan WebSocket client — tick stream with exponential backoff reconnect.

Handles WebSocket connection, subscription, and tick parsing.
"""

import asyncio
from typing import Callable, Dict, List, Optional

import orjson
import structlog
import websockets

logger = structlog.get_logger()


class DhanWSClient:
    """
    DhanHQ WebSocket client for real-time tick data.

    Features:
    - Auto-reconnect with exponential backoff
    - Per-symbol tick callbacks
    - Connection state management
    """

    def __init__(
        self,
        access_token: str,
        client_id: str,
        on_tick: Callable[[dict], None],
    ):
        self._access_token = access_token
        self._client_id = client_id
        self._on_tick = on_tick
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._reconnect_delay = 2
        self._max_reconnect_delay = 30
        self._is_connected = False
        self._subscriptions: List[Dict] = []
        self._running = False

    async def connect(self) -> None:
        """Connect to DhanHQ WebSocket."""
        self._running = True

        while self._running:
            try:
                uri = "wss://api.dhan.co/v2/marketfeed"
                headers = {
                    "access-token": self._access_token,
                    "client-id": self._client_id,
                }

                async with websockets.connect(uri, additional_headers=headers) as ws:
                    self._ws = ws
                    self._is_connected = True
                    self._reconnect_delay = 2  # Reset on success

                    logger.info("dhan_ws_connected")

                    # Re-subscribe to all symbols
                    for sub in self._subscriptions:
                        await self._send_subscription(sub)

                    # Listen for messages
                    async for message in ws:
                        await self._handle_message(message)

            except websockets.exceptions.ConnectionClosed:
                logger.warning("dhan_ws_connection_closed")
            except Exception as e:
                logger.error("dhan_ws_error", error=str(e))
            finally:
                self._is_connected = False
                self._ws = None

            # Exponential backoff
            if self._running:
                logger.info("dhan_ws_reconnecting", delay=self._reconnect_delay)
                await asyncio.sleep(self._reconnect_delay)
                self._reconnect_delay = min(
                    self._reconnect_delay * 2, self._max_reconnect_delay
                )

    async def subscribe(self, instruments: List[Dict]) -> None:
        """
        Subscribe to instruments.

        Args:
            instruments: List of instrument dicts with ExchangeSegment and SecurityId
        """
        subscription = {
            "RequestCode": 15,
            "InstrumentCount": len(instruments),
            "InstrumentList": instruments,
        }
        self._subscriptions.append(subscription)

        if self._is_connected and self._ws:
            await self._send_subscription(subscription)

    async def _send_subscription(self, subscription: Dict) -> None:
        """Send subscription request."""
        if self._ws:
            await self._ws.send(orjson.dumps(subscription).decode())

    async def _handle_message(self, message: str) -> None:
        """Handle incoming WebSocket message."""
        try:
            data = orjson.loads(message)

            # Parse tick data
            if data.get("Type") == "Ticker":
                tick = self._parse_tick(data)
                if tick:
                    self._on_tick(tick)

        except Exception as e:
            logger.error("dhan_ws_parse_error", error=str(e))

    def _parse_tick(self, data: dict) -> Optional[dict]:
        """Parse DhanHQ tick format to our format."""
        try:
            return {
                "type": "ticker",
                "symbol": data.get("Symbol", ""),
                "LTP": float(data.get("LTP", 0)),
                "buy_qty": int(data.get("BuyQuantity", 0)),
                "sell_qty": int(data.get("SellQuantity", 0)),
                "trade_size": int(data.get("LastTradedQuantity", 0)),
                "timestamp": data.get("Timestamp", ""),
                "exchange": data.get("ExchangeSegment", ""),
            }
        except (ValueError, TypeError):
            return None

    async def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        self._running = False
        if self._ws:
            await self._ws.close()
        self._is_connected = False
        logger.info("dhan_ws_disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._is_connected