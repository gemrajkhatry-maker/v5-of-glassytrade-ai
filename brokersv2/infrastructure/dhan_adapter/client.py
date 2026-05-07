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
from brokersv2.infrastructure.dhan_adapter.mapper import InstrumentMapper, BrokerInstrumentMapping
from brokersv2.infrastructure.rate_limiter.token_bucket import RateLimiter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from brokersv2.domain.instrument.models import CanonicalInstrument


logger = logging.getLogger(__name__)


@dataclass
class DhanConfig:
    """DhanHQ configuration."""
    client_id: str
    access_token: str
    base_url: str = "https://api.dhan.co"
    ws_url: str = "wss://api.dhan.co/ws"
    timeout: int = 30


class DhanHttpClient:
    """
    DhanHQ v2 HTTP client with rate limiting.
    
    Handles all REST API calls to DhanHQ.
    """
    
    def __init__(self, config: DhanConfig, rate_limiter: Optional[RateLimiter] = None):
        self.config = config
        self._rate_limiter = rate_limiter or RateLimiter()
        self._session: Optional[aiohttp.ClientSession] = None
        self._headers = {
            "access-token": config.access_token,
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
        # Wait for rate limit token
        await self._rate_limiter.wait_for_token(bucket)
        
        session = await self._get_session()
        url = f"{self.config.base_url}{endpoint}"
        
        async with session.request(method, url, headers=self._headers, **kwargs) as response:
            if response.status != 200:
                error_text = await response.text()
                logger.error(f"Dhan API error {response.status}: {error_text}")
                response.raise_for_status()
            return await response.json()
    
    async def get_quote(
        self,
        instrument: "CanonicalInstrument",
        mapper: InstrumentMapper,
    ) -> Quote:
        """Get quote for instrument."""
        mapping = mapper.canonical_to_broker_mapping(instrument)
        if not mapping:
            raise ValueError(f"No broker mapping for {instrument.symbol}")
        
        endpoint = f"/quotes/{mapping.security_id}"
        data = await self._request("GET", endpoint, bucket="quotes")
        
        return Quote(
            instrument=instrument,
            ltp=float(data.get("LTP", 0)),
            bid=float(data.get("bid", 0)),
            ask=float(data.get("ask", 0)),
            volume=int(data.get("volume", 0)),
            open=float(data.get("open", 0)),
            high=float(data.get("high", 0)),
            low=float(data.get("low", 0)),
            close=float(data.get("close", 0)),
            oi=int(data.get("OI", 0)) if data.get("OI") else None,
        )
    
    async def place_order(
        self,
        order: Order,
        mapper: InstrumentMapper,
    ) -> str:
        """Place order and return broker order ID."""
        mapping = mapper.canonical_to_broker_mapping(order.instrument)
        if not mapping:
            raise ValueError(f"No broker mapping for {order.instrument.symbol}")
        
        payload = {
            "security_id": mapping.security_id,
            "exchange_segment": mapping.exchange_segment,
            "transaction_type": order.side.value,
            "quantity": str(int(order.quantity)),
            "order_type": order.order_type.value,
            "product_type": "INTRADAY",
            "price": str(order.price) if order.price else "0",
        }
        
        if order.trigger_price:
            payload["trigger_price"] = str(order.trigger_price)
        
        data = await self._request("POST", "/orders", bucket="orders", json=payload)
        return data.get("order_id", "")
    
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
        mapping = mapper.canonical_to_broker_mapping(instrument) if mapper else None
        security_id = mapping.security_id if mapping else ""
        
        payload = {
            "security_id": security_id,
            "from_date": from_date,
            "to_date": to_date,
            "interval": interval,
        }
        
        data = await self._request("POST", "/historical", bucket="historical", json=payload)
        
        candles = []
        for row in data.get("data", []):
            candles.append(Candle(
                instrument=instrument,
                timeframe=interval,
                timestamp=row["date"],  # Would parse
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
            ))
        
        return candles