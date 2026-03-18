"""AMT Analysis Handler — context analysis (no signals)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING, Any

from app.domain.fabio_ai.services.amt_analyzer import AMTAnalyzer, IncrementalVolumeProfile
from app.domain.fabio_ai.services.footprint_analyzer import FootprintAnalyzer
from app.infrastructure.serialization.schemas import amt_result_to_dto, footprint_to_dto

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, OrderBook, AMTResult

logger = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))


def _filter_today_session(data: list) -> list:
    """Filter candles to build meaningful volume profile.
    
    For options: prefer today's session only (overnight theta decay distorts VP)
    For MCX commodities: use multi-day data (commodities don't have theta decay)
    
    With 90-day historical data now available from Dhan, we can build
    robust volume profiles even for MCX options.
    """
    if not data:
        return data
    today = datetime.now(_IST).strftime("%Y-%m-%d")
    today_data = [c for c in data if today in str(c.time)]
    
    # If we have enough today candles (>20 = ~2 hours at 5m), use session-only
    if len(today_data) > 20:
        return today_data
    
    # Not enough today candles — use recent data for meaningful VP
    # Use last 100 candles (~8 hours at 5m) for good profile
    logger.info("Only %d today candles — using last 100 for VP", len(today_data))
    return data[-100:] if len(data) > 100 else data


class AMTHandler:
    """Handles AMT analysis and footprint generation (every tick)."""

    # Maximum number of candles kept in the incremental profile window.
    # 1000 candles (~80h at 5m interval) ensures we capture the full
    # session structure and previous balance areas accurately.
    _LOOKBACK: int = 1000
    _DEV_LOOKBACK: int = 20  # Developing VA — adapts in ~100min at 5m interval

    def __init__(self, session_only_vp: bool = True) -> None:
        self._amt_analyzer = AMTAnalyzer()
        self._footprint_analyzer = FootprintAnalyzer()
        self._inc_profile = IncrementalVolumeProfile()
        self._dev_profile = IncrementalVolumeProfile()  # Short-lookback developing VA
        self._prev_data_len: int = 0
        self._session_only_vp = session_only_vp
        # Track current trading date (IST) to force VP rebuild on day boundary
        self._trading_date: str = datetime.now(_IST).strftime("%Y-%m-%d")
        # Cache profile arrays to avoid new list objects on sub-candle updates
        self._cached_profile: list | None = None
        self._cached_leg_profile: list | None = None

    def _to_float_ohlc(self, data: list[OHLC]) -> list[Any]:
        """Convert Decimal-based OHLC to float-based for high-speed AMT analysis."""
        from dataclasses import make_dataclass
        FloatOHLC = make_dataclass("FloatOHLC", [
            ("time", str), ("open", float), ("high", float), ("low", float),
            ("close", float), ("volume", float), ("vwap", float),
            ("taker_buy_volume", float), ("delta", float)
        ])
        return [
            FloatOHLC(
                time=str(c.time),
                open=float(c.open),
                high=float(c.high),
                low=float(c.low),
                close=float(c.close),
                volume=float(c.volume),
                vwap=float(c.vwap),
                taker_buy_volume=float(c.taker_buy_volume),
                delta=float(c.delta)
            ) for c in data
        ]

    def analyze(
        self,
        data: list[OHLC],
        order_book: OrderBook | None = None,
        prior_poc: float = 0.0,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
        cushion_tier: str = "Conservative",
        session_pnl: float = 0.0,
    ) -> tuple[AMTResult, dict, dict]:
        """Run AMT analysis and footprint generation.

        Returns:
            (amt_result, amt_dto, footprint_dto)
        """
        # Convert to float-based OHLC to prevent Decimal/float mismatch errors in analysis
        data = self._to_float_ohlc(data)
        # Detect day boundary — force full VP rebuild when trading date changes
        current_date = datetime.now(_IST).strftime("%Y-%m-%d")
        if current_date != self._trading_date:
            logger.info("Trading day changed %s → %s, resetting VP", self._trading_date, current_date)
            self._inc_profile = IncrementalVolumeProfile()
            self._dev_profile = IncrementalVolumeProfile()
            self._prev_data_len = 0
            self._trading_date = current_date

        # For intraday options, use only today's session candles for VP
        vp_data = _filter_today_session(data) if self._session_only_vp else data

        # Incrementally update the volume profile with the latest candle.
        lookback = min(len(vp_data), self._LOOKBACK)
        recent_data = vp_data[-lookback:]

        vp_len = len(vp_data)
        data_len = len(data)
        data_grew_by = data_len - self._prev_data_len

        # Developing VA: short lookback for fast adaptation
        dev_lookback = min(len(vp_data), self._DEV_LOOKBACK)
        dev_recent = vp_data[-dev_lookback:]

        if data_grew_by > 1 or data_grew_by < 0 or (self._prev_data_len == 0 and data_len > 0):
            # Bulk load, data reset, or first call — full rebuild
            self._inc_profile = IncrementalVolumeProfile()
            for candle in recent_data:
                self._inc_profile.update(candle)
            self._dev_profile = IncrementalVolumeProfile()
            for candle in dev_recent:
                self._dev_profile.update(candle)
            if data_grew_by > 1:
                logger.info("VP full rebuild: %d candles (session_filtered=%d)", len(recent_data), vp_len)
        elif data_grew_by == 1 and recent_data:
            # New candle arrived
            new_candle = recent_data[-1]
            oldest = None
            if vp_len > self._LOOKBACK:
                oldest = vp_data[-(lookback + 1)]
            self._inc_profile.update(new_candle, oldest)
            # Developing VP: shorter window
            dev_oldest = None
            if vp_len > self._DEV_LOOKBACK:
                dev_oldest = vp_data[-(dev_lookback + 1)]
            self._dev_profile.update(new_candle, dev_oldest)
        # data_grew_by == 0: sub-candle update — skip VP rebuild (noise)

        is_new_candle = data_grew_by != 0
        self._prev_data_len = data_len

        amt_result = self._amt_analyzer.analyze(
            data, order_book, incremental_profile=self._inc_profile,
            prior_poc=prior_poc, prior_vah=prior_vah, prior_val=prior_val,
            developing_profile=self._dev_profile,
            cushion_tier=cushion_tier, session_pnl=session_pnl,
        )

        amt_dto = amt_result_to_dto(amt_result)

        # On sub-candle updates, reuse cached profile arrays to prevent
        # unnecessary delta diffs and frontend redraws (profiles don't change
        # until a new candle arrives).
        if is_new_candle:
            self._cached_profile = amt_dto.get("profile")
            self._cached_leg_profile = amt_dto.get("legProfile")
        elif self._cached_profile is not None:
            amt_dto["profile"] = self._cached_profile
            amt_dto["legProfile"] = self._cached_leg_profile

        fp_data = data[-50:] if len(data) >= 50 else data
        fp_result = self._footprint_analyzer.generate(fp_data)
        fp_dto = {k: footprint_to_dto(v) for k, v in fp_result.items()}

        return amt_result, amt_dto, fp_dto
