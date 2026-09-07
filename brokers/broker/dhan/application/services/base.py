"""
Base Dhan Service - Shared dependencies and helpers for all Dhan services.
"""

import asyncio
from typing import Dict, List, Optional, Tuple

from shared.entities.models import Instrument
from brokers.broker.types import Exchange

from brokers.broker.dhan.ports import (
    IHttpClient,
    ISymbolMapper,
    IRateLimiter,
    ICircuitBreaker,
)
from brokers.broker.dhan.domain import (
    DhanInstrument,
    ExchangeSegment,
    DhanError,
    DhanSymbolNotFoundError,
)
from brokers.broker.dhan.domain.constants import INDEX_UNDERLYINGS
from brokers.broker.dhan.domain.segment_mapping import exchange_to_segment_name

from brokers.broker.logging import get_logger
from ..config import DhanConfig

logger = get_logger("dhan.services.base")


class BaseDhanService:
    """
    Base class for all Dhan service modules.

    Holds shared dependencies injected by DhanBroker and provides
    common helper methods used across services.
    """

    # Known index underlyings that live in IDX_I segment (single source of truth in domain.constants)
    _INDEX_UNDERLYINGS = INDEX_UNDERLYINGS

    def __init__(
        self,
        config: DhanConfig,
        http_client: Optional[IHttpClient],
        symbol_mapper: Optional[ISymbolMapper],
        rate_limiter: Optional[IRateLimiter],
        circuit_breaker: Optional[ICircuitBreaker],
        option_symbol_cache: Dict[str, str],
        ensure_initialized,
    ) -> None:
        self._config = config
        self._http_client = http_client
        self._symbol_mapper = symbol_mapper
        self._rate_limiter = rate_limiter
        self._circuit_breaker = circuit_breaker
        self._option_symbol_cache = option_symbol_cache
        self._ensure_initialized = ensure_initialized

    async def _apply_rate_limit(self, category: str = "default") -> None:
        """Apply rate limiting if configured."""
        if self._rate_limiter:
            await self._rate_limiter.acquire(category)

    async def _execute_with_cb(self, operation):
        """
        Execute an async HTTP operation through the circuit breaker if configured.
        Falls through directly when no circuit breaker is set.

        Usage:
            response = await self._execute_with_cb(
                lambda: self._http_client.post(endpoint=..., json=...)
            )
        """
        if self._circuit_breaker:
            return await self._circuit_breaker.execute(operation)
        return await operation()

    async def _resolve_security_id(self, instrument: Instrument) -> str:
        """
        Resolve security ID for an instrument.

        Resolution order:
        1. Pre-set security_id on the instrument
        2. Option symbol cache
        3. Symbol mapper
        """
        if instrument.security_id:
            return instrument.security_id

        cached_sid = self._option_symbol_cache.get(instrument.symbol)
        if cached_sid:
            return cached_sid

        if self._symbol_mapper:
            segment = exchange_to_segment_name(instrument.exchange)
            exchange_segment = ExchangeSegment.from_name(segment)

            if instrument.symbol.upper() in self._INDEX_UNDERLYINGS:
                exchange_segment = ExchangeSegment.IDX_I

            if exchange_segment == ExchangeSegment.MCX:
                futures_inst = await self._symbol_mapper.get_nearest_futures_contract(
                    instrument.symbol, exchange_segment
                )
                if futures_inst:
                    return futures_inst.security_id

            security_id = await self._symbol_mapper.get_security_id(
                instrument.symbol, exchange_segment
            )
            if security_id:
                return security_id

        raise DhanSymbolNotFoundError(
            message=f"Cannot resolve security_id for {instrument.symbol}",
            details={
                "symbol": instrument.symbol,
                "exchange": instrument.exchange.value,
            },
        )

    async def _resolve_instruments_parallel(
        self, instruments: List[Instrument]
    ) -> Tuple[List[str], Dict[str, Instrument]]:
        """Resolve security IDs for multiple instruments in parallel."""
        async def _resolve_one(inst: Instrument):
            try:
                sid = await self._resolve_security_id(inst)
                return (inst, sid, None)
            except Exception as e:
                return (inst, None, e)

        resolved = await asyncio.gather(
            *[_resolve_one(inst) for inst in instruments]
        )

        security_ids: List[str] = []
        instrument_map: Dict[str, Instrument] = {}
        for inst, sid, err in resolved:
            if err or not sid:
                logger.warning(f"Failed to resolve {inst.symbol}: {err}")
            elif sid in instrument_map:
                logger.warning(
                    "Duplicate security_id %s: both %r and %r resolve to it — "
                    "keeping %r, dropping %r. This usually means a bare underlying "
                    "root (e.g. 'CRUDEOIL') was subscribed alongside its futures "
                    "contract and would silently hijack its tick packets.",
                    sid,
                    instrument_map[sid].symbol,
                    inst.symbol,
                    instrument_map[sid].symbol,
                    inst.symbol,
                )
            else:
                security_ids.append(sid)
                instrument_map[sid] = inst

        return security_ids, instrument_map

    def _handle_error(self, error: Exception, context: str) -> None:
        """Handle and map errors to domain errors."""
        if isinstance(error, DhanError):
            raise error

        error_message = f"{context} failed: {error}"
        logger.error(error_message)

        raise DhanError(
            message=error_message,
            code="UNKNOWN_ERROR",
            details={"context": context, "error": str(error)},
        )
