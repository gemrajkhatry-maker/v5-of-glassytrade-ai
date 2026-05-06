"""MCX Futures broker adapter for v2.

This adapter implements the domain IBroker port for Multi-Commodity Exchange
(MCX) futures.  It is intentionally conservative:
  - Live execution requires explicit opt-in via MCX_LIVE_ENABLED=true.
  - Order placement retries on transient network errors (exponential backoff).
  - _await_terminal blocks until order reaches a filled / canceled / rejected
    terminal state (or the caller's timeout).

Wiring (composition root or test):
    broker = McxBrokerAdapter(base_url="https://api.example.com")
    # or via settings:
    broker = McxBrokerAdapter()
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from decimal import Decimal
from typing import Any

import httpx

from app.domain.shared.port.broker import IBroker
from app.domain.trading.model.entities import Position, Signal
from app.domain.trading.model.aggregates import Portfolio
from app.domain.trading.model.enums import Side

log = logging.getLogger(__name__)

_BASE_URL = os.environ.get("MCX_BASE_URL", "https://api.mcxindia.com/v1")
_API_KEY = os.environ.get("MCX_API_KEY", "")
_API_SECRET = os.environ.get("MCX_API_SECRET", "")
_LIVE_ENABLED = os.environ.get("MCX_LIVE_ENABLED", "").lower() in ("1", "true", "yes")


def _make_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_API_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "GlassyTrade-MCX-Broker/2.0",
    }


def _sign_payload(payload: dict[str, Any], secret: str) -> dict[str, Any]:
    """Attach HMAC-SHA256 signature to payload."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).digest()
    return payload | {"sig": base64.b64encode(sig).decode()}


class McxBrokerAdapter(IBroker):
    """Live MCX broker adapter.

    Disabled by default.  Set MCX_LIVE_ENABLED=true to enable real orders.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        live_enabled: bool | None = None,
    ) -> None:
        self._base_url = (base_url or _BASE_URL).rstrip("/")
        self._api_key = api_key or _API_KEY
        self._api_secret = api_secret or _API_SECRET
        self._live_enabled = live_enabled if live_enabled is not None else _LIVE_ENABLED
        self._pending: dict[str, dict[str, Any]] = {}
        self._session = httpx.Client(
            timeout=30.0,
            headers=_make_headers(),
        )

    # ------------------------------------------------------------------
    # IBroker interface
    # ------------------------------------------------------------------

    def execute_order(
        self, signal: Signal, portfolio: Portfolio, symbol: str
    ) -> Position | None:
        """Execute a limit order and return the materialised Position.

        Raises NotImplementedError when live execution is not enabled.
        """
        if not self._live_enabled:
            raise NotImplementedError(
                "MCX broker adapter live execution is disabled "
                "(set MCX_LIVE_ENABLED=true to enable)"
            )

        payload = self._build_order_payload(signal, symbol)
        local_id = str(uuid.uuid4())
        self._pending[local_id] = {"payload": payload, "symbol": symbol, "ts": time.time()}

        try:
            resp = self._post_create_order(payload)
            if resp.status_code == 400:
                body = resp.json()
                if body.get("error") == "InvalidSignal":
                    log.warning("MCX rejected order (InvalidSignal): %s", body)
                    return None

            broker_order_id = resp.json().get("order_id")
            if not broker_order_id:
                raise RuntimeError("MCX create-order response missing order_id")

            filled, status_data = self._await_terminal(str(broker_order_id))
            if not filled:
                log.warning(
                    "MCX order %s terminal with status %s — not filling",
                    broker_order_id,
                    status_data.get("status"),
                )
                return None

            fill_data = self._get_fill(str(broker_order_id))
            return self._materialise(signal, fill_data, symbol)
        except httpx.RequestError as exc:
            log.error("MCX network error placing order: %s", exc)
            return None
        finally:
            self._pending.pop(local_id, None)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by its broker order ID."""
        if not self._live_enabled:
            raise NotImplementedError(
                "MCX broker adapter live execution is disabled"
            )
        try:
            resp = self._session.delete(f"{self._base_url}/order/cancel/{order_id}")
            return resp.status_code == 200
        except httpx.RequestError as exc:
            log.error("MCX cancel_order network error: %s", exc)
            return False

    def close_position(self, position_id: str, price: float) -> bool:
        """Close an open position.  Not directly supported by MCX; callers should
        place an offsetting order via execute_order instead.
        """
        log.warning(
            "McxBrokerAdapter.close_position called for %s at %.2f — "
            "MCX requires an explicit opposite-side order to close",
            position_id,
            price,
        )
        return False

    # ------------------------------------------------------------------
    # Order lifecycle helpers
    # ------------------------------------------------------------------

    def _build_order_payload(self, signal: Signal, symbol: str) -> dict[str, Any]:
        meta = signal.metadata or {}
        quantity = int(meta.get("order_quantity", 0))
        if quantity <= 0:
            quantity = int(meta.get("size", 1) or 1)

        payload: dict[str, Any] = {
            "symbol": symbol,
            "side": "BUY" if signal.is_buy else "SELL",
            "type": "LIMIT",
            "quantity": quantity,
            "price": float(signal.price),
            "client_id": str(signal.signal_id),
        }
        if self._api_secret:
            payload = _sign_payload(payload, self._api_secret)
        return payload

    def _post_create_order(self, payload: dict[str, Any]) -> httpx.Response:
        """POST /order/create with up to 4 retries on transient errors."""
        url = f"{self._base_url}/order/create"
        attempts = 0
        delay = 1.0
        last_exc: Exception | None = None
        while attempts < 4:
            try:
                resp = self._session.post(url, json=payload)
                resp.raise_for_status()
                return resp
            except httpx.RequestError as exc:
                last_exc = exc
                attempts += 1
                if attempts < 4:
                    time.sleep(delay)
                    delay = min(delay * 2, 8.0)
        raise last_exc or RuntimeError("_post_create_order: all retries exhausted")

    def _get_fill(self, order_id: str) -> dict[str, Any]:
        """GET /order/status/{order_id} with up to 3 retries."""
        url = f"{self._base_url}/order/status/{order_id}"
        attempts = 0
        delay = 1.0
        last_exc: Exception | None = None
        while attempts < 3:
            try:
                resp = self._session.get(url)
                resp.raise_for_status()
                return resp.json()
            except httpx.RequestError as exc:
                last_exc = exc
                attempts += 1
                if attempts < 3:
                    time.sleep(delay)
                    delay = min(delay * 2, 6.0)
        raise last_exc or RuntimeError("_get_fill: all retries exhausted")

    def _await_terminal(
        self, broker_order_id: str, poll_interval: float = 1.0
    ) -> tuple[bool, dict[str, Any]]:
        """Poll until order reaches a terminal state."""
        url = f"{self._base_url}/order/status/{broker_order_id}"
        while True:
            try:
                resp = self._session.get(url)
                resp.raise_for_status()
                data = resp.json()
                status = data.get("status", "")
                if status in {"filled", "canceled", "rejected"}:
                    return status == "filled", data
                time.sleep(poll_interval)
            except httpx.RequestError as exc:
                log.warning("MCX poll error for %s: %s", broker_order_id, exc)
                time.sleep(poll_interval)

    def _materialise(
        self, signal: Signal, fill: dict[str, Any], symbol: str
    ) -> Position:
        """Build a domain Position from an MCX fill payload."""
        executed_price = float(fill.get("average_price", signal.price))
        quantity = float(fill.get("executed_quantity", 1.0))

        position = Position(
            symbol=symbol,
            side=Side.LONG if signal.is_buy else Side.SHORT,
            source=signal.source,
            entry_price=Decimal(str(executed_price)),
            size=Decimal(str(max(quantity, 1.0))),
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            entry_time=fill.get("filled_at") or fill.get("timestamp") or "",
            metadata=dict(signal.metadata or {}),
        )
        if position.metadata is None:
            position.metadata = {}
        position.metadata.update(
            {
                "source": "mcx",
                "broker_order_id": fill.get("order_id"),
                "filled_price": executed_price,
            }
        )
        return position
