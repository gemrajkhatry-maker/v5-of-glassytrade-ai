"""
Market Data Service - Quote and LTP operations.
"""

from typing import Dict, List, Optional

from shared.entities.models import Instrument, Quote
from brokers.broker.types import Exchange
from brokers.broker.dhan.domain import DhanNetworkError, MARKETFEED_QUOTE, MARKETFEED_LTP
from brokers.broker.dhan.domain.segment_mapping import exchange_to_segment_name
from ..converters import DhanConverter
from brokers.broker.logging import get_logger
from .base import BaseDhanService

logger = get_logger("dhan.services.market_data")


class MarketDataService(BaseDhanService):
    """Handles quote and LTP market data operations."""

    async def get_quote_async(self, instrument: Instrument) -> Quote:
        """Get current quote for instrument."""
        await self._ensure_initialized()
        # Rate limit is applied inside get_quotes_by_segment_async — don't double-acquire

        try:
            security_id = await self._resolve_security_id(instrument)
            segment = exchange_to_segment_name(instrument.exchange)
            sid_to_inst = {security_id: instrument}
            result = await self.get_quotes_by_segment_async(segment, sid_to_inst)
            quote = result.get(instrument)
            if quote is None:
                raise DhanNetworkError(
                    message="Quote response missing for instrument",
                    code="DH-4002",
                    details={"symbol": instrument.symbol, "security_id": security_id},
                )
            return quote
        except Exception as e:
            if hasattr(e, 'code'):
                raise
            self._handle_error(e, f"get_quote({instrument.symbol})")

    async def get_quotes_batch_async(
        self, instruments: List[Instrument]
    ) -> Dict[Instrument, Quote]:
        """Get quotes for multiple instruments."""
        await self._ensure_initialized()

        if not instruments:
            return {}

        _, instrument_map = await self._resolve_instruments_parallel(instruments)

        by_segment: Dict[str, Dict[str, Instrument]] = {}
        for sid, inst in instrument_map.items():
            seg = exchange_to_segment_name(inst.exchange)
            by_segment.setdefault(seg, {})[sid] = inst

        result: Dict[Instrument, Quote] = {}
        for segment, sid_to_inst in by_segment.items():
            try:
                batch_quotes = await self.get_quotes_by_segment_async(segment, sid_to_inst)
                result.update(batch_quotes)
            except Exception as e:
                logger.warning(f"Batch quote failed for segment {segment}: {e}")

        return result

    async def get_quotes_by_segment_async(
        self, segment: str, sid_to_instrument: Dict[str, Instrument]
    ) -> Dict[Instrument, Quote]:
        """Fetch quotes for instruments in one segment via Dhan POST /v2/marketfeed/quote."""
        if not sid_to_instrument:
            return {}

        await self._apply_rate_limit("market_data")
        sids = [int(sid) for sid in sid_to_instrument.keys() if str(sid).strip()]
        if not sids:
            return {}

        payload: Dict[str, List[int]] = {segment: sids}
        response = await self._execute_with_cb(
            lambda: self._http_client.post(endpoint=MARKETFEED_QUOTE, json=payload)
        )

        if response.status_code != 200:
            raise DhanNetworkError(
                message=f"Batch quote failed with status {response.status_code}",
                code=str(response.status_code),
                details=response.data,
            )

        data = response.data.get("data", {}) if isinstance(response.data, dict) else {}
        seg_data = data.get(segment, {}) if isinstance(data, dict) else {}
        if not isinstance(seg_data, dict):
            return {}

        result: Dict[Instrument, Quote] = {}
        for sid_str, inst in sid_to_instrument.items():
            raw = seg_data.get(str(sid_str), seg_data.get(sid_str, {}))
            if not isinstance(raw, dict):
                continue
            ohlc = raw.get("ohlc") or {}
            depth = raw.get("depth") or {}
            buy_levels = depth.get("buy") if isinstance(depth, dict) else []
            sell_levels = depth.get("sell") if isinstance(depth, dict) else []
            bid = float(buy_levels[0].get("price", 0)) if buy_levels else 0.0
            ask = float(sell_levels[0].get("price", 0)) if sell_levels else 0.0
            quote_data = {
                "tradingSymbol": inst.symbol,
                "LTP": raw.get("last_price", 0),
                "ltp": raw.get("last_price", 0),
                "open": ohlc.get("open", 0),
                "high": ohlc.get("high", 0),
                "low": ohlc.get("low", 0),
                "close": ohlc.get("close", 0),
                "volume": raw.get("volume", 0),
                "bid": bid,
                "ask": ask,
                "oi": raw.get("oi"),
                "OI": raw.get("oi"),
                "bid_depth": buy_levels,
                "ask_depth": sell_levels,
            }
            try:
                result[inst] = DhanConverter.quote_from_api_response(
                    quote_data, sid_str, inst.exchange
                )
            except Exception as e:
                logger.warning(f"Failed to convert quote for {inst.symbol}: {e}")

        return result

    async def get_ltp_batch_async(
        self, symbols: List[str], exchange: Optional[Exchange] = None
    ) -> Dict[str, float]:
        """Get LTP for multiple symbols using the lightweight batch LTP endpoint."""
        if not symbols:
            return {}

        await self._ensure_initialized()
        ex = exchange or Exchange.NSE

        instruments = [Instrument(symbol=sym, exchange=ex) for sym in symbols]
        _, instrument_map = await self._resolve_instruments_parallel(instruments)

        by_segment: Dict[str, Dict[str, str]] = {}
        for sid, inst in instrument_map.items():
            seg = exchange_to_segment_name(inst.exchange)
            by_segment.setdefault(seg, {})[sid] = inst.symbol

        result: Dict[str, float] = {}
        for segment, sid_to_sym in by_segment.items():
            await self._apply_rate_limit("market_data")
            sids = [int(s) for s in sid_to_sym.keys()]
            payload = {segment: sids}
            try:
                response = await self._execute_with_cb(
                    lambda: self._http_client.post(endpoint=MARKETFEED_LTP, json=payload)
                )
                if response.status_code == 200:
                    data = response.data.get("data", {}) if isinstance(response.data, dict) else {}
                    seg_data = data.get(segment, {}) if isinstance(data, dict) else {}
                    for sid_str, sym in sid_to_sym.items():
                        raw = seg_data.get(str(sid_str), seg_data.get(sid_str, {}))
                        if isinstance(raw, dict):
                            result[sym] = float(raw.get("last_price", 0))
            except Exception as e:
                logger.warning(f"LTP batch failed for segment {segment}: {e}")

        return result
