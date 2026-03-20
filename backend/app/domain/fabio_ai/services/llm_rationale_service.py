"""LLM Rationale Service — Async enrichment layer per fix plan §9.

LLM enriches but NEVER decides. Runs async, never blocks signal pipeline.

Roles:
  - Rationale: Human-readable trade explanation (after gates pass)
  - Market narrative: On state changes
  - Risk commentary: On risk events
  - Setup grading: After aggression score
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class RationaleResult:
    """Result of LLM rationale generation."""

    text: str  # Generated rationale text
    success: bool  # True if LLM returned (not timeout)
    latency_ms: float  # Response time in ms


class LLMRationaleService:
    """Async LLM enrichment. Never blocks signal pipeline.

    Usage:
        service = LLMRationaleService(llm_predict_fn)
        # Non-blocking: generate rationale after gates pass
        rationale = await service.generate_rationale(context)
        # If timeout: returns empty rationale, signal still goes through
    """

    TIMEOUT_SECONDS = 5.0  # Short timeout — rationale is nice-to-have

    def __init__(self, llm_predict_fn=None) -> None:
        """Initialize with optional LLM prediction function.

        Args:
            llm_predict_fn: Async callable(str) -> str. If None, returns placeholder.
        """
        self._predict = llm_predict_fn

    async def generate_rationale(self, context: dict) -> RationaleResult:
        """Generate trade rationale asynchronously.

        Never blocks. Returns empty string on timeout or if no LLM available.
        """
        if self._predict is None:
            return RationaleResult(
                text="Rationale: deterministic pipeline validated all 12 gates.",
                success=True,
                latency_ms=0.0,
            )

        prompt = self._build_prompt(context)

        try:
            import time

            start = time.time()
            text = await asyncio.wait_for(
                self._predict(prompt),
                timeout=self.TIMEOUT_SECONDS,
            )
            latency = (time.time() - start) * 1000
            return RationaleResult(text=text, success=True, latency_ms=latency)
        except asyncio.TimeoutError:
            logger.debug("LLM rationale timeout (%.1fs)", self.TIMEOUT_SECONDS)
            return RationaleResult(
                text="Rationale unavailable (timeout)",
                success=False,
                latency_ms=self.TIMEOUT_SECONDS * 1000,
            )
        except Exception as e:
            logger.debug("LLM rationale error: %s", e)
            return RationaleResult(
                text=f"Rationale unavailable ({type(e).__name__})",
                success=False,
                latency_ms=0.0,
            )

    @staticmethod
    def _build_prompt(context: dict) -> str:
        """Build LLM prompt from AMT deterministic analysis."""
        return f"""AMT ANALYSIS (DETERMINISTIC — DO NOT OVERRIDE):
Market State: {context.get("market_state", "UNKNOWN")}
POC: {context.get("poc", 0):.2f} | VAH: {context.get("vah", 0):.2f} | VAL: {context.get("val", 0):.2f}
CVD Slope: {context.get("cvd_slope", 0):.2f} | Divergence: {context.get("cvd_divergence", "")}
Aggression: {context.get("aggression_score", 0):.1f}/4.5 ({context.get("aggression_confidence", "LOW")})
Gate: PASSED at gate {context.get("gate_number", 12)}
Setup: {context.get("setup_type", "NONE")} | R:R = {context.get("r_r_ratio", 0):.2f}
Direction: {context.get("direction", "FLAT")}
Entry: {context.get("entry_price", 0):.2f} | SL: {context.get("stop_loss", 0):.2f} | TP: {context.get("take_profit", 0):.2f}

TASK: Write a 2-3 sentence rationale for a trading journal.
Explain WHY this trade setup is valid using the AMT data above.
Do NOT suggest entry/exit — the system has already decided."""

    async def generate_narrative(self, state_change: dict) -> RationaleResult:
        """Generate market narrative on state change."""
        prompt = f"""Market state transition:
Previous: {state_change.get("previous", "INIT")}
Current: {state_change.get("current", "UNKNOWN")}
Trigger: {state_change.get("trigger", "")}
POC: {state_change.get("poc", 0):.2f} | VAH: {state_change.get("vah", 0):.2f} | VAL: {state_change.get("val", 0):.2f}

TASK: Write a 1-2 sentence market narrative explaining this transition."""
        if self._predict is None:
            return RationaleResult(text="", success=True, latency_ms=0.0)
        return await self.generate_rationale({"_custom_prompt": prompt})
