"""Live broker adapter for Multi‑Commodity Exchange (MCX) Futures.

The module intentionally keeps a strict boundary: transport logic here, all
execution policy in application/domain services.  This adapter is currently
non-production and remains wired as a guarded placeholder.

To use in live deployment, set a concrete live broker adapter in
``composition_root._create_broker_adapter`` and keep this module in sync with
``IBroker``.
"""

from __future__ import annotations

import logging
import json
import time
import uuid
from decimal import Decimal
from typing import Dict, Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from app.domain.ports.broker import IBroker
from app.domain.trading.models.entities import Position, Signal
from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.models.enums import Side
from app.config import settings

log = logging.getLogger(__name__)


def _make_headers() -> Dict[str, str]:
    """Construct the HTTP headers required by the MCX API."""
    return {
        "Authorization": f"Bearer {settings.mcx.api_key}",
        "Content-Type": "application/json",
        "User-Agent": "GlassyTrade-MCX-Broker/0.1",
    }


def _sign_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Apply request signature when supported."""
    import hmac
    import hashlib
    import base64

    secret = settings.mcx.api_secret.encode()
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(secret, raw, hashlib.sha256).digest()
    return payload | {"sig": base64.b64encode(signature).decode()}


class McxBrokerAdapter(IBroker):
    """MCX adapter.

    Notes:
    * This adapter is intentionally conservative: every public method checks
      whether it is explicitly enabled.
    * It satisfies ``IBroker`` as synchronous methods.
    """

    _pending_orders: dict[str, dict[str, Any]] = {}

    def __init__(self, base_url: str | None = None):
        self.base_url = base_url or settings.mcx.base_url
        self._live_enabled = bool(
            getattr(settings, "MCX_LIVE_ENABLED", False)
            or getattr(settings.mcx, "enabled", False)
        )
        self.session = httpx.Client(timeout=30.0, headers=_make_headers())

    def execute_order(
        self, signal: Signal, portfolio: Portfolio, symbol: str
    ) -> Position | None:
        """Execute a broker order and materialise a Position.

        Raises ``NotImplementedError`` when live execution is not enabled.
        """
        if not self._live_enabled:
            raise NotImplementedError(
                "MCX broker adapter is currently disabled for production use"
            )

        payload = self._build_order_payload(signal, symbol)
        order_id = str(uuid.uuid4())
        self._store_pending_order(order_id, payload, symbol)

        try:
            create_resp = self._post_create_order(payload)
            if create_resp.status_code == 400 and create_resp.json().get("error") == "InvalidSignal":
                self._remove_pending_order(order_id)
                return None

            broker_order_id = create_resp.json().get("order_id")
            if not broker_order_id:
                raise RuntimeError("MCX create-order response missing order_id")

            terminal, final_status = self._await_terminal(str(broker_order_id))
            if not terminal:
                return None
            if final_status.get("status") != "filled":
                return None

            fill_resp = self._post_get_fill(str(broker_order_id))
            return self._materialise_position(signal, fill_resp, symbol)
        finally:
            self._remove_pending_order(order_id)

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by broker order ID."""
        if not self._live_enabled:
            raise NotImplementedError(
                "MCX broker adapter is currently disabled for production use"
            )

        cancel_url = f"{self.base_url}/order/cancel/{order_id}"
        resp = self.session.delete(cancel_url)
        return resp.status_code == 200

    def _store_pending_order(self, order_id: str, payload: Dict[str, Any], symbol: str) -> None:
        self._pending_orders[order_id] = {"payload": payload, "symbol": symbol, "ts": time.time()}

    def _remove_pending_order(self, order_id: str) -> None:
        self._pending_orders.pop(order_id, None)

    def _build_order_payload(self, signal: Signal, symbol: str) -> Dict[str, Any]:
        """Translate a domain ``Signal`` into MCX payload fields."""
        meta = signal.metadata or {}
        quantity = int(meta.get("order_quantity", 0))
        if quantity <= 0:
            quantity = int(meta.get("size", 1) or 1)

        payload = {
            "symbol": symbol,
            "side": "BUY" if signal.is_buy else "SELL",
            "type": "LIMIT",
            "quantity": quantity,
            "price": float(signal.price),
            "client_id": str(signal.signal_id),
        }

        payload = _sign_payload(payload)
        return payload

    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(httpx.RequestError),
    )
    def _post_create_order(self, payload: Dict[str, Any]) -> httpx.Response:
        """POST /order/create — retry on transient network errors."""
        url = f"{self.base_url}/order/create"
        resp = self.session.post(url, json=payload)
        resp.raise_for_status()
        return resp

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        retry=retry_if_exception_type(httpx.RequestError),
    )
    def _post_get_fill(self, order_id: str) -> Dict[str, Any]:
        """GET /order/status/{order_id}."""
        url = f"{self.base_url}/order/status/{order_id}"
        resp = self.session.get(url)
        resp.raise_for_status()
        data = resp.json()
        return data

    def _await_terminal(self, broker_order_id: str) -> tuple[bool, Dict[str, Any]]:
        """Wait for order terminal state and return terminal flag + payload."""
        url = f"{self.base_url}/order/status/{broker_order_id}"
        while True:
            resp = self.session.get(url)
            resp.raise_for_status()
            data = resp.json()
            status = data.get("status")
            if status in {"filled", "canceled", "rejected"}:
                return status == "filled", data
            time.sleep(1.0)

    def _materialise_position(
        self,
        signal: Signal,
        fill_payload: Dict[str, Any],
        symbol: str,
    ) -> Position:
        """Build a Position-like record from a fill payload."""
        executed_price = float(fill_payload.get("average_price", signal.price))
        quantity = float(fill_payload.get("executed_quantity", 0.0))

        position = Position(
            symbol=symbol,
            side=Side.LONG if signal.is_buy else Side.SHORT,
            source=signal.source,
            entry_price=Decimal(str(executed_price)),
            size=Decimal(str(quantity or 1)),
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            entry_time=fill_payload.get("filled_at") or fill_payload.get("timestamp") or "",
            metadata=dict(signal.metadata or {}),
        )

        if position.metadata is None:
            position.metadata = {}
        position.metadata.update(
            {
                "source": "mcx",
                "fill_payload": fill_payload,
                "order_id": fill_payload.get("order_id"),
                "filled_price": executed_price,
            }
        )
        return position
