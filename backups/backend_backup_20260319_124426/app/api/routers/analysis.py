"""Analysis router — AMT, prediction, and footprint endpoints."""

from fastapi import APIRouter

from app.domain.fabio_ai.services.amt_analyzer import AMTAnalyzer
from app.domain.fabio_ai.services.prediction_engine import PredictionEngine
from app.domain.fabio_ai.services.footprint_analyzer import FootprintAnalyzer
from app.infrastructure.serialization.schemas import (
    AMTRequestDTO, PredictionRequestDTO, FootprintRequestDTO,
    dto_to_ohlc, dto_to_order_book, dto_to_weights,
    ohlc_to_dto, amt_result_to_dto, footprint_to_dto,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])

# Stateless domain services can be created per-request (they have no state)
_amt_analyzer = AMTAnalyzer()
_prediction_engine = PredictionEngine()
_footprint_analyzer = FootprintAnalyzer()


@router.post("/amt")
async def run_amt_analysis(req: AMTRequestDTO):
    data = [dto_to_ohlc(d) for d in req.data]
    ob = dto_to_order_book(req.order_book)
    result = _amt_analyzer.analyze(data, ob)
    return amt_result_to_dto(result)


@router.post("/predict")
async def run_prediction(req: PredictionRequestDTO):
    data = [dto_to_ohlc(d) for d in req.data]
    weights = dto_to_weights(req.weights)
    ob = dto_to_order_book(req.order_book)
    result = _prediction_engine.predict(data, weights, req.count, ob)

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


@router.post("/footprint")
async def run_footprint(req: FootprintRequestDTO):
    data = [dto_to_ohlc(d) for d in req.data]
    result = _footprint_analyzer.generate(data)
    return {k: footprint_to_dto(v) for k, v in result.items()}
