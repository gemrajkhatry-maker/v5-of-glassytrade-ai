"""LLM orchestration for entry-level prompts."""
from __future__ import annotations

import hashlib
import logging
from collections import OrderedDict
from typing import Any

from app.domain.shared.port import ILLMInference
from app.domain.fabio_ai.services.prompt_builder import build_entry_prompt
from app.domain.fabio_ai.services.response_parser import parse_entry_response

logger = logging.getLogger(__name__)

_DEFAULT_INSTRUCTION = (
    "You are READING the auction using Fabio AMT methodology. "
    "Interpret structure, order-flow, and context without speculative prediction. "
    "If the setup is weak or blocked by gates, return FLAT."
)


class GenerativeAIService:
    """Compatibility entry-model service for FABIO-style prompts."""

    _CACHE_SIZE = 8

    def __init__(self, llm_adapter: ILLMInference, instruction: str = ""):
        self.llm_adapter = llm_adapter
        self._instruction = instruction or _DEFAULT_INSTRUCTION
        self._cache: OrderedDict[str, dict[str, Any]] = OrderedDict()

    def is_ready(self) -> bool:
        return bool(self.llm_adapter.is_ready())

    def runtime_state(self) -> dict[str, str | None]:
        if hasattr(self.llm_adapter, "runtime_state"):
            return self.llm_adapter.runtime_state()  # type: ignore[attr-defined]
        return {"state": "UNKNOWN", "reason": "runtime_state not implemented"}

    def analyze_market(self, market_data: dict[str, Any]) -> dict[str, Any]:
        prompt_input = build_entry_prompt(market_data, allow_short=True)
        cache_key = hashlib.md5(prompt_input.encode()).hexdigest()
        if cache_key in self._cache:
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]
        try:
            raw_response = self.llm_adapter.predict(self._instruction, prompt_input)
            if raw_response is None:
                parsed = {
                    "direction": "FLAT",
                    "rationale": "LLM returned None",
                    "confidence": "Low",
                }
            else:
                parsed = parse_entry_response(raw_response)
            parsed["input_prompt"] = prompt_input
            parsed.setdefault("market_state", market_data.get("market_state", "Unknown"))
            parsed.setdefault("aggression", market_data.get("aggression", 0.0))
            self._cache[cache_key] = parsed
            if len(self._cache) > self._CACHE_SIZE:
                self._cache.popitem(last=False)
            return parsed
        except Exception as exc:  # noqa: BLE001
            logger.error("AI analysis failed: %s", exc)
            return {"direction": "FLAT", "rationale": f"Error: {exc}", "confidence": "Low"}
