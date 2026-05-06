"""Analysis endpoints for AMT, prediction, and footprint extraction."""
from __future__ import annotations

from app.domain.amt.service.amt_analyzer import AMTAnalyzer
from app.domain.amt.service.footprint_analyzer import FootprintAnalyzer
from app.domain.amt.service.prediction_engine import PredictionEngine
from app.domain.trading.model.value_objects import ModelWeights
from app.infrastructure.serialization.schemas import (
    AMTRequestDTO,
    FootprintRequestDTO,
    PredictionRequestDTO,
    amt_result_to_dto,
    dto_to_ohlc,
    dto_to_order_book,
    dto_to_weights,
    footprint_to_dto,
    ohlc_to_dto,
)

from fastapi import APIRouter

router = APIRouter(prefix="/analysis", tags=["analysis"])

_amt_analyzer = AMTAnalyzer()
_prediction_engine = PredictionEngine()
_footprint_analyzer = FootprintAnalyzer()


@router.post("/amt")
async def run_amt_analysis(req: AMTRequestDTO):
    data = [dto_to_ohlc(d) for d in req.data]
    _ = dto_to_order_book(req.orderBook) if getattr(req, "orderBook", None) else None
    result = _amt_analyzer.analyze(
        bars=[
            {
                "time": bar.time,
                "open": bar.open,
                "high": bar.high,
                "low": bar.low,
                "close": bar.close,
                "volume": bar.volume,
                "buyVolume": bar.taker_buy_volume,
                "sellVolume": max(bar.volume - bar.taker_buy_volume, 0),
                "vwap": bar.vwap,
                "takerBuyVolume": bar.taker_buy_volume,
                "delta": bar.delta,
            }
            for bar in data
        ],
        symbol="",
        prior_profile=None,
    )
    return amt_result_to_dto(result)


@router.post("/predict")
async def run_prediction(req: PredictionRequestDTO):
    data = [dto_to_ohlc(d) for d in req.data]
    _weights_payload = dto_to_weights(req.weights)
    weights = ModelWeights(
        trend=_weights_payload["trend"],
        momentum=_weights_payload["momentum"],
        delta=_weights_payload["delta"],
        order_book=_weights_payload["order_book"],
        volatility=_weights_payload["volatility"],
    )
    ob = dto_to_order_book(req.orderBook) if getattr(req, "orderBook", None) else None
    result = _prediction_engine.predict(data, weights, req.count, ob)
    payload = {
        "predictions": [ohlc_to_dto(p) for p in result.predictions],
    }
    if result.analysis is not None:
        payload["analysis"] = {
            "sentiment": result.analysis.sentiment,
            "confidence": result.analysis.confidence,
            "longTermTrend": result.analysis.long_term_trend,
            "volatilityScore": result.analysis.volatility_score,
            "projectedPrice": result.analysis.projected_price,
            "reasoning": list(result.analysis.reasoning),
            "factorBreakdown": {
                "trend": result.analysis.factor_breakdown.trend,
                "momentum": result.analysis.factor_breakdown.momentum,
                "delta": result.analysis.factor_breakdown.delta,
                "orderBook": result.analysis.factor_breakdown.order_book,
                "volatility": getattr(result.analysis.factor_breakdown, "volatility", 0.0),
            },
        }
    return payload


@router.post("/footprint")
async def run_footprint(req: FootprintRequestDTO):
    data = [dto_to_ohlc(d) for d in req.data]
    result = _footprint_analyzer.generate(data)
    return {k: footprint_to_dto(v) for k, v in result.items()}

