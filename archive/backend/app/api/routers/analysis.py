"""Analysis router — AMT, prediction, and footprint endpoints."""

from fastapi import APIRouter

from app.application.services.analysis_service import AnalysisService
from app.infrastructure.serialization.schemas import (
    AMTRequestDTO,
    PredictionRequestDTO,
    FootprintRequestDTO,
    amt_result_to_dto,
    footprint_to_dto,
)

router = APIRouter(prefix="/analysis", tags=["analysis"])

_analysis_service = AnalysisService()


@router.post("/amt")
async def run_amt_analysis(req: AMTRequestDTO):
    result = _analysis_service.run_amt(req)
    return amt_result_to_dto(result)


@router.post("/predict")
async def run_prediction(req: PredictionRequestDTO):
    result = _analysis_service.run_prediction(req)
    return _analysis_service.build_prediction_response(result)


@router.post("/footprint")
async def run_footprint(req: FootprintRequestDTO):
    result = _analysis_service.run_footprint(req)
    return {k: footprint_to_dto(v) for k, v in result.items()}
