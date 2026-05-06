"""Asynchronous LLM rationale generation service."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class RationaleResult:
    text: str
    success: bool
    latency_ms: float


class LLMRationaleService:
    TIMEOUT_SECONDS = 5.0

    def __init__(self, llm_predict_fn=None):
        self._predict = llm_predict_fn

    async def generate_rationale(self, context: dict) -> RationaleResult:
        if self._predict is None:
            return RationaleResult("Rationale: deterministic pipeline validated all gates.", True, 0.0)
        prompt = self._build_prompt(context)
        try:
            start = asyncio.get_running_loop().time()
            text = await asyncio.wait_for(self._predict(prompt), timeout=self.TIMEOUT_SECONDS)
            latency = (asyncio.get_running_loop().time() - start) * 1000
            return RationaleResult(text=str(text), success=True, latency_ms=latency)
        except asyncio.TimeoutError:
            return RationaleResult("Rationale unavailable (timeout)", False, self.TIMEOUT_SECONDS * 1000)
        except Exception as exc:  # noqa: BLE001
            return RationaleResult(f"Rationale unavailable ({type(exc).__name__})", False, 0.0)

    async def generate_narrative(self, state_change: dict) -> RationaleResult:
        prompt = (
            f"Market transition: {state_change.get('previous', 'INIT')} -> {state_change.get('current', 'UNKNOWN')}. "
            f"Trigger: {state_change.get('trigger', '')}. "
            f"POC {state_change.get('poc', 0):.2f} VAH {state_change.get('vah', 0):.2f} VAL {state_change.get('val', 0):.2f}."
        )
        if self._predict is None:
            return RationaleResult(prompt, True, 0.0)
        return await self.generate_rationale({"_custom_prompt": prompt, **state_change})

    @staticmethod
    def _build_prompt(context: dict) -> str:
        return (
            f"AMT ANALYSIS:\n"
            f"Market State: {context.get('market_state', 'UNKNOWN')}\n"
            f"POC: {context.get('poc', 0):.2f} VAH: {context.get('vah', 0):.2f} VAL: {context.get('val', 0):.2f}\n"
            f"Direction: {context.get('direction', 'FLAT')} Entry: {context.get('entry_price', 0):.2f} "
            f"SL: {context.get('stop_loss', 0):.2f} TP: {context.get('take_profit', 0):.2f} "
            f"R:R {context.get('r_r_ratio', 0):.2f}\n"
            "Return 2-3 sentence rationale for journal. Do NOT alter signal."
        )
