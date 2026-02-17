"""AMT Analysis Handler — context analysis (no signals)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.fabio_ai.services.amt_analyzer import AMTAnalyzer, IncrementalVolumeProfile
from app.domain.fabio_ai.services.footprint_analyzer import FootprintAnalyzer
from app.infrastructure.serialization.schemas import amt_result_to_dto, footprint_to_dto

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, OrderBook, AMTResult

logger = logging.getLogger(__name__)


class AMTHandler:
    """Handles AMT analysis and footprint generation (every tick)."""

    # Maximum number of candles kept in the incremental profile window.
    _LOOKBACK: int = 200

    def __init__(self) -> None:
        self._amt_analyzer = AMTAnalyzer()
        self._footprint_analyzer = FootprintAnalyzer()
        self._inc_profile = IncrementalVolumeProfile()
        self._prev_data_len: int = 0

    def analyze(
        self,
        data: list[OHLC],
        order_book: OrderBook | None = None,
    ) -> tuple[AMTResult, dict, dict]:
        """Run AMT analysis and footprint generation.

        Returns:
            (amt_result, amt_dto, footprint_dto)
        """
        # Incrementally update the volume profile with the latest candle.
        lookback = min(len(data), self._LOOKBACK)
        recent_data = data[-lookback:]

        data_len = len(data)
        data_grew_by = data_len - self._prev_data_len

        if data_grew_by > 1 or data_grew_by < 0 or (self._prev_data_len == 0 and data_len > 0):
            # Bulk load, data reset, or first call — full rebuild
            self._inc_profile = IncrementalVolumeProfile()
            for candle in recent_data:
                self._inc_profile.update(candle)
            if data_grew_by > 1:
                logger.info("VP full rebuild: %d candles (bulk load)", len(recent_data))
        elif data_grew_by == 1 and recent_data:
            # New candle arrived
            new_candle = recent_data[-1]
            oldest = None
            if data_len > self._LOOKBACK and self._prev_data_len >= self._LOOKBACK:
                oldest = data[-(lookback + 1)]
            self._inc_profile.update(new_candle, oldest)
        # data_grew_by == 0: sub-candle update — skip VP rebuild (noise)

        self._prev_data_len = len(data)

        amt_result = self._amt_analyzer.analyze(
            data, order_book, incremental_profile=self._inc_profile,
        )
        amt_dto = amt_result_to_dto(amt_result)

        fp_data = data[-50:] if len(data) >= 50 else data
        fp_result = self._footprint_analyzer.generate(fp_data)
        fp_dto = {k: footprint_to_dto(v) for k, v in fp_result.items()}

        return amt_result, amt_dto, fp_dto
