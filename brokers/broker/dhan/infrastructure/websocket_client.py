"""
Dhan WebSocket Client - Implementation of IWebSocketClient protocol.

Connects to the Dhan market feed WebSocket and decodes the binary packet protocol.

Binary packet format (Little Endian):
  Header (8 bytes):
    [0]   ResponseCode    uint8
    [1]   ExchangeSegment uint8
    [2-3] Sub-exchange / reserved uint16
    [4-7] SecurityId      uint32

  Packet types:
    2  — Ticker      (16 bytes): LTP float32, LastTradeTime uint32
    4  — Quote       (50 bytes): LTP, LTQ, LTT, ATP, Vol, TotalSell, TotalBuy, OHLC
    5  — OI          (12 bytes): OI uint32
    6  — PrevClose   (16 bytes): PrevClose float32, PrevOI uint32
    8  — Full/Depth  (162 bytes): Quote fields + OI + HighOI + LowOI + 5-level depth
    50 — Disconnect  (10 bytes): ReasonCode uint16

Authentication:
  URL query params (v2): ?version=2&token=<TOKEN>&clientId=<CLIENT_ID>&authType=2

Subscription message:
  {"RequestCode": 15, "InstrumentCount": N,
   "InstrumentList": [{"ExchangeSegment": "NSE_EQ", "SecurityId": "1333"}]}
"""

import asyncio
import json
import struct
from datetime import datetime
from typing import Optional, List, AsyncIterator, Set, Dict, Any

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.protocol import State as WSState

from brokers.broker.logging import get_logger
from brokers.broker.dhan.ports import (
    IWebSocketClient,
    WSMessage,
)
from brokers.broker.dhan.domain import (
    DhanWebSocketConnectionError,
    DhanWebSocketDisconnectedError,
    DhanWebSocketMessageError,
    DhanAuthError,
    WS_URL,
    WS_PING_INTERVAL_SECONDS,
    WS_RECONNECT_DELAY_SECONDS,
    WS_MAX_RECONNECT_ATTEMPTS,
    FEED_TYPE_FULL,
)


logger = get_logger("dhan.websocket")


# ---------------------------------------------------------------------------
# Exchange segment code → string mapping (Dhan binary protocol)
# ---------------------------------------------------------------------------

_SEGMENT_MAP: Dict[int, str] = {
    1:  "NSE_EQ",
    2:  "NSE_FNO",
    3:  "NSE_CURRENCY",
    4:  "BSE_EQ",
    5:  "BSE_FNO",
    6:  "BSE_CURRENCY",
    7:  "MCX_COMM",
    13: "MCX_FNO",
    16: "IDX_I",
}

# Response codes
_RC_TICKER      = 2
_RC_QUOTE       = 4
_RC_OI          = 5
_RC_PREV_CLOSE  = 6
_RC_FULL        = 8
_RC_DISCONNECT  = 50


# ---------------------------------------------------------------------------
# Dhan WebSocket Client
# ---------------------------------------------------------------------------

class DhanWebSocketClient(IWebSocketClient):
    """
    WebSocket client for the Dhan market feed API (v2 binary protocol).

    Builds the authenticated URL at connect time:
      wss://api-feed.dhan.co?version=2&token=TOKEN&clientId=CLIENT_ID&authType=2

    Decodes incoming binary packets into typed WSMessage objects.
    """

    def __init__(
        self,
        ws_url: str = WS_URL,
        access_token: str = "",
        client_id: str = "",
        ping_interval: float = WS_PING_INTERVAL_SECONDS,
        reconnect_delay: float = WS_RECONNECT_DELAY_SECONDS,
        max_reconnect_attempts: int = WS_MAX_RECONNECT_ATTEMPTS,
        auth_provider: Optional[Any] = None,
    ) -> None:
        self._ws_url = ws_url
        self._access_token = access_token
        self._client_id = client_id
        self._ping_interval = ping_interval
        self._reconnect_delay = reconnect_delay
        self._max_reconnect_attempts = max_reconnect_attempts
        self._auth_provider = auth_provider

        self._ws: Optional[ClientConnection] = None
        self._connected: bool = False
        self._reconnect_count: int = 0

        self._message_queue: Optional[asyncio.Queue] = None  # lazily initialized in connect()
        self._receive_task: Optional[asyncio.Task] = None
        self._ping_task: Optional[asyncio.Task] = None

        self._subscriptions: Set[str] = set()
        self._current_feed_type: int = FEED_TYPE_FULL
        # Maps security_id string → exchange segment string (e.g. "NSE_FNO", "MCX_COMM").
        # Persisted so reconnect replay can re-send the correct segment for each instrument.
        self._sid_to_segment: Dict[str, str] = {}

        # Maps WS-internal SecurityId (uint32) → REST API security_id string.
        # Populated on first tick per instrument: the server echoes back its own
        # internal ID in the binary packet header, which differs from the REST ID.
        self._ws_sid_to_rest: Dict[int, str] = {}

        logger.debug(f"DhanWebSocketClient initialised: base_url={ws_url}")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None and self._ws.state is WSState.OPEN

    @property
    def subscriptions(self) -> Set[str]:
        return self._subscriptions.copy()

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    def _build_auth_url(self) -> str:
        """Build authenticated WebSocket URL per Dhan v2 docs."""
        return (
            f"{self._ws_url}"
            f"?version=2"
            f"&token={self._access_token}"
            f"&clientId={self._client_id}"
            f"&authType=2"
        )

    async def connect(self) -> None:
        """
        Establish WebSocket connection using the v2 auth URL format.

        Raises:
            DhanWebSocketConnectionError: If connection fails.
            DhanAuthError: If authentication is rejected (HTTP 401).
        """
        if self.is_connected:
            return

        # Lazily create the queue inside a running event loop (Python 3.10+)
        if self._message_queue is None:
            self._message_queue = asyncio.Queue(maxsize=10000)

        auth_url = self._build_auth_url()
        logger.info(f"Connecting to Dhan market feed WS (clientId={self._client_id})")

        try:
            self._ws = await websockets.connect(
                auth_url,
                ping_interval=self._ping_interval,
                ping_timeout=self._ping_interval * 2,
                close_timeout=5.0,
            )
            self._connected = True
            self._reconnect_count = 0
            logger.info("WebSocket connected successfully")

            self._receive_task = asyncio.create_task(self._receive_loop())
            self._ping_task = asyncio.create_task(self._ping_loop())

            if self._subscriptions:
                sids = list(self._subscriptions)
                # Reconstruct per-instrument segments from persisted map (empty = NSE_EQ default)
                segs = [self._sid_to_segment.get(sid, "NSE_EQ") for sid in sids]
                await self._send_subscription(sids, self._current_feed_type, segs)

        except websockets.exceptions.InvalidStatus as e:
            if e.response.status_code == 401:
                raise DhanAuthError(
                    message="WebSocket authentication failed",
                    details={"status_code": 401},
                )
            raise DhanWebSocketConnectionError(
                message=f"WebSocket connection rejected: HTTP {e.response.status_code}",
                details={"status_code": e.response.status_code},
            )
        except websockets.exceptions.WebSocketException as e:
            raise DhanWebSocketConnectionError(
                message=f"WebSocket connection failed: {e}",
                details={"error": str(e)},
            )
        except Exception as e:
            raise DhanWebSocketConnectionError(
                message=f"Unexpected error during WS connect: {e}",
                details={"error": str(e)},
            )

    async def disconnect(self) -> None:
        """Close WebSocket connection and cancel background tasks."""
        if not self._connected:
            return

        logger.info("Disconnecting WebSocket…")
        for task in (self._receive_task, self._ping_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._receive_task = None
        self._ping_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception as e:
                logger.debug("ws.close() error during disconnect (ignored): %s", e)
            self._ws = None

        self._connected = False
        logger.info("WebSocket disconnected")

    # ------------------------------------------------------------------
    # Subscription
    # ------------------------------------------------------------------

    async def subscribe(
        self,
        security_ids: List[str],
        feed_type: int = FEED_TYPE_FULL,
        exchange_segments: Optional[List[str]] = None,
    ) -> None:
        """
        Subscribe to market data.

        Args:
            security_ids: Dhan REST API security IDs.
            feed_type: RequestCode for desired packet type:
                15 = Ticker  (LTP only)
                17 = Quote   (LTP + OHLC + Volume)
                21 = Full    (Quote + 5-level depth + OI)  ← default
                20 = FullDepth (20-level depth)
            exchange_segments: Per-instrument exchange segment strings (e.g. "NSE_FNO", "MCX_COMM").
                Must match len(security_ids). Required for non-equity segments.
        """
        if not self.is_connected:
            raise DhanWebSocketDisconnectedError(message="Cannot subscribe: not connected")

        self._subscriptions.update(security_ids)
        self._current_feed_type = feed_type
        # Pre-populate WS SID→REST mapping so _decode_binary can resolve
        # the uint32 security_id from binary packets back to REST string IDs.
        for sid_str in security_ids:
            try:
                self._ws_sid_to_rest[int(sid_str)] = sid_str
            except (ValueError, TypeError):
                pass
        # Persist segment mapping so reconnect replay uses the correct segment per instrument
        if exchange_segments and len(exchange_segments) == len(security_ids):
            for sid, seg in zip(security_ids, exchange_segments):
                self._sid_to_segment[sid] = seg
        await self._send_subscription(security_ids, feed_type, exchange_segments)
        logger.info(f"Subscribed to {len(security_ids)} instruments feed_type={feed_type}")

    async def _send_subscription(
        self,
        security_ids: List[str],
        feed_type: int,
        exchange_segments: Optional[List[str]] = None,
    ) -> None:
        """Send subscription JSON to the server."""
        if not self._ws:
            return

        if exchange_segments and len(exchange_segments) == len(security_ids):
            instrument_list = [
                {"SecurityId": sid, "ExchangeSegment": seg}
                for sid, seg in zip(security_ids, exchange_segments)
            ]
        else:
            # Default to NSE_EQ when no segment is specified
            instrument_list = [
                {"SecurityId": sid, "ExchangeSegment": "NSE_EQ"}
                for sid in security_ids
            ]

        message = {
            "RequestCode": feed_type,   # 15=Ticker 17=Quote 21=Full 20=FullDepth
            "InstrumentCount": len(security_ids),
            "InstrumentList": instrument_list,
        }
        try:
            await self._ws.send(json.dumps(message))
            logger.debug(f"Subscription sent for {len(security_ids)} instruments")
        except Exception as e:
            raise DhanWebSocketMessageError(
                message=f"Failed to send subscription: {e}",
                details={"error": str(e)},
            )

    def register_security_mapping(self, ws_internal_id: int, rest_id: str) -> None:
        """
        Register a mapping from WS-internal SecurityId to REST API security_id.

        The Dhan binary feed returns its own internal SecurityId in packet headers,
        which differs from the SecurityId used in REST calls. Call this after
        receiving the first tick per instrument (or pre-populate from a lookup).

        Args:
            ws_internal_id: The uint32 SecurityId in binary packet header.
            rest_id: The REST API security_id string used to subscribe.
        """
        self._ws_sid_to_rest[ws_internal_id] = rest_id
        logger.debug(f"Registered WS ID mapping: {ws_internal_id} → {rest_id}")

    async def unsubscribe(self, security_ids: List[str]) -> None:
        """Unsubscribe from market data for specified instruments."""
        if not self.is_connected:
            raise DhanWebSocketDisconnectedError(message="Cannot unsubscribe: not connected")
        for sid in security_ids:
            self._subscriptions.discard(sid)
        if not self._ws:
            return
        message = {
            "RequestCode": 16,
            "InstrumentCount": len(security_ids),
            "InstrumentList": [{"SecurityId": sid} for sid in security_ids],
        }
        try:
            await self._ws.send(json.dumps(message))
        except Exception as e:
            logger.warning(f"Failed to send unsubscription: {e}")

    # ------------------------------------------------------------------
    # Message iterator
    # ------------------------------------------------------------------

    async def messages(self) -> AsyncIterator[WSMessage]:
        """Async iterator yielding decoded WSMessage objects.

        Survives reconnect cycles: keeps polling the queue even while
        is_connected is False (reconnect in progress).  Only exits when
        a terminal 'disconnected' message is received (max attempts
        exhausted) or the task is cancelled.
        """
        while True:
            try:
                msg = await asyncio.wait_for(self._message_queue.get(), timeout=1.0)
                # Terminal: max reconnect attempts exhausted
                if msg.type == "disconnected" and "Max reconnection" in str(msg.data.get("reason", "")):
                    yield msg
                    break
                yield msg
            except asyncio.TimeoutError:
                # If disconnected and no reconnect in progress, exit
                if not self.is_connected and self._reconnect_count >= self._max_reconnect_attempts:
                    break
            except asyncio.CancelledError:
                break

    # ------------------------------------------------------------------
    # Background tasks
    # ------------------------------------------------------------------

    def _split_raw(self, raw: "str | bytes") -> list:
        """
        Split a raw WS frame into individual decodable chunks.

        The default implementation treats the whole frame as one chunk.
        Subclasses (e.g. DepthWebSocketClient) can override this to split
        frames that contain multiple concatenated binary sub-packets.
        """
        return [raw]

    async def _receive_loop(self) -> None:
        while self.is_connected and self._ws:
            try:
                raw = await self._ws.recv()
                for chunk in self._split_raw(raw):
                    msg = self._parse_message(chunk)
                    if msg:
                        try:
                            self._message_queue.put_nowait(msg)
                        except asyncio.QueueFull:
                            # Drop oldest message to make room (backpressure)
                            try:
                                self._message_queue.get_nowait()
                            except asyncio.QueueEmpty:
                                pass
                            self._message_queue.put_nowait(msg)
            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"WebSocket closed: {e}")
                self._connected = False
                await self._attempt_reconnect()
                break
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception("Error receiving message: %s", e)
                await self._message_queue.put(
                    WSMessage(type="error", data={"error": str(e)}, timestamp=datetime.now())
                )

    async def _ping_loop(self) -> None:
        while self.is_connected and self._ws:
            try:
                await asyncio.sleep(self._ping_interval)
                if self._ws and self._ws.state is WSState.OPEN:
                    await self._ws.ping()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Ping error: {e}")

    async def _attempt_reconnect(self) -> None:
        while self._reconnect_count < self._max_reconnect_attempts:
            self._reconnect_count += 1
            delay = min(self._reconnect_delay * (2 ** (self._reconnect_count - 1)), 60.0)
            logger.info(f"Reconnecting {self._reconnect_count}/{self._max_reconnect_attempts} in {delay}s")
            await asyncio.sleep(delay)

            # Refresh token before reconnect if auth_provider is available
            if self._auth_provider:
                try:
                    token = await self._auth_provider.ensure_valid_token()
                    if token and token != self._access_token:
                        self._access_token = token
                        logger.info("Token refreshed before WS reconnect")
                except Exception as e:
                    logger.warning("Token refresh before reconnect failed: %s", e)

            try:
                await self.connect()
                return
            except Exception:
                logger.exception("Reconnect failed")
        logger.error("Max reconnection attempts reached")
        await self._message_queue.put(
            WSMessage(type="disconnected",
                      data={"reason": "Max reconnection attempts reached",
                            "attempts": self._reconnect_count},
                      timestamp=datetime.now())
        )

    # ------------------------------------------------------------------
    # Message parsing — binary protocol decoder
    # ------------------------------------------------------------------

    def _parse_message(self, raw: "str | bytes") -> Optional[WSMessage]:
        """Route to binary or JSON parser depending on message type."""
        if isinstance(raw, bytes):
            return self._decode_binary(raw)
        # JSON text frames (status/ack messages from server)
        try:
            data = json.loads(raw)
            return WSMessage(type=self._classify_json(data), data=data, timestamp=datetime.now())
        except json.JSONDecodeError:
            return WSMessage(type="raw", data={"raw": raw}, timestamp=datetime.now())

    def _decode_binary(self, data: bytes) -> Optional[WSMessage]:
        """
        Decode a Dhan binary market feed packet.

        Header layout (8 bytes, Little Endian):
          [0]   ResponseCode      uint8
          [1]   ExchangeSegment   uint8
          [2-3] Sub-exchange/reserved uint16
          [4-7] SecurityId        uint32

        Packet types and sizes:
          2  Ticker     16 bytes  — LTP(f32), LastTradeTime(u32)
          4  Quote      50 bytes  — LTP, LTQ, LTT, ATP, Vol, TotSell, TotBuy, OHLC
          5  OI         12 bytes  — OI(u32)
          6  PrevClose  16 bytes  — PrevClose(f32), PrevOI(u32)
          8  Full      162 bytes  — Quote + OI/HighOI/LowOI + 5×depth
          50 Disconnect 10 bytes  — ReasonCode(u16)
        """
        if len(data) < 8:
            logger.debug(f"Binary packet too short ({len(data)} bytes), skipping")
            return None

        rc        = data[0]
        seg_code  = data[1]
        ws_sec_id = struct.unpack_from('<I', data, 4)[0]   # offset 4, NOT 2
        segment   = _SEGMENT_MAP.get(seg_code, str(seg_code))

        # Resolve WS internal ID → REST API security_id (set by subscribe caller)
        rest_id = self._ws_sid_to_rest.get(ws_sec_id, str(ws_sec_id))

        base: Dict[str, Any] = {
            "security_id": rest_id,
            "ws_security_id": str(ws_sec_id),
            "exchange_segment": segment,
        }

        try:
            if rc == _RC_TICKER and len(data) >= 16:
                ltp = struct.unpack_from('<f', data, 8)[0]
                ltt = struct.unpack_from('<I', data, 12)[0]
                return WSMessage(
                    type="tick",
                    data={**base, "ltp": round(ltp, 2), "last_trade_time": ltt},
                    timestamp=datetime.now(),
                )

            elif rc == _RC_PREV_CLOSE and len(data) >= 16:
                prev_close = struct.unpack_from('<f', data, 8)[0]
                # Dhan encodes prev_oi as float32, not uint32
                prev_oi    = int(struct.unpack_from('<f', data, 12)[0])
                return WSMessage(
                    type="prev_close",
                    data={**base, "prev_close": round(prev_close, 2), "prev_oi": prev_oi},
                    timestamp=datetime.now(),
                )

            elif rc == _RC_OI and len(data) >= 12:
                oi = struct.unpack_from('<I', data, 8)[0]
                return WSMessage(
                    type="oi",
                    data={**base, "oi": oi},
                    timestamp=datetime.now(),
                )

            elif rc == _RC_QUOTE and len(data) >= 50:
                o = 8
                ltp      = struct.unpack_from('<f', data, o)[0]; o += 4
                ltq      = struct.unpack_from('<H', data, o)[0]; o += 2
                ltt      = struct.unpack_from('<I', data, o)[0]; o += 4
                atp      = struct.unpack_from('<f', data, o)[0]; o += 4
                vol      = struct.unpack_from('<I', data, o)[0]; o += 4
                tot_sell = struct.unpack_from('<I', data, o)[0]; o += 4
                tot_buy  = struct.unpack_from('<I', data, o)[0]; o += 4
                open_    = struct.unpack_from('<f', data, o)[0]; o += 4
                close    = struct.unpack_from('<f', data, o)[0]; o += 4
                high     = struct.unpack_from('<f', data, o)[0]; o += 4
                low      = struct.unpack_from('<f', data, o)[0]
                return WSMessage(
                    type="quote",
                    data={
                        **base,
                        "ltp": round(ltp, 2), "ltq": ltq, "last_trade_time": ltt,
                        "atp": round(atp, 2), "volume": vol,
                        "total_sell_qty": tot_sell, "total_buy_qty": tot_buy,
                        "open": round(open_, 2), "close": round(close, 2),
                        "high": round(high, 2), "low": round(low, 2),
                    },
                    timestamp=datetime.now(),
                )

            elif rc == _RC_FULL and len(data) >= 162:
                o = 8
                ltp      = struct.unpack_from('<f', data, o)[0]; o += 4
                ltq      = struct.unpack_from('<H', data, o)[0]; o += 2
                ltt      = struct.unpack_from('<I', data, o)[0]; o += 4
                atp      = struct.unpack_from('<f', data, o)[0]; o += 4
                vol      = struct.unpack_from('<I', data, o)[0]; o += 4
                tot_sell = struct.unpack_from('<I', data, o)[0]; o += 4
                tot_buy  = struct.unpack_from('<I', data, o)[0]; o += 4
                open_    = struct.unpack_from('<f', data, o)[0]; o += 4
                close    = struct.unpack_from('<f', data, o)[0]; o += 4
                high     = struct.unpack_from('<f', data, o)[0]; o += 4
                low      = struct.unpack_from('<f', data, o)[0]; o += 4
                oi       = struct.unpack_from('<I', data, o)[0]; o += 4
                high_oi  = struct.unpack_from('<I', data, o)[0]; o += 4
                low_oi   = struct.unpack_from('<I', data, o)[0]; o += 4
                # 5-level depth: each level = bid_qty(4) + ask_qty(4) + bid_orders(2) + ask_orders(2) + bid_price(4) + ask_price(4) = 20 bytes
                depth_bids, depth_asks = [], []
                for _ in range(5):
                    bq  = struct.unpack_from('<I', data, o)[0]; o += 4
                    aq  = struct.unpack_from('<I', data, o)[0]; o += 4
                    bo  = struct.unpack_from('<H', data, o)[0]; o += 2
                    ao  = struct.unpack_from('<H', data, o)[0]; o += 2
                    bp  = struct.unpack_from('<f', data, o)[0]; o += 4
                    ap  = struct.unpack_from('<f', data, o)[0]; o += 4
                    depth_bids.append({"price": round(bp, 2), "qty": bq, "orders": bo})
                    depth_asks.append({"price": round(ap, 2), "qty": aq, "orders": ao})
                return WSMessage(
                    type="full",
                    data={
                        **base,
                        "ltp": round(ltp, 2), "ltq": ltq, "last_trade_time": ltt,
                        "atp": round(atp, 2), "volume": vol,
                        "total_sell_qty": tot_sell, "total_buy_qty": tot_buy,
                        "open": round(open_, 2), "close": round(close, 2),
                        "high": round(high, 2), "low": round(low, 2),
                        "oi": oi, "high_oi": high_oi, "low_oi": low_oi,
                        "depth_bids": depth_bids, "depth_asks": depth_asks,
                    },
                    timestamp=datetime.now(),
                )

            elif rc == _RC_DISCONNECT:
                reason = struct.unpack_from('<H', data, 8)[0] if len(data) >= 10 else 0
                logger.warning(f"Server sent disconnect packet reason_code={reason}")
                return WSMessage(
                    type="disconnected",
                    data={**base, "reason_code": reason},
                    timestamp=datetime.now(),
                )

            else:
                logger.debug(f"Unknown binary packet rc={rc} len={len(data)}")
                return WSMessage(
                    type="binary_unknown",
                    data={**base, "response_code": rc, "raw": data[:32].hex()},
                    timestamp=datetime.now(),
                )

        except struct.error as e:
            logger.warning(f"Binary decode error rc={rc} len={len(data)}: {e}")
            return WSMessage(
                type="binary_error",
                data={**base, "response_code": rc, "error": str(e), "raw": data[:32].hex()},
                timestamp=datetime.now(),
            )

    def _classify_json(self, data: dict) -> str:
        """Classify a JSON text frame by content."""
        if "Open" in data or "High" in data:
            return "quote"
        if "LTP" in data or "last_price" in data:
            return "tick"
        if "orderId" in data or "order_id" in data:
            return "order"
        if "error" in data or "Error" in data:
            return "error"
        if "status" in data or "Status" in data:
            return "status"
        return "unknown"

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> "DhanWebSocketClient":
        await self.connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.disconnect()

    def __repr__(self) -> str:
        return (
            f"DhanWebSocketClient(connected={self._connected}, "
            f"subscriptions={len(self._subscriptions)})"
        )
