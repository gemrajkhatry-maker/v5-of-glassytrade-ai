"""
DhanHQ v2 HTTP client adapter.
"""

from __future__ import annotations

from typing import Optional, List, Dict, Any
from dataclasses import dataclass
import logging

import aiohttp
from aiohttp import ClientTimeout

from brokersv2.core.types import (
    SecurityId,
    OrderId,
    Exchange,
)
from brokersv2.domain.order.models import Order, OrderStatus
from brokersv2.domain.market.models import Quote, Candle
from brokersv2.domain.market.hours import MarketHoursGate, MarketClosedError
from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper, BrokerInstrumentMapping
from brokersv2.infrastructure.rate_limiter.token_bucket import RateLimiter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brokersv2.domain.instrument.models import CanonicalInstrument


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Domain exceptions raised before any network call
# ---------------------------------------------------------------------------

class LotSizeError(ValueError):
    """Raised when order quantity is not a multiple of the instrument lot size."""

    def __init__(self, quantity: int, lot_size: int, symbol: str) -> None:
        self.quantity = quantity
        self.lot_size = lot_size
        self.symbol = symbol
        super().__init__(
            f"Order quantity {quantity} for {symbol} is not a multiple of lot size {lot_size}."
        )


class FreezeQuantityError(ValueError):
    """
    Raised when order quantity exceeds the exchange freeze quantity limit.

    The caller must slice the order using DhanHQ /orders/slicing endpoint.
    """

    def __init__(self, quantity: int, freeze_qty: int, symbol: str) -> None:
        self.quantity = quantity
        self.freeze_qty = freeze_qty
        self.symbol = symbol
        super().__init__(
            f"Order quantity {quantity} for {symbol} exceeds exchange freeze limit "
            f"{freeze_qty}.  Use /orders/slicing to split the order."
        )


def validate_lot_size(order: "Order", instrument: "CanonicalInstrument") -> None:
    """Raise LotSizeError if quantity is not a multiple of lot_size."""
    lot = int(instrument.lot_size) if instrument.lot_size else 1
    if lot > 1 and int(order.quantity) % lot != 0:
        raise LotSizeError(int(order.quantity), lot, instrument.symbol)


def validate_freeze_quantity(order: "Order", instrument: "CanonicalInstrument") -> None:
    """Raise FreezeQuantityError if quantity exceeds exchange freeze limit."""
    freeze = getattr(instrument, "freeze_quantity", None)
    if freeze and int(order.quantity) > int(freeze):
        raise FreezeQuantityError(int(order.quantity), int(freeze), instrument.symbol)


@dataclass
class DhanConfig:
    """DhanHQ configuration."""
    client_id: str
    access_token: str
    base_url: str = "https://api.dhan.co/v2"  # Dhan v2 API
    ws_url: str = "wss://api.dhan.co/ws"
    timeout: int = 30


class DhanHttpClient:
    """
    DhanHQ v2 HTTP client with rate limiting.
    
    Handles all REST API calls to DhanHQ.
    """
    
    def __init__(
        self,
        config: DhanConfig,
        rate_limiter: Optional[RateLimiter] = None,
        market_hours_gate: Optional[MarketHoursGate] = None,
        margin_checker=None,
        auth_provider=None,  # NEW: Optional auth provider for token refresh
    ):
        self.config = config
        self._rate_limiter = rate_limiter or RateLimiter()
        self._market_hours_gate = market_hours_gate or MarketHoursGate()
        self._margin_checker = margin_checker  # injected post-init to avoid circular import
        self._auth_provider = auth_provider  # NEW: Store auth provider
        self._session: Optional[aiohttp.ClientSession] = None
        
        # NEW: Use auth provider's token if available, otherwise use config token
        initial_token = auth_provider._access_token if auth_provider and auth_provider._access_token else config.access_token
        self._headers = {
            "access-token": initial_token,
            "client-id": config.client_id,
            "Content-Type": "application/json",
        }
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session."""
        if self._session is None or self._session.closed:
            timeout = ClientTimeout(total=self.config.timeout)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session
    
    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def _refresh_headers(self) -> None:
        """Refresh auth headers from auth provider (called on 401 or proactively)."""
        if self._auth_provider:
            try:
                fresh_token = await self._auth_provider.ensure_valid_token()
                self._headers["access-token"] = fresh_token
            except Exception as e:
                logger.warning("Token refresh failed: %s", e)

    async def _request(
        self,
        method: str,
        endpoint: str,
        bucket: str = "default",
        **kwargs,
    ) -> Dict[str, Any]:
        """
        Make HTTP request with rate limiting.
        
        Args:
            method: HTTP method (GET, POST, DELETE)
            endpoint: API endpoint path
            bucket: Rate limit bucket name
            **kwargs: Additional args for aiohttp
        
        Returns:
            JSON response as dict
        """
        # Ensure valid token before each request
        if self._auth_provider:
            try:
                fresh_token = await self._auth_provider.ensure_valid_token()
                self._headers["access-token"] = fresh_token
            except Exception as e:
                logger.warning("Token refresh before request failed: %s", e)

        # Async rate-limit wait — non-blocking, yields to the event loop
        if not await self._rate_limiter.async_wait_for_token(bucket):
            logger.warning("Rate limit timeout for bucket: %s", bucket)
            raise TimeoutError(f"Rate limit exceeded for {bucket}")
        
        session = await self._get_session()
        url = f"{self.config.base_url}{endpoint}"
        
        async with session.request(method, url, headers=self._headers, **kwargs) as response:
            if response.status == 401 and self._auth_provider:
                # Token rejected — refresh and retry once
                await self._refresh_headers()
                async with session.request(method, url, headers=self._headers, **kwargs) as retry_response:
                    if retry_response.status != 200:
                        error_text = await retry_response.text()
                        logger.error("Dhan API error %s (after token refresh): %s", retry_response.status, error_text)
                        retry_response.raise_for_status()
                    return await retry_response.json()

            # Retry 5xx errors once with brief delay
            if response.status in (500, 502, 503, 504):
                import asyncio as _asyncio
                error_text = await response.text()
                logger.warning("Dhan API server error %s, retrying once: %s", response.status, error_text)
                await _asyncio.sleep(1)  # Brief backoff
                async with session.request(method, url, headers=self._headers, **kwargs) as retry_response:
                    if retry_response.status == 200:
                        return await retry_response.json()
                    # Retry failed — parse and raise
                    retry_text = await retry_response.text()
                    logger.error("Dhan API error %s (retry failed): %s", retry_response.status, retry_text)
                    retry_response.raise_for_status()

            if response.status != 200:
                error_text = await response.text()
                # Parse structured error from JSON body if available
                error_msg = error_text
                try:
                    error_body = await response.json()
                    error_msg = error_body.get("message", error_body.get("error", error_text))
                except Exception:
                    pass
                logger.error("Dhan API error %s: %s", response.status, error_msg)
                response.raise_for_status()
            return await response.json()
    
    async def get_quote(
        self,
        instrument: "CanonicalInstrument",
        mapper: InstrumentMapper,
    ) -> Quote:
        """
        Get a real-time quote via DhanHQ v2 ``POST /marketfeed/quote``.

        The API expects a dict keyed by exchange_segment with lists of security IDs:
            {"NSE_EQ": ["11536"], "NSE_FNO": ["49081"]}

        Response structure: ``{"data": {"NSE_EQ": [{"securityId": "11536", ...}]}}``
        """
        mapping = mapper.canonical_to_broker_mapping(instrument)
        if not mapping:
            raise ValueError(f"No broker mapping for {instrument.symbol}")

        payload = {mapping.exchange_segment: [mapping.security_id]}
        data = await self._request("POST", "/marketfeed/quote", bucket="quotes", json=payload)

        # Unwrap the nested response: data → exchange_segment → list[quote_dict]
        segment_data = (data.get("data") or data).get(mapping.exchange_segment, [])
        quote_dict = segment_data[0] if segment_data else {}

        return Quote(
            instrument=instrument,
            ltp=float(quote_dict.get("LTP", 0)),
            bid=float(quote_dict.get("bestBidPrice", quote_dict.get("bid", 0))),
            ask=float(quote_dict.get("bestAskPrice", quote_dict.get("ask", 0))),
            volume=int(quote_dict.get("volume", 0)),
            open=float(quote_dict.get("open", 0)),
            high=float(quote_dict.get("high", 0)),
            low=float(quote_dict.get("low", 0)),
            close=float(quote_dict.get("close", 0)),
            oi=int(quote_dict.get("OI", 0)) if quote_dict.get("OI") else None,
        )

    async def get_quotes_bulk(
        self,
        instruments: List["CanonicalInstrument"],
        mapper: InstrumentMapper,
    ) -> List[Quote]:
        """
        Fetch quotes for multiple instruments in a single ``POST /marketfeed/quote`` call.

        Instruments are grouped by exchange_segment as required by the Dhan API.
        """
        segment_map: Dict[str, List[str]] = {}
        instrument_index: Dict[str, "CanonicalInstrument"] = {}

        for inst in instruments:
            m = mapper.canonical_to_broker_mapping(inst)
            if not m:
                continue
            segment_map.setdefault(m.exchange_segment, []).append(m.security_id)
            instrument_index[m.security_id] = inst

        data = await self._request("POST", "/marketfeed/quote", bucket="quotes", json=segment_map)
        inner = data.get("data") or data

        quotes: List[Quote] = []
        for segment, quote_list in inner.items():
            for q in quote_list:
                sec_id = q.get("securityId", q.get("security_id", ""))
                inst = instrument_index.get(sec_id)
                if inst is None:
                    continue
                quotes.append(Quote(
                    instrument=inst,
                    ltp=float(q.get("LTP", 0)),
                    bid=float(q.get("bestBidPrice", q.get("bid", 0))),
                    ask=float(q.get("bestAskPrice", q.get("ask", 0))),
                    volume=int(q.get("volume", 0)),
                    open=float(q.get("open", 0)),
                    high=float(q.get("high", 0)),
                    low=float(q.get("low", 0)),
                    close=float(q.get("close", 0)),
                    oi=int(q.get("OI", 0)) if q.get("OI") else None,
                ))
        return quotes
    
    async def place_order(
        self,
        order: Order,
        mapper: InstrumentMapper,
    ) -> str:
        """Place order and return broker order ID.

        Builds a fully-compliant DhanHQ v2 order payload including
        productType, validity, correlationId, dhanClientId, disclosedQuantity,
        and AMO fields.  Raises ValueError if the instrument has no broker mapping.
        """
        mapping = mapper.canonical_to_broker_mapping(order.instrument)
        if not mapping:
            raise ValueError(f"No broker mapping for {order.instrument.symbol}")

        # Hard-reject orders outside market hours (unless it is an AMO order)
        if not getattr(order, "after_market_order", False):
            self._market_hours_gate.check(mapping.exchange_segment)

        # Lot size and freeze quantity validation — raises before any network call
        validate_lot_size(order, order.instrument)
        validate_freeze_quantity(order, order.instrument)

        # Margin pre-check (optional — wired post-init from bootstrap)
        if self._margin_checker is not None:
            await self._margin_checker.check(order)

        # Resolve product_type — default CNC if attribute missing (backward compat)
        product_type = getattr(order, "product_type", None)
        product_type_val = product_type.value if product_type is not None else "CNC"

        validity = getattr(order, "validity", None)
        validity_val = validity.value if validity is not None else "DAY"

        amo = getattr(order, "after_market_order", False)
        amo_time = getattr(order, "amo_time", None)
        disclosed_qty = getattr(order, "disclosed_quantity", None) or 0

        payload = {
            "dhanClientId": self.config.client_id,
            "correlationId": str(order.correlation_id or ""),
            "transactionType": order.side.value,
            "exchangeSegment": mapping.exchange_segment,
            "productType": product_type_val,
            "orderType": order.order_type.value,
            "validity": validity_val,
            "securityId": mapping.security_id,
            "quantity": int(order.quantity),
            "disclosedQuantity": disclosed_qty,
            "price": float(order.price) if order.price else 0.0,
            "triggerPrice": float(order.trigger_price) if order.trigger_price else 0.0,
            "afterMarketOrder": amo,
            "amoTime": amo_time.value if amo_time is not None else "",
        }

        data = await self._request("POST", "/orders", bucket="orders", json=payload)
        return data.get("orderId", data.get("order_id", ""))

    async def modify_order(
        self,
        broker_order_id: str,
        price: Optional[float] = None,
        quantity: Optional[int] = None,
        order_type: Optional[str] = None,
        validity: Optional[str] = None,
        trigger_price: Optional[float] = None,
        disclosed_quantity: Optional[int] = None,
    ) -> bool:
        """Modify a pending order via DhanHQ PUT /orders/{order-id}.

        Only supply the fields you want to change; omitted fields keep their
        current values as per the Dhan API contract.
        """
        payload: dict = {"dhanClientId": self.config.client_id, "orderId": broker_order_id}
        if price is not None:
            payload["price"] = price
        if quantity is not None:
            payload["quantity"] = quantity
        if order_type is not None:
            payload["orderType"] = order_type
        if validity is not None:
            payload["validity"] = validity
        if trigger_price is not None:
            payload["triggerPrice"] = trigger_price
        if disclosed_quantity is not None:
            payload["disclosedQuantity"] = disclosed_quantity

        await self._request("PUT", f"/orders/{broker_order_id}", bucket="orders", json=payload)
        return True
    
    async def cancel_order(self, broker_order_id: str) -> bool:
        """Cancel order by broker order ID."""
        endpoint = f"/orders/{broker_order_id}"
        await self._request("DELETE", endpoint, bucket="orders")
        return True
    
    async def get_order_status(self, broker_order_id: str) -> Order:
        """Get order status."""
        endpoint = f"/orders/{broker_order_id}"
        data = await self._request("GET", endpoint, bucket="non_trading")
        
        # This would need instrument mapping to create full Order object
        # Simplified for now
        return Order(
            order_id=OrderId(broker_order_id),
            instrument=None,  # Would need to look up from mapper
            side=None,  # Would parse from data
            quantity=0,
            status=OrderStatus(data.get("status", "UNKNOWN")),
        )
    
    async def get_historical(
        self,
        instrument: "CanonicalInstrument",
        from_date: str,
        to_date: str,
        interval: str = "1d",
        mapper: Optional[InstrumentMapper] = None,
    ) -> List[Candle]:
        """Get historical data."""
        from brokersv2.core.types import Segment, InstrumentType
        
        mapping = mapper.canonical_to_broker_mapping(instrument) if mapper else None
        security_id = mapping.security_id if mapping else ""
        exchange_segment = mapping.exchange_segment if mapping else ""
        
        # Infer instrument type for Dhan API
        if instrument.segment == Segment.COMMODITY:
            dhan_instrument = "COMMODITY"
        elif instrument.instrument_type == InstrumentType.OPTION:
            dhan_instrument = "OPTION"
        elif instrument.instrument_type == InstrumentType.FUTURE:
            dhan_instrument = "FUTURE"
        else:
            dhan_instrument = "EQUITY"
        
        # Dhan v2 API has two endpoints:
        # - /charts/historical for daily data ("1d")
        # - /charts/intraday for minute data ("1", "5", "15", "25", "60")
        if interval == "1d":
            endpoint = "/charts/historical"
            payload = {
                "securityId": security_id,
                "exchangeSegment": exchange_segment,
                "instrument": dhan_instrument,
                "expiryCode": 0,
                "oi": False,
                "fromDate": from_date,
                "toDate": to_date,
            }
        else:
            endpoint = "/charts/intraday"
            # Intraday requires datetime strings
            payload = {
                "securityId": security_id,
                "exchangeSegment": exchange_segment,
                "instrument": dhan_instrument,
                "interval": interval,
                "oi": False,
                "fromDate": f"{from_date} 09:15:00",
                "toDate": f"{to_date} 15:30:00",
            }
        
        data = await self._request("POST", endpoint, bucket="historical", json=payload)
        
        candles = []
        for row in data.get("data", []):
            candles.append(Candle(
                instrument=instrument,
                timeframe=interval,
                timestamp=row.get("timestamp", row.get("date")),
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=float(row.get("volume", 0)),
            ))
        
        return candles
    
    async def get_option_chain(
        self,
        symbol: str,
        exchange: str = "NSE",
        expiry_index: int = 0,
        mapper: Optional[InstrumentMapper] = None,
    ) -> Dict[str, Any]:
        """
        Fetch option chain from DhanHQ API.
        
        API: POST /optionchain
        Body: {
            "UnderlyingScrip": <security_id>,
            "UnderlyingSeg": <segment>,
            "Expiry": <expiry_date>
        }
        
        Args:
            symbol: Underlying symbol (e.g., "NIFTY", "BANKNIFTY")
            exchange: Exchange code (default: "NSE")
            expiry_index: Expiry selection (0=current, 1=near, 2=far)
            mapper: Instrument mapper to resolve security ID
        
        Returns:
            Dict with option chain data
        """
        # Normalize symbol input
        symbol = symbol.upper().strip()
        
        # Index underlyings that use IDX_I segment
        INDEX_UNDERLYINGS = {"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"}
        
        # Determine API segment
        if symbol.upper() in INDEX_UNDERLYINGS:
            api_segment = "IDX_I"
            # Index security IDs (hardcoded for common indices)
            index_security_ids = {
                "NIFTY": "13",
                "BANKNIFTY": "14",
                "FINNIFTY": "23",
                "MIDCPNIFTY": "26",
            }
            security_id = index_security_ids.get(symbol.upper(), "")
        else:
            # For stocks, use mapper if available
            if mapper:
                from brokersv2.domain.instrument.models import CanonicalInstrument
                
                canonical = CanonicalInstrument.create_equity(
                    symbol=symbol.upper(),
                    exchange=Exchange.NSE if exchange == "NSE" else Exchange.BSE,
                )
                mapping = mapper.canonical_to_broker_mapping(canonical)
                if mapping:
                    security_id = mapping.security_id
                    api_segment = mapping.exchange_segment
                else:
                    security_id = ""
                    api_segment = "NSE_FNO" if exchange == "NSE" else "BSE_FNO"
            else:
                security_id = ""
                api_segment = "NSE_FNO" if exchange == "NSE" else "BSE_FNO"
        
        if not security_id:
            raise ValueError(f"Cannot resolve security_id for {symbol}. Please register instrument in mapper.")
        
        # Step 1: Fetch expiry list
        logger.info(f"Fetching expiry list for {symbol} (security_id={security_id}, segment={api_segment})")
        expiry_payload = {
            "UnderlyingScrip": int(security_id) if security_id.isdigit() else security_id,
            "UnderlyingSeg": api_segment,
        }
        
        expiry_data = await self._request(
            "POST",
            "/optionchain/expirylist",
            bucket="non_trading",
            json=expiry_payload,
        )
        
        # Parse expiry list
        expiries = expiry_data.get("data", [])
        if isinstance(expiries, dict):
            expiries = expiries.get("data", [])
        
        if not expiries or expiry_index >= len(expiries):
            raise ValueError(f"No expiry found at index {expiry_index} for {symbol}")
        
        expiry_date = expiries[expiry_index]
        logger.info(f"Selected expiry: {expiry_date} (index={expiry_index})")
        
        # Step 2: Fetch option chain for selected expiry
        chain_payload = {
            "UnderlyingScrip": int(security_id) if security_id.isdigit() else security_id,
            "UnderlyingSeg": api_segment,
            "Expiry": expiry_date,
        }
        
        logger.info(f"Fetching option chain: {symbol} expiry={expiry_date}")
        data = await self._request(
            "POST",
            "/optionchain",
            bucket="option_chain",  # Use specific bucket for rate limiting
            json=chain_payload,
        )
        
        logger.info(f"Option chain received for {symbol} expiry={expiry_date}")
        
        # Add expiry date to response for adapter to use
        data['expiry'] = expiry_date

        return data

    async def get_positions(self) -> List[Dict[str, Any]]:
        """Fetch current intraday positions from DhanHQ GET /positions."""
        data = await self._request("GET", "/positions", bucket="non_trading")
        return data.get("data", data) if isinstance(data, dict) else data

    async def get_holdings(self) -> List[Dict[str, Any]]:
        """Fetch CNC holdings (T+1 carryforward) from DhanHQ GET /holdings."""
        data = await self._request("GET", "/holdings", bucket="non_trading")
        return data.get("data", data) if isinstance(data, dict) else data

    async def get_orders(self) -> List[Dict[str, Any]]:
        """Fetch today's orders from DhanHQ GET /orders."""
        data = await self._request("GET", "/orders", bucket="non_trading")
        return data.get("data", data) if isinstance(data, dict) else data

    async def get_fund_limit(self) -> Dict[str, Any]:
        """Fetch available funds and margin from DhanHQ GET /fundlimit."""
        data = await self._request("GET", "/fundlimit", bucket="non_trading")
        return data.get("data", data) if isinstance(data, dict) else data

    async def get_portfolio(self) -> Dict[str, Any]:
        """Fetch portfolio summary (holdings + positions aggregated)."""
        positions = await self.get_positions()
        holdings = await self.get_holdings()
        return {"positions": positions, "holdings": holdings}