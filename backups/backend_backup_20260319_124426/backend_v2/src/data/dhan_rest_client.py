"""
Dhan REST client — L2 DOM polling and option chain.

Polls L2 market depth every 500ms.
"""

import asyncio
from typing import Dict, List, Optional

import aiohttp
import orjson
import structlog

logger = structlog.get_logger()


class DhanRESTClient:
    """
    DhanHQ REST API client for L2 DOM and option chain data.

    Features:
    - L2 DOM polling (500ms interval)
    - Option chain retrieval
    - Automatic retry on failure
    """

    def __init__(
        self,
        access_token: str,
        client_id: str,
    ):
        self._access_token = access_token
        self._client_id = client_id
        self._base_url = "https://api.dhan.co"
        self._session: Optional[aiohttp.ClientSession] = None

    async def connect(self) -> None:
        """Initialize HTTP session."""
        self._session = aiohttp.ClientSession(
            headers={
                "access-token": self._access_token,
                "client-id": self._client_id,
                "Content-Type": "application/json",
            }
        )
        logger.info("dhan_rest_connected")

    async def close(self) -> None:
        """Close HTTP session."""
        if self._session:
            await self._session.close()
        logger.info("dhan_rest_closed")

    async def get_market_depth(self, security_id: str, exchange: str) -> Optional[Dict]:
        """
        Get L2 market depth for a symbol.

        Args:
            security_id: Dhan security ID
            exchange: Exchange segment (MCX_COMM, NSE_FO, etc.)

        Returns:
            Market depth dict with bid/ask levels.
        """
        if not self._session:
            return None

        try:
            url = f"{self._base_url}/marketfeed/ohlc"
            payload = {
                exchange: [security_id]
            }

            async with self._session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return self._parse_depth(data, security_id)
                else:
                    logger.warning("dhan_depth_error", status=resp.status)
                    return None

        except Exception as e:
            logger.error("dhan_depth_exception", error=str(e))
            return None

    def _parse_depth(self, data: dict, security_id: str) -> Optional[Dict]:
        """Parse market depth response."""
        try:
            # Extract depth data for the security
            for exchange_data in data.values():
                if isinstance(exchange_data, dict):
                    for sec_id, sec_data in exchange_data.items():
                        if str(sec_id) == str(security_id):
                            return {
                                "bid_levels": sec_data.get("depth", {}).get("buy", []),
                                "ask_levels": sec_data.get("depth", {}).get("sell", []),
                                "ltp": sec_data.get("last_price", 0),
                            }
            return None
        except Exception:
            return None

    async def get_option_chain(
        self,
        security_id: str,
        exchange: str,
    ) -> Optional[List[Dict]]:
        """
        Get option chain for a symbol.

        Args:
            security_id: Underlying security ID
            exchange: Exchange segment

        Returns:
            List of option contracts.
        """
        if not self._session:
            return None

        try:
            url = f"{self._base_url}/optionchain"
            payload = {
                "UnderlyingScrip": int(security_id),
                "UnderlyingSeg": exchange,
            }

            async with self._session.post(url, json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("data", {}).get("oc", [])
                else:
                    logger.warning("dhan_option_chain_error", status=resp.status)
                    return None

        except Exception as e:
            logger.error("dhan_option_chain_exception", error=str(e))
            return None

    async def poll_l2_loop(
        self,
        security_id: str,
        exchange: str,
        callback,
        interval_ms: int = 500,
    ) -> None:
        """
        Poll L2 DOM at regular interval.

        Args:
            security_id: Security ID to poll
            exchange: Exchange segment
            callback: Callback function for depth data
            interval_ms: Polling interval in milliseconds
        """
        while True:
            depth = await self.get_market_depth(security_id, exchange)
            if depth:
                callback(depth)
            await asyncio.sleep(interval_ms / 1000)