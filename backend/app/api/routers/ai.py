"""AI command router — proxies natural language commands to Gemini."""

from fastapi import APIRouter, Depends

from app.api.dependencies import get_ai_model
from app.domain.ports.ai_model import AIModelPort
from app.infrastructure.serialization.schemas import CommandRequestDTO

router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/command")
async def ai_command(
    req: CommandRequestDTO,
    ai_model: AIModelPort = Depends(get_ai_model),
):
    result = await ai_model.process_command(req.prompt, req.current_config)
    return {
        "message": result.message,
        "action": result.action,
        "configUpdates": result.config_updates,
    }


from pydantic import BaseModel
from typing import Dict, Any, Optional

class MarketAnalysisRequest(BaseModel):
    ltp: float
    delta: Optional[float] = 0.0
    volume: Optional[float] = 0.0
    context: Optional[str] = "Neutral"
    key_level: Optional[str] = None
    aggression: Optional[str] = None

from app.api.dependencies import get_gen_ai_service
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService

@router.post("/analyze")
async def analyze_market(
    req: MarketAnalysisRequest,
    service: GenerativeAIService = Depends(get_gen_ai_service),
):
    """
    Analyzes market data using the fine-tuned Nanbeige model (Fabio Logic).
    """
    # Convert Pydantic model to dict for service compatibility
    market_data = req.dict()
    analysis = service.analyze_market(market_data)
    
    return {
        "direction": analysis["direction"],
        "rationale": analysis["rationale"],
        "raw_output": analysis.get("raw_output", "")
    }
