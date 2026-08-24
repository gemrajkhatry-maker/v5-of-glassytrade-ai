"""Application services for analysis endpoints."""

from __future__ import annotations

from quant.amt.analyzer import AMTAnalyzer
from quant.inference.prediction import PredictionEngine
from quant.amt.orderflow.footprint import FootprintAnalyzer
from app.infrastructure.serialization.schemas import (
    dto_to_ohlc,
    dto_to_order_book,
    dto_to_weights,
    ohlc_to_dto,
)


class AnalysisService:
    """Application-level orchestration for analysis request handling."""

    def __init__(
        self,
        amt_analyzer: AMTAnalyzer | None = None,
        prediction_engine: PredictionEngine | None = None,
        footprint_analyzer: FootprintAnalyzer | None = None,
    ) -> None:
        self._amt_analyzer = amt_analyzer or AMTAnalyzer()
        self._prediction_engine = prediction_engine or PredictionEngine()
        self._footprint_analyzer = footprint_analyzer or FootprintAnalyzer()

    def run_amt(self, req):
        data = [dto_to_ohlc(d) for d in req.data]
        ob = dto_to_order_book(req.order_book)
        return self._amt_analyzer.analyze(data, ob)

    def run_prediction(self, req):
        data = [dto_to_ohlc(d) for d in req.data]
        weights = dto_to_weights(req.weights)
        ob = dto_to_order_book(req.order_book)
        return self._prediction_engine.predict(data, weights, req.count, ob)

    def build_prediction_response(self, result):
        resp: dict = {
            "predictions": [ohlc_to_dto(p) for p in result.predictions],
        }
        if result.analysis:
            resp["analysis"] = {
                "sentiment": result.analysis.sentiment,
                "confidence": result.analysis.confidence,
                "longTermTrend": result.analysis.long_term_trend,
                "volatilityScore": result.analysis.volatility_score,
                "quantScore": result.analysis.quant_score,
                "projectedPrice": result.analysis.projected_price,
                "reasoning": list(result.analysis.reasoning),
                "factorBreakdown": {
                    "trend": result.analysis.factor_breakdown.trend,
                    "momentum": result.analysis.factor_breakdown.momentum,
                    "delta": result.analysis.factor_breakdown.delta,
                    "orderBook": result.analysis.factor_breakdown.order_book,
                },
            }
        return resp

    def run_footprint(self, req):
        data = [dto_to_ohlc(d) for d in req.data]
        return self._footprint_analyzer.generate(data)
