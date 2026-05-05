"""Dhan broker adapter for Indian markets - matches existing adapter pattern."""
from dataclasses import dataclass
from typing import Optional, Dict, Any
import asyncio
import httpx

from decimal import Decimal


class DhanAdapter:
    """Dhan broker adapter for Indian stock trading."""
    
    def __init__(self, client_id: str, access_token: str, testnet: bool = True):
        self._client_id = client_id
        self._access_token = access_token
        self._testnet = testnet
        self._base_url = "https://api.dhan.co"
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            headers={
                "access-token": access_token,
                "Content-Type": "application/json"
            },
            timeout=30.0
        )
    
    async def place_order(self, symbol: str, side: str, qty: float, price: float) -> dict:
        """Place order via Dhan API."""
        payload = {
            "tradingsymbol": symbol,
            "exchange": "NSE",
            "transactiontype": side,
            "quantity": int(qty),
            "ordertype": "MARKET" if price == 0 else "LIMIT",
            "producttype": "INTRADAY",
            "price": price
        }
        
        response = await self._client.post("/v2/orders", json=payload)
        response.raise_for_status()
        data = response.json()
        
        return {
            "order_id": data.get("orderId", f"{symbol}_{asyncio.get_event_loop().time()}"),
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": price,
            "status": data.get("status", "PENDING")
        }
    
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel order on Dhan."""
        try:
            response = await self._client.delete(f"/v2/orders/{order_id}")
            response.raise_for_status()
            return True
        except Exception:
            return False
    
    async def get_position(self, symbol: str) -> Optional[dict]:
        """Get position from Dhan."""
        try:
            response = await self._client.get("/v2/holdings")
            response.raise_for_status()
            holdings = response.json()
            for holding in holdings:
                if holding.get("tradingSymbol") == symbol:
                    return {
                        "symbol": symbol,
                        "quantity": Decimal(str(holding.get("netQty", 0))),
                        "avg_price": Decimal(str(holding.get("avgCostPrice", 0))),
                        "pnl": Decimal(str(holding.get("pnl", 0)))
                    }
            return None
        except Exception:
            return None
    
    async def close(self):
        """Close HTTP client."""
        await self._client.aclose()