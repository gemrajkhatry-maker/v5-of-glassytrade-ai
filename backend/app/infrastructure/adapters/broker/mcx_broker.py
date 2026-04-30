"""Live broker adapter for Multi‑Commodity Exchange (MCX) Futures.

This adapter implements the `IBroker` contract and talks to the
official MCX REST API.  It is deliberately kept thin so that all
business‑logic (order sizing, risk checks, repeatability) lives in
the backend services, while this class only knows *how* to send an
order, poll for its status and return a domain `Position`.

The implementation follows the typical pattern:

* 1️⃣  Load credentials from the unified config (`settings.mcx.*`).
* 2️⃣  Build a signed HTTP request (`/order/create` endpoint).
* 3️⃣  Poll `/order/status/{order_id}` until terminal state
   (`filled`, `canceled`, `rejected`).
* 4️⃣  On success, materialise a `Position` entity and hand it back
   to the calling service.
* 5️⃣  All calls are wrapped with retry / circuit‑breaker logic
   (via `tenacity`) to survive transient network blips.
"""

from __future__ import annotations

import json
import uuid
import time
from typing import Optional, Dict, Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from httpx import Response

# Domain entities – keep them lightweight so the adapter does not depend
# on heavy ORM models when it is imported.
from app.domain.trading.models.entities import Position, Signal
from app.domain.trading.models.aggregates import Portfolio

# Config – unified settings that already exist in ConsolidatedConfig
from app.config import settings

# --------------------------------------------------------------------------- #
# Helper utilities
# --------------------------------------------------------------------------- #
def _make_headers() -> Dict[str, str]:
    """Construct the HTTP headers required by the MCX API."""
    return {
        "Authorization": f"Bearer {settings.mcx.api_key}",
        "Content-Type": "application/json",
        "User-Agent": "GlassyTrade-MCX-Broker/0.1",
    }


def _sign_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Some brokers require a HMAC‑SHA256 signature of the request body.
    The exact algorithm is broker‑specific; the stub below shows a
    generic approach that can be swapped out if the real API uses a
    different method.
    """
    import hmac, hashlib, base64

    secret = settings.mcx.api_secret.encode()
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    signature = hmac.new(secret, raw, hashlib.sha256).digest()
    return payload | {"sig": base64.b64encode(signature).decode()}


# --------------------------------------------------------------------------- #
# Core Adapter
# --------------------------------------------------------------------------- #
class McxBrokerAdapter:
    """
    Live broker adapter for MCX Futures.

    Parameters
    ----------
    base_url: str, optional
        Base URL of the MCX API.  Defaults to the production endpoint,
        but can be overridden in tests.
    """

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = (
            base_url
            if base_url
            else settings.mcx.base_url  # e.g. "https://api.mcxindia.com"
        )
        self.session = httpx.AsyncClient(
            timeout=30.0,
            headers=_make_headers(),
        )

    # --------------------------------------------------------------------- #
    # Public API – required by `IBroker`
    # --------------------------------------------------------------------- #
    async def execute_order(
        self, signal: Signal, portfolio: Portfolio, symbol: str
    ) -> Optional[Position]:
        """
        Place an order on MCX and return a populated `Position` if the
        order eventually fills.

        The method follows the classic async‑await pattern:
        * build the order payload,
        * POST to `/order/create`,
        * poll `/order/status/{order_id}` until terminal,
        * materialise a `Position`,
        * finally return it (or ``None`` if the broker rejected the order).
        """
        # 1️⃣  Assemble the order payload from the signal
        payload = self._build_order_payload(signal, symbol)

        # 2️⃣  Persist a temporary placeholder order ID – needed for cancel
        order_id = str(uuid.uuid4())
        self._store_pending_order(order_id, payload, symbol)

        # 3️⃣  Send the creation request with retry logic
        create_resp = await self._post_create_order(payload, order_id)

        # 4️⃣  If the broker immediately rejected the order, bail out early
        if create_resp.status_code == 400 and create_resp.json().get("error") == "InvalidSignal":
            self._remove_pending_order(order_id)
            return None

        # 5️⃣  Extract the broker‑assigned order identifier
        broker_order_id = create_resp.json()["order_id"]

        # 6️⃣  Poll for status changes
        terminal, final_status = await self._await_terminal(broker_order_id)

        # 7️⃣  If terminal is not *filled*, treat it as a failure
        if not terminal:
            self._remove_pending_order(order_id)
            return None

        # 8️⃣  Build and return a domain `Position`
        filled = final_status  # type: ignore[assignment]  # mypy narrows after check
        if filled.get("status") != "filled":
            self._remove_pending_order(order_id)
            return None

        fill_resp = await self._post_get_fill(broker_order_id)
        pos = self._materialise_position(signal, fill_resp, symbol, order_id)
        self._remove_pending_order(order_id)
        return pos

    async def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an already‑opened order via the MCX cancel endpoint.
        Returns ``True`` if the broker accepted the cancellation request.
        """
        cancel_url = f"{self.base_url}/order/cancel/{order_id}"
        resp = await self.session.delete(cancel_url)
        # Simple success check – the real API may return a detailed payload
        return resp.status_code == 200

    # --------------------------------------------------------------------- #
    # Internal helpers
    # --------------------------------------------------------------------- #
    def _store_pending_order(self, order_id: str, payload: Dict[str, Any], symbol: str) -> None:
        """
        Keep a short‑lived in‑memory record so that a later cancel can be
        correlated with the pending request.  In production we would
        persist this in DB, but for the current MVP an in‑process dict is
        sufficient.
        """
        # The container keeps a thread‑safe map of pending orders.
        from ..di.container import current_container

        pending: Dict[str, Dict[str, Any]] = current_container.pending_orders()
        pending[order_id] = {"payload": payload, "symbol": symbol, "ts": time.time()}

    def _remove_pending_order(self, order_id: str) -> None:
        """Remove a pending order record."""
        from ..di.container import current_container

        pending: Dict[str, Dict[str, Any]] = current_container.pending_orders()
        pending.pop(order_id, None)

    # --------------------------------------------------------------------- #
    # Payload construction
    # --------------------------------------------------------------------- #
    def _build_order_payload(self, signal: Signal, symbol: str) -> Dict[str, Any]:
        """
        Translate a domain `Signal` into the JSON structure required by
        MCX.  The exact field names depend on the broker’s spec.
        """
        # Example payload – adapt to the real schema
        base_qty = signal.qty  # assume signal already respects quantity limits
        price = signal.price   # limit price supplied by the strategy

        payload = {
            "symbol": symbol,
            "side": "BUY" if signal.side == "long" else "SELL",
            "type": "LIMIT",
            "quantity": base_qty,
            "price": price,
            "client_id": signal.strategy_id,  # useful for audit trails
        }

        # If the exchange requires a signature, append it now
        payload = _sign_payload(payload)
        return payload

    # --------------------------------------------------------------------- #
    # HTTP helpers with retry / circuit‑breaker
    # --------------------------------------------------------------------- #
    @retry(
        reraise=True,
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(httpx.RequestError),
    )
    async def _post_create_order(self, payload: Dict[str, Any], order_id: str) -> Response:
        """POST /order/create – retry on network errors."""
        url = f"{self.base_url}/order/create"
        # Attach the already‑signed payload
        resp = await self.session.post(url, json=payload)
        resp.raise_for_status()
        return resp

    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=6),
        retry=retry_if_exception_type(httpx.RequestError),
    )
    async def _post_get_fill(self, order_id: str) -> Response:
        """GET /order/status/{order_id} – retry on network errors."""
        url = f"{self.base_url}/order/status/{order_id}"
        resp = await self.session.get(url)
        resp.raise_for_status()
        return resp

    async def _await_terminal(self, broker_order_id: str) -> tuple[bool, Dict[str, Any]]:
        """
        Loop until the order reaches a terminal state (`filled`,
        `canceled`, `rejected`).  Returns a tuple:

        * ``terminal`` – ``True`` when a terminal state is hit.
        * ``final_status`` – the parsed JSON payload from the broker.
        """
        while True:
            resp = await self.session.get(
                f"{self.base_url}/order/status/{broker_order_id}"
            )
            data = resp.json()
            status = data.get("status")
            if status in {"filled", "canceled", "rejected"}:
                return status == "filled", data
            # Not terminal yet → sleep 1 s and retry
            await asyncio.sleep(1.0)

    def _materialise_position(
        self,
        signal: Signal,
        fill_payload: Dict[str, Any],
        symbol: str,
        broker_order_id: str,
    ) -> Position:
        """
        Convert the broker’s fill response into a domain `Position`.
        The position is stored in the DB later by the calling service.
        """
        # The fill payload typically contains:
        #   - executed_quantity
        #   - average_price
        #   - side (BUY/SELL)
        qty = int(fill_payload.get("executed_quantity", 0))
        price = float(fill_payload.get("average_price", 0.0))
        side = fill_payload.get("side", "BUY")

        return Position(
            order_id=broker_order_id,
            symbol=symbol,
            side="long" if side == "BUY" else "short",
            entry_price=price,
            quantity=qty,
            timestamp=time.time(),
            source="mcx_broker",
        )