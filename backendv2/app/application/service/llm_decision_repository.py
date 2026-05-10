"""Repository for persisting LLM decisions.

Extracted from LLMEntryHandler. Encapsulates mapping from domain objects
to storage format for LLM decisions.
"""
from __future__ import annotations

from typing import Any

from app.domain.fabio_ai.model.llm_decision import LLMDecision
from app.domain.shared.port import IStorage
from app.domain.trading.model.value_objects import AMTResult, OHLC


class LLMDecisionRepository:
    """Handles persistence of LLMDecision objects via IStorage."""

    def __init__(self, storage: IStorage) -> None:
        self._storage = storage

    def save(
        self,
        symbol: str,
        decision: LLMDecision,
        amt_result: AMTResult,
        candles: list[OHLC],
    ) -> None:
        """Save LLM decision to storage.

        Records symbol, direction, confidence, rationale, prompt, raw output,
        market state, aggression, tick trace id, price (last candle close),
        volume profile levels (vah, val, poc), delta, volume, and profile shape.
        """
        last_candle = candles[-1] if candles else None
        ltp = float(last_candle.close) if last_candle is not None else 0.0
        try:
            self._storage.save_llm_decision({
                "symbol": symbol,
                "direction": decision.direction,
                "confidence": decision.confidence,
                "rationale": decision.rationale,
                "input_prompt": decision.input_prompt,
                "raw_output": decision.raw_output,
                "market_state": decision.market_state,
                "aggression": str(getattr(amt_result, "aggression", 0.0)),
                "tick_trace_id": decision.tick_trace_id,
                "price": ltp,
                "vah": float(getattr(amt_result, "value_area_high", 0.0)),
                "val": float(getattr(amt_result, "value_area_low", 0.0)),
                "poc": float(getattr(amt_result, "poc", 0.0)),
                "delta": float(getattr(last_candle, "delta", 0.0)) if last_candle is not None else 0.0,
                "volume": float(getattr(last_candle, "volume", 0.0)) if last_candle is not None else 0.0,
                "profile_shape": str(getattr(amt_result, "profile_shape", "")),
                "extra": {},
            })
        except Exception:
            # Logging is handled by the caller; repository does not log.
            raise
