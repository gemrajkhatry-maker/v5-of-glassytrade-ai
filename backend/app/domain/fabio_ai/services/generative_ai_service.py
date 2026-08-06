import hashlib
import logging
from collections import OrderedDict
from typing import Dict, Any

from app.domain.ports.llm_inference import ILLMInference
from app.domain.fabio_ai.services.prompt_builder import (
    build_entry_prompt,
    parse_entry_response,
)

logger = logging.getLogger(__name__)

# Default instruction — used when no exchange-specific instruction is injected
_DEFAULT_INSTRUCTION = (
    "You are READING the auction using Fabio Valentini's AMT methodology. "
    "You are NOT predicting — you are interpreting market structure, order flow, "
    "and institutional behavior. Consider ALL context provided: session phase, "
    "gate warnings, market state, volume bubbles, stacked imbalances, CVD slope, "
    "profile shape, and VWAP bias. If the story is clear and "
    "elements align, state your CONVICTION and direction. If you don't see a "
    "clear setup or if gate warnings are significant, STAY FLAT.\n"
    "DECISION HIERARCHY:\n"
    "1. AGGRESSION (CVD/OFI/Delta) - What the market IS doing (Decisive)\n"
    "2. STRUCTURE (Mode/IB/Location) - WHERE it is doing it (Contextual)\n"
    "3. QUANT (Probability) - Statistical edge (Confirming)\n"
    "4. TIMING (VWAP/Velocity) - Execution precision\n"
    "AMT RULES: 1) NO counter-flow trades (avoid fading strong CVD). "
    "2) Entries MUST be at structural boundaries (VAH/VAL/LVN). "
    "3) Cap confidence at 0.85 (HIGH) if P > 0.7 and Structure aligns. "
    "4) If P ~ 0.5, cap confidence at MEDIUM even with strong structure."
)


class GenerativeAIService:
    """Fabio Logic LLM service — entry decisions ONLY.

    Runtime contract:
      - Prompt input: natural-language AMT/flow narrative from build_entry_prompt()
      - Canonical output: single JSON object with direction/rationale/confidence/market_state
      - Legacy structured "Market State / Logic / Trigger" parsing remains as fallback

    This keeps runtime behavior aligned to one paper-trading contract even if
    older fine-tuning artifacts still exist in the repository.
    """

    _CACHE_SIZE = 8

    def __init__(self, llm_adapter: ILLMInference, instruction: str = ""):
        self.llm_adapter = llm_adapter
        self._instruction = instruction or _DEFAULT_INSTRUCTION
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_ready(self) -> bool:
        """Check if the underlying LLM adapter is ready for inference."""
        return self.llm_adapter.is_ready()

    def runtime_state(self) -> dict[str, str | None]:
        """Expose adapter runtime state for readiness and diagnostics."""
        if hasattr(self.llm_adapter, "runtime_state"):
            return self.llm_adapter.runtime_state()  # type: ignore[attr-defined]
        return {"state": "UNKNOWN", "reason": "runtime_state not implemented"}

    def analyze_market(self, market_data: Dict[str, Any]) -> Dict[str, Any]:
        """Analyze current market data for an *entry* decision.

        Returns
        -------
        dict with keys:
            direction : "LONG" | "SHORT" | "FLAT"
            rationale : full model output text
            raw_output, input_prompt, market_state, aggression
        """
        prompt_input = build_entry_prompt(market_data)

        # Check cache (avoids redundant inference for identical market state)
        cache_key = hashlib.md5(prompt_input.encode()).hexdigest()
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

        try:
            raw_response = self.llm_adapter.predict(self._instruction, prompt_input)
            # Fix-NoneType: Guard against None from LLM adapter
            if raw_response is None:
                logger.warning("LLM adapter returned None — returning FLAT")
                parsed = {
                    "direction": "FLAT",
                    "rationale": "LLM returned None",
                    "confidence": "High",
                }
            else:
                parsed = parse_entry_response(raw_response)
            parsed["input_prompt"] = prompt_input
            parsed["market_state"] = market_data.get("market_state", "Unknown")
            parsed["aggression"] = market_data.get("aggression", "0.00")

            # Cache result
            self._cache[cache_key] = parsed
            if len(self._cache) > self._CACHE_SIZE:
                self._cache.popitem(last=False)

            return parsed
        except Exception as e:
            logger.error(f"Error during AI analysis: {e}")
            return {"direction": "FLAT", "rationale": f"Error: {e}"}

    # Prompt building and response parsing extracted to prompt_builder.py
    # Delegated via: build_entry_prompt(), parse_entry_response()
