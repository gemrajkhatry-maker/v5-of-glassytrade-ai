"""Market analysis REST endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from app.domain.amt.service.volume_profile import build_volume_profile, calculate_vwap
from app.domain.amt.service.orderflow_detectors import detect_absorptions
from app.domain.amt.service.signal_generator import generate_triple_a_signal
from app.infrastructure.serialization import AMTAnalysisDTO, OHLCDataDTO

router = APIRouter()


@router.post("/analyze")
async def analyze_market(data: list[OHLCDataDTO]):
    bars = [
        {
            "open": d.open,
            "high": d.high,
            "low": d.low,
            "close": d.close,
            "volume": d.volume,
            "buyVolume": float(d.takerBuyVolume or 0.0) or d.volume / 2,
            "sellVolume": d.volume - (float(d.takerBuyVolume or 0.0) or d.volume / 2),
            "bar_index": i,
        }
        for i, d in enumerate(data)
    ]

    vp = build_volume_profile(bars, bucket_size=50.0)
    vwap, _, _, _, _ = calculate_vwap(bars)
    absorptions = detect_absorptions(bars)
    signal = generate_triple_a_signal(bars, absorptions, vp, vwap)

    return AMTAnalysisDTO(
        marketState="BULLISH" if signal.type == "LONG" else "BEARISH",
        poc=vp.poc,
        valueAreaHigh=vp.vah,
        valueAreaLow=vp.val,
        signal=None if signal.type == "NO_TRADE" else signal,
    )
