"""AI analysis router — market analysis via fine-tuned LLM."""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.api.dependencies import get_gen_ai_service, get_storage
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
from app.infrastructure.storage.database import SQLiteStorageAdapter

router = APIRouter(prefix="/ai", tags=["ai"])


class MarketAnalysisRequest(BaseModel):
    ltp: float
    delta: Optional[float] = 0.0
    volume: Optional[float] = 0.0
    context: Optional[str] = "Neutral"
    key_level: Optional[str] = None
    aggression: Optional[str] = None


@router.post("/analyze")
async def analyze_market(
    req: MarketAnalysisRequest,
    service: GenerativeAIService = Depends(get_gen_ai_service),
):
    """Analyzes market data using the fine-tuned Nanbeige model (Fabio Logic)."""
    market_data = req.dict()
    analysis = service.analyze_market(market_data)

    return {
        "direction": analysis["direction"],
        "rationale": analysis["rationale"],
        "raw_output": analysis.get("raw_output", ""),
    }


@router.get("/history")
async def get_decision_history(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    storage: SQLiteStorageAdapter = Depends(get_storage),
):
    """Returns persisted LLM decision history from SQLite."""
    rows = storage.query_llm_decisions(start=start, end=end)
    return {"decisions": rows}
