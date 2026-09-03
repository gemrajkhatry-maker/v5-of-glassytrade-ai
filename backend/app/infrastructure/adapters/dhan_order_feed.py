"""Dhan Live Order Update feed — async fill notifications over WebSocket.

Connects to Dhan's order-update socket (``wss://api-order-update.dhan.co``),
authenticates with the JSON ``LoginReq`` handshake (MsgCode 42), and dispatches
every ``order_alert`` to a callback plus per-order waiters.

Design constraints (C4 async fill feed):

- **Pure optimization.** When the feed is unhealthy or disabled, order-status
  waiting falls back to the proven REST polling path in the adapter, so live
  behaviour never regresses.
- **No lost updates.** Incoming updates are buffered per order id (bounded)
  so an update that arrives between ``place_order`` and waiter registration
  is still visible via :meth:`snapshot`.
- **Fully contained.** The socket runs in a daemon thread with its own event
  loop; every failure is logged and retried with backoff and never propagates
  to trading code.

Wire protocol (DhanHQ v2 docs):

- Auth (first JSON frame)::

    {"LoginReq": {"MsgCode": 42, "ClientId": "<id>", "Token": "<token>"},
     "UserType": "SELF"}

- Updates arrive as JSON ``{"Type": "order_alert", "Data": {...}}`` where
  ``Data`` carries ``orderNo`` and ``status`` (TRANSIT / PENDING / PART_TRADED
  / TRADED / CANCELLED / REJECTED / EXPIRED). Field casing has been observed
  in BOTH lowerCamelCase and PascalCase across Dhan docs/SDK, so lookups
  always try both.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from collections import OrderedDict
from typing import Any, Callable

import websockets

from brokers.broker.dhan.application.order_converter import DHAN_ORDER_STATUS_MAP
from brokers.broker.types import OrderStatus

logger = logging.getLogger(__name__)

_DEFAULT_ORDER_WS_URL = "wss://api-order-update.dhan.co"
_MAX_TRACKED_ORDERS = 200
_AUTH_MSG_CODE = 42


def _first(payload: dict, *keys: str, default: Any = None) -> Any:
    """First non-empty value among candidate keys (handles casing drift)."""
    for key in keys:
        value = payload.get(key)
        if value is not None and value != "":
            return value
    return default


from shared.money import to_float as _to_float


def normalize_order_update(payload: Any) -> dict | None:
    """Normalize a raw Dhan order-alert payload into a stable snapshot dict.

    Returns ``None`` for anything that is not an order update (other message
    types, heartbeats, malformed frames). Status is mapped to the broker-
    agnostic :class:`OrderStatus` via the same table the REST path uses, so
    terminal detection is consistent across both feeds.
    """
    if not isinstance(payload, dict):
        return None
    if payload.get("Type") not in (None, "order_alert"):
        return None
    data = payload.get("Data")
    if not isinstance(data, dict):
        return None
    order_id = _first(data, "OrderNo", "orderNo", "OrderId", "orderId", "order_id")
    if order_id is None:
        return None

    raw_status = str(_first(data, "status", "Status") or "").strip().upper()
    status = DHAN_ORDER_STATUS_MAP.get(raw_status)
    if status is None:
        # Unknown status: treat as non-terminal (PENDING) rather than guessing
        # terminal — a wrong terminal guess would drop a live order.
        status = OrderStatus.PENDING

    return {
        "order_id": str(order_id),
        "status": status,
        "raw_status": raw_status,
        "quantity": _to_float(_first(data, "quantity", "Quantity")),
        "filled_quantity": _to_float(
            _first(data, "tradedQty", "TradedQty", "fillQty", "FillQty")
        ),
        "average_fill_price": _to_float(
            _first(
                data,
                "avgTradedPrice", "AvgTradedPrice", "avgPrice", "TradedPrice",
            )
        ),
        "symbol": str(_first(data, "tradingSymbol", "Symbol") or ""),
        "timestamp": str(
            _first(data, "orderTimestamp", "OrderDateTime", "LastUpdatedTime") or ""
        ),
    }


class DhanOrderUpdateFeed:
    """Background Dhan order-update WebSocket with buffered dispatch.

    Public API (thread-safe): :meth:`start`, :meth:`stop`, :attr:`healthy`,
    :meth:`snapshot`, :meth:`wait_for_update`, and the ``on_update`` callback
    attribute (invoked with each normalized snapshot).
    """

    def __init__(
        self,
        client_id: str,
        access_token: str,
        *,
        on_update: Callable[[dict], None] | None = None,
        url: str | None = None,
        user_type: str | None = None,
    ) -> None:
        self._client_id = str(client_id or "")
        self._access_token = str(access_token or "")
        self.on_update = on_update
        self._url = (
            url
            or os.environ.get("DHAN_ORDER_WS_URL", "").strip()
            or _DEFAULT_ORDER_WS_URL
        )
        self._user_type = (
            user_type or os.environ.get("DHAN_WS_USER_TYPE", "SELF").strip() or "SELF"
        )
        self._reconnect_sec = _to_float(
            os.environ.get("DHAN_ORDER_WS_RECONNECT_SEC", "5")
        ) or 5.0

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._connected = False
        self._latest: "OrderedDict[str, dict]" = OrderedDict()
        self._events: dict[str, threading.Event] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws: Any = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background feed thread (idempotent)."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run, name="dhan-order-update-ws", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        """Signal the feed to stop and close the socket (idempotent)."""
        self._stop_event.set()
        loop = self._loop
        ws = self._ws
        if loop is not None and ws is not None:
            try:
                asyncio.run_coroutine_threadsafe(ws.close(), loop)
            except Exception:
                logger.debug("order WS close during stop failed (ignored)", exc_info=True)
        thread = self._thread
        if (
            thread is not None
            and thread.is_alive()
            and thread is not threading.current_thread()
        ):
            thread.join(timeout=5.0)

    @property
    def healthy(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive() and self._connected

    def is_running(self) -> bool:
        """True while the background thread is alive (connecting or connected)."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    # ------------------------------------------------------------------
    # Waiter API
    # ------------------------------------------------------------------

    def snapshot(self, order_id: str) -> dict | None:
        """Latest buffered update for *order_id*, or None."""
        with self._lock:
            return self._latest.get(str(order_id))

    def wait_for_update(self, order_id: str, timeout: float) -> bool:
        """Block until a new update for *order_id* arrives (or timeout).

        Returns True when at least one new update arrived; callers must
        re-check :meth:`snapshot` afterwards. Waiting on an unknown order is
        valid — the event is created so a late update wakes us immediately.
        """
        order_id = str(order_id)
        with self._lock:
            event = self._events.get(order_id)
            if event is None:
                event = threading.Event()
                self._events[order_id] = event
            event.clear()
        return event.wait(timeout)

    # ------------------------------------------------------------------
    # Test / injection hook
    # ------------------------------------------------------------------

    def inject_update(self, payload: dict) -> None:
        """Dispatch a raw payload as if it arrived on the socket (tests)."""
        self._dispatch(payload)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _run(self) -> None:
        try:
            asyncio.run(self._run_forever())
        except Exception:
            if not self._stop_event.is_set():
                logger.exception("order-update feed thread crashed — REST polling remains")

    async def _run_forever(self) -> None:
        backoff = 1.0
        while not self._stop_event.is_set():
            try:
                await self._consume_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if self._stop_event.is_set():
                    break
                logger.warning(
                    "Order-update WS error: %s — reconnecting in %.1fs", exc, backoff
                )
            # Bounded sleep that reacts quickly to stop requests.
            waited = 0.0
            while waited < backoff and not self._stop_event.is_set():
                await asyncio.sleep(0.2)
                waited += 0.2
            backoff = min(max(backoff * 2.0, 1.0), self._reconnect_sec)

    async def _consume_once(self) -> None:
        ws = await websockets.connect(
            self._url,
            ping_interval=20,
            ping_timeout=40.0,  # generous: event loop may stall during MLX inference
            close_timeout=10.0,
        )
        self._loop = asyncio.get_running_loop()
        self._ws = ws
        try:
            auth = {
                "LoginReq": {
                    "MsgCode": _AUTH_MSG_CODE,
                    "ClientId": self._client_id,
                    "Token": self._access_token,
                },
                "UserType": self._user_type,
            }
            await ws.send(json.dumps(auth))
            self._set_connected(True)
            logger.info("Order-update WS connected (%s)", self._url)
            async for message in ws:
                if self._stop_event.is_set():
                    break
                try:
                    payload = json.loads(message)
                except (TypeError, ValueError):
                    logger.debug("order WS non-JSON frame ignored")
                    continue
                self._dispatch(payload)
        finally:
            self._set_connected(False)
            self._ws = None
            try:
                await ws.close()
            except Exception:
                pass

    def _set_connected(self, value: bool) -> None:
        self._connected = value

    def _dispatch(self, payload: Any) -> None:
        snap = normalize_order_update(payload)
        if snap is None:
            return
        order_id = snap["order_id"]
        with self._lock:
            self._latest[order_id] = snap
            self._latest.move_to_end(order_id)
            while len(self._latest) > _MAX_TRACKED_ORDERS:
                old_id, _ = self._latest.popitem(last=False)
                self._events.pop(old_id, None)
            event = self._events.get(order_id)
            if event is None:
                event = threading.Event()
                self._events[order_id] = event
            event.set()
        callback = self.on_update
        if callback is not None:
            try:
                callback(snap)
            except Exception:
                logger.exception("order-update callback failed (ignored)")
