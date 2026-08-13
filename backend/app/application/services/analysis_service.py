"""Application services for analysis endpoints."""

from __future__ import annotations

from quant.amt.analyzer import AMTAnalyzer
from quant.amt.orderflow.footprint import FootprintAnalyzer
from app.infrastructure.serialization.schemas import (
    dto_to_ohlc,
    dto_to_order_book,
)


class AnalysisService:
    """Application-level orchestration for analysis request handling."""

    def __init__(
        self,
        amt_analyzer: AMTAnalyzer | None = None,
        footprint_analyzer: FootprintAnalyzer | None = None,
    ) -> None:
        self._amt_analyzer = amt_analyzer or AMTAnalyzer()
        self._footprint_analyzer = footprint_analyzer or FootprintAnalyzer()

    def run_amt(self, req):
        data = [dto_to_ohlc(d) for d in req.data]
        ob = dto_to_order_book(req.order_book)
        return self._amt_analyzer.analyze(data, ob)

    def run_footprint(self, req):
        data = [dto_to_ohlc(d) for d in req.data]
        return self._footprint_analyzer.generate(data)
