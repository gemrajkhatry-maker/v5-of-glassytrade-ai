"""AMT Analysis Handler — context analysis (no signals)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from app.domain.fabio_ai.services.amt_analyzer import AMTAnalyzer, IncrementalVolumeProfile
from app.domain.fabio_ai.services.footprint_analyzer import FootprintAnalyzer
from app.infrastructure.serialization.schemas import amt_result_to_dto, footprint_to_dto

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, OrderBook, AMTResult

logger = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))


def _filter_today_session(data: list) -> list:
    """Filter candles to today's trading session only.

    For options/intraday instruments, multi-day VP is meaningless
    because overnight premium decay creates huge price gaps.
    """
    if not data:
        return data
    today = datetime.now(_IST).strftime("%Y-%m-%d")
    today_data = [c for c in data if today in str(c.time)]
    # Fall back to all data only if ZERO candles from today (e.g. weekend/pre-market).
    # Even 1 today candle is better than using yesterday's prices for options —
    # overnight theta decay creates huge price gaps that distort VP.
    if len(today_data) == 0:
        # Pre-market: use only the most recent 20 candles to minimize stale data
        return data[-20:] if len(data) > 20 else data
    return today_data


class AMTHandler:
    """Handles AMT analysis and footprint generation (every tick)."""

    # Maximum number of candles kept in the incremental profile window.
    # 60 candles (~5h at 5m interval) keeps VP relevant for options
    # that can move 20%+ intraday, preventing stale POC from early session.
    _LOOKBACK: int = 60

    def __init__(self, session_only_vp: bool = True) -> None:
        self._amt_analyzer = AMTAnalyzer()
        self._footprint_analyzer = FootprintAnalyzer()
        self._inc_profile = IncrementalVolumeProfile()
        self._prev_data_len: int = 0
        self._session_only_vp = session_only_vp
        # Track current trading date (IST) to force VP rebuild on day boundary
        self._trading_date: str = datetime.now(_IST).strftime("%Y-%m-%d")

    def analyze(
        self,
        data: list[OHLC],
        order_book: OrderBook | None = None,
        prior_poc: float = 0.0,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
    ) -> tuple[AMTResult, dict, dict]:
        """Run AMT analysis and footprint generation.

        Returns:
            (amt_result, amt_dto, footprint_dto)
        """
        # Detect day boundary — force full VP rebuild when trading date changes
        current_date = datetime.now(_IST).strftime("%Y-%m-%d")
        if current_date != self._trading_date:
            logger.info("Trading day changed %s → %s, resetting VP", self._trading_date, current_date)
            self._inc_profile = IncrementalVolumeProfile()
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

        if data_grew_by > 1 or data_grew_by < 0 or (self._prev_data_len == 0 and data_len > 0):
            # Bulk load, data reset, or first call — full rebuild
            self._inc_profile = IncrementalVolumeProfile()
            for candle in recent_data:
                self._inc_profile.update(candle)
            if data_grew_by > 1:
                logger.info("VP full rebuild: %d candles (session_filtered=%d)", len(recent_data), vp_len)
        elif data_grew_by == 1 and recent_data:
            # New candle arrived
            new_candle = recent_data[-1]
            oldest = None
            if vp_len > self._LOOKBACK:
                oldest = vp_data[-(lookback + 1)]
            self._inc_profile.update(new_candle, oldest)
        # data_grew_by == 0: sub-candle update — skip VP rebuild (noise)

        self._prev_data_len = data_len

        amt_result = self._amt_analyzer.analyze(
            data, order_book, incremental_profile=self._inc_profile,
            prior_poc=prior_poc, prior_vah=prior_vah, prior_val=prior_val,
        )
        amt_dto = amt_result_to_dto(amt_result)

        fp_data = data[-50:] if len(data) >= 50 else data
        fp_result = self._footprint_analyzer.generate(fp_data)
        fp_dto = {k: footprint_to_dto(v) for k, v in fp_result.items()}

        return amt_result, amt_dto, fp_dto
