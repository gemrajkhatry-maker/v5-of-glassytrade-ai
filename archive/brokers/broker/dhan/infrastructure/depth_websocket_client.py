"""
Dhan Full Market Depth WebSocket Client.

Connects to the dedicated depth feed endpoints:
  - 20-level: wss://depth-api-feed.dhan.co/twentydepth
  - 200-level: wss://full-depth-api.dhan.co/twohundreddepth

Binary packet format (both endpoints):
  Header (12 bytes, Little Endian):
    [0-1]  uint16  Total payload message length
    [2]    uint8   Feed Response Code  (41=Bid, 51=Ask, 50=Disconnect)
    [3]    uint8   Exchange Segment
    [4-7]  int32   Security ID
    [8-11] uint32  Message Sequence (20-level) / Number of rows (200-level)

  Depth levels starting at offset 12, each 16 bytes:
    [+0..+7]   float64  Price
    [+8..+11]  uint32   Quantity
    [+12..+15] uint32   Number of Orders

  20-level total: 12 + 20×16 = 332 bytes per side packet
  200-level total: 12 + rows×16 bytes per side packet

Subscription (RequestCode 23):
  20-level:  {"RequestCode": 23, "InstrumentCount": N,
               "InstrumentList": [{"ExchangeSegment": "NSE_EQ", "SecurityId": "1333"}, ...]}
  200-level: {"RequestCode": 23, "ExchangeSegment": "NSE_EQ", "SecurityId": "1333"}
             (single instrument only)

Auth URL differs from regular feed — no `version=2` param:
  ?token=<TOKEN>&clientId=<CLIENT_ID>&authType=2
"""

import json
import struct
from datetime import datetime
from typing import Dict, List, Optional

from brokers.broker.dhan.domain.constants import (
    WS_URL_DEPTH_20,
    WS_URL_DEPTH_200,
    DEPTH_REQUEST_CODE,
    DEPTH_RC_BID,
    DEPTH_RC_ASK,
    DEPTH_RC_DISCONNECT,
    WS_PING_INTERVAL_SECONDS,
    WS_RECONNECT_DELAY_SECONDS,
    WS_MAX_RECONNECT_ATTEMPTS,
)
from brokers.broker.dhan.ports import WSMessage
from brokers.broker.dhan.infrastructure.websocket_client import DhanWebSocketClient, _SEGMENT_MAP
from brokers.broker.dhan.domain import (
    DhanWebSocketConnectionError,
    DhanWebSocketMessageError,
)
from brokers.broker.logging import get_logger

logger = get_logger("dhan.infrastructure.depth_ws")


class DepthWebSocketClient(DhanWebSocketClient):
    """
    WebSocket client for the Dhan Full Market Depth feed (20-level or 200-level).

    Subclasses DhanWebSocketClient and overrides:
      - _build_auth_url  — depth servers don't use the `version=2` query param
      - _send_subscription — uses RequestCode=23 and different format for 200-level
      - _decode_binary   — 12-byte header, float64 prices, rc=41/51 sides

    Args:
        depth_level: 20 or 200. Selects the server URL and subscription format.
        access_token: Dhan access token.
        client_id:    Dhan client ID.
    """

    def __init__(
        self,
        depth_level: int = 20,
        access_token: str = "",
        client_id: str = "",
        ping_interval: float = WS_PING_INTERVAL_SECONDS,
        reconnect_delay: float = WS_RECONNECT_DELAY_SECONDS,
        max_reconnect_attempts: int = WS_MAX_RECONNECT_ATTEMPTS,
    ) -> None:
        if depth_level not in (20, 200):
            raise ValueError(f"depth_level must be 20 or 200, got {depth_level}")

        ws_url = WS_URL_DEPTH_20 if depth_level == 20 else WS_URL_DEPTH_200
        super().__init__(
            ws_url=ws_url,
            access_token=access_token,
            client_id=client_id,
            ping_interval=ping_interval,
            reconnect_delay=reconnect_delay,
            max_reconnect_attempts=max_reconnect_attempts,
        )
        self._depth_level = depth_level
        logger.debug(
            f"DepthWebSocketClient initialised: depth={depth_level}-level url={ws_url}"
        )

    # ------------------------------------------------------------------
    # Auth URL — no `version=2` param on depth endpoints
    # ------------------------------------------------------------------

    def _build_auth_url(self) -> str:
        """Depth servers use a simpler auth URL (no version=2)."""
        return (
            f"{self._ws_url}"
            f"?token={self._access_token}"
            f"&clientId={self._client_id}"
            f"&authType=2"
        )

    # ------------------------------------------------------------------
    # Subscription — RequestCode=23, 200-level uses flat format
    # ------------------------------------------------------------------

    async def _send_subscription(
        self,
        security_ids: List[str],
        feed_type: int,  # ignored — depth always uses DEPTH_REQUEST_CODE=23
        exchange_segments: Optional[List[str]] = None,
    ) -> None:
        """
        Send subscription to the depth feed server.

        20-level: list of up to 50 instruments.
        200-level: single instrument only (flat format without InstrumentList).
        """
        if not self._ws:
            return

        if self._depth_level == 200:
            # Single instrument — flat top-level fields, no InstrumentList
            if len(security_ids) != 1:
                raise DhanWebSocketMessageError(
                    message="200-level depth supports only 1 instrument per connection",
                    details={"count": len(security_ids)},
                )
            seg = (exchange_segments[0] if exchange_segments else "NSE_EQ")
            message = {
                "RequestCode": DEPTH_REQUEST_CODE,
                "ExchangeSegment": seg,
                "SecurityId": security_ids[0],
            }
        else:
            # 20-level — InstrumentList format, up to 50 instruments
            if exchange_segments and len(exchange_segments) == len(security_ids):
                instrument_list = [
                    {"SecurityId": sid, "ExchangeSegment": seg}
                    for sid, seg in zip(security_ids, exchange_segments)
                ]
            else:
                instrument_list = [
                    {"SecurityId": sid, "ExchangeSegment": "NSE_EQ"}
                    for sid in security_ids
                ]
            message = {
                "RequestCode": DEPTH_REQUEST_CODE,
                "InstrumentCount": len(security_ids),
                "InstrumentList": instrument_list,
            }

        try:
            await self._ws.send(json.dumps(message))
            logger.debug(
                f"Depth subscription sent: depth={self._depth_level}-level "
                f"instruments={len(security_ids)}"
            )
        except Exception as e:
            raise DhanWebSocketMessageError(
                message=f"Failed to send depth subscription: {e}",
                details={"error": str(e)},
            )

    # ------------------------------------------------------------------
    # Frame splitter — depth WS concatenates multiple 332-byte sub-packets
    # ------------------------------------------------------------------

    _SUB_PKT_SIZE = 332   # 12-byte header + 20 × 16-byte depth level

    def _split_raw(self, raw) -> list:
        """
        Split a depth WS frame into individual sub-packets.

        Both 20-level and 200-level feeds concatenate bid + ask (and sometimes
        multiple update pairs) into a single WS frame:
          20-level:  fixed 332-byte chunks (12 header + 20×16)
          200-level: variable chunks — rows field at [8-11] tells us the size

        Each chunk is decoded independently by _decode_binary.
        """
        if not isinstance(raw, bytes):
            return [raw]

        if self._depth_level == 20:
            # Fixed-size sub-packets
            if len(raw) % self._SUB_PKT_SIZE == 0:
                n = len(raw) // self._SUB_PKT_SIZE
                return [raw[i * self._SUB_PKT_SIZE:(i + 1) * self._SUB_PKT_SIZE]
                        for i in range(n)]
            return [raw]

        # 200-level: parse sub-packet sizes from the rows field in each header
        chunks = []
        offset = 0
        while offset < len(raw):
            if offset + 12 > len(raw):
                break
            rows = struct.unpack_from('<I', raw, offset + 8)[0]
            sub_size = 12 + rows * 16
            if sub_size <= 12 or offset + sub_size > len(raw):
                # Malformed or last partial — take the rest as one chunk
                chunks.append(raw[offset:])
                break
            chunks.append(raw[offset:offset + sub_size])
            offset += sub_size
        return chunks if chunks else [raw]

    # ------------------------------------------------------------------
    # Binary decoder — 12-byte header, float64 levels, rc=41/51
    # ------------------------------------------------------------------

    def _decode_binary(self, data: bytes) -> Optional[WSMessage]:
        """
        Decode a binary packet from the depth feed.

        Header (12 bytes):
          [0-1]  uint16  total payload length
          [2]    uint8   response code (41=Bid, 51=Ask, 50=Disconnect)
          [3]    uint8   exchange segment
          [4-7]  int32   security ID
          [8-11] uint32  message sequence (20-level) / number of rows (200-level)

        Depth levels (each 16 bytes from offset 12):
          float64 price + uint32 quantity + uint32 orders
        """
        if len(data) < 12:
            return None

        try:
            # Header
            rc       = struct.unpack_from('<B', data, 2)[0]
            exch     = struct.unpack_from('<B', data, 3)[0]
            sec_id   = struct.unpack_from('<I', data, 4)[0]   # uint32 (consistent with parent)
            seq_rows = struct.unpack_from('<I', data, 8)[0]   # uint32

            # Map WS binary security_id → REST string (fallback: str(sec_id))
            rest_id = self._ws_sid_to_rest.get(sec_id, str(sec_id))
            # Map raw exchange byte to human-readable segment name (consistent with parent decoder)
            segment_name = _SEGMENT_MAP.get(exch, str(exch))

            base = {
                "security_id": rest_id,
                "ws_security_id": str(sec_id),
                "exchange_segment": segment_name,
            }

            if rc in (DEPTH_RC_BID, DEPTH_RC_ASK):
                side = "bid" if rc == DEPTH_RC_BID else "ask"

                # 200-level: [8-11] = actual number of rows in this packet
                # 20-level:  always 20 rows
                num_levels = seq_rows if self._depth_level == 200 else 20

                levels = []
                o = 12
                for _ in range(num_levels):
                    if o + 16 > len(data):
                        break
                    price  = struct.unpack_from('<d', data, o)[0]; o += 8   # float64
                    qty    = struct.unpack_from('<I', data, o)[0]; o += 4   # uint32
                    orders = struct.unpack_from('<I', data, o)[0]; o += 4   # uint32
                    levels.append({
                        "price": round(price, 2),
                        "qty": qty,
                        "orders": orders,
                    })

                logger.debug(
                    f"Depth packet: sid={rest_id} side={side} "
                    f"levels={len(levels)} depth={self._depth_level}"
                )
                return WSMessage(
                    type="depth",
                    data={**base, "side": side, "levels": levels},
                    timestamp=datetime.now(),
                )

            elif rc == DEPTH_RC_DISCONNECT:
                reason = struct.unpack_from('<H', data, 12)[0] if len(data) >= 14 else 0
                logger.warning(f"Depth server disconnect: reason_code={reason}")
                return WSMessage(
                    type="disconnected",
                    data={**base, "reason_code": reason},
                    timestamp=datetime.now(),
                )

            else:
                logger.debug(f"Unknown depth packet rc={rc} len={len(data)}")
                return WSMessage(
                    type="binary_unknown",
                    data={**base, "response_code": rc, "raw": data[:32].hex()},
                    timestamp=datetime.now(),
                )

        except struct.error as e:
            logger.warning(f"Depth binary decode error len={len(data)}: {e}")
            rc_safe = data[2] if len(data) > 2 else -1
            return WSMessage(
                type="binary_error",
                data={"response_code": rc_safe, "error": str(e), "raw": data[:32].hex()},
                timestamp=datetime.now(),
            )
