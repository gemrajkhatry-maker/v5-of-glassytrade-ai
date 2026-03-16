import hashlib
import logging
from collections import OrderedDict
from typing import Dict, Any

from app.config import settings
from app.domain.ports.llm_inference import LLMInferencePort
from app.domain.fabio_ai.services.prompt_builder import build_entry_prompt, parse_entry_response

logger = logging.getLogger(__name__)


class GenerativeAIService:
    """Fabio Logic LLM service — entry decisions ONLY.

    Runtime contract:
      - Prompt input: natural-language AMT/flow narrative from build_entry_prompt()
      - Canonical output: single JSON object with direction/rationale/confidence/market_state
      - Legacy structured "Market State / Logic / Trigger" parsing remains as fallback

    This keeps runtime behavior aligned to one paper-trading contract even if
    older fine-tuning artifacts still exist in the repository.
    """

    # The EXACT instruction used during fine-tuning (from config for consistency)
    INSTRUCTION = settings.LLM_INSTRUCTION

    _CACHE_SIZE = 8

    def __init__(self, llm_adapter: LLMInferencePort):
        self.llm_adapter = llm_adapter
        self._cache: OrderedDict[str, Dict[str, Any]] = OrderedDict()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def is_ready(self) -> bool:
        """Check if the underlying LLM adapter is ready for inference."""
        return self.llm_adapter.is_ready()

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
            raw_response = self.llm_adapter.predict(self.INSTRUCTION, prompt_input)
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
